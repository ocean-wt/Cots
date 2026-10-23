package main

import (
	"context"
	"time"
)

// Token-bucket Lua script. KEYS[1] = bucket key, ARGV = cap, refill/s, now(ms).
// Uses a SET NX fallback when the key is missing (older versions lack
// HSET NX on individual fields), then HGETALL via HMGET in one round trip.
var tokenBucketScript = `
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local exists = redis.call('EXISTS', key)
local tokens, last
if exists == 0 then
  tokens = cap
  last = now
else
  local vals = redis.call('HMGET', key, 't', 'l')
  tokens = tonumber(vals[1])
  last = tonumber(vals[2])
end
tokens = math.min(cap, tokens + (now - last) / 1000.0 * rate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', key, 't', tokens, 'l', now)
redis.call('PEXPIRE', key, math.max(2000, math.ceil(cap / rate * 2000)))
local retry_ms = 0
if allowed == 0 then
  retry_ms = math.ceil((1 - tokens) / rate * 1000)
end
return {allowed, retry_ms}
`

// decision returned by the limiter.
type limitDecision struct {
	allowed    bool
	retryAfter time.Duration
	source     string // "redis" | "local"
}

// distributedLimiter enforces a per-tenant token bucket in Redis so all
// gateway replicas share one quota. Redis outages degrade to an
// independent in-process bucket (fail-open with a local safety bound).
type distributedLimiter struct {
	rdb          *redisClient
	capacity     float64
	refillRate   float64
	local        *rateLimiter
	scriptLoaded bool
}

func newDistributedLimiter(addr, password string, capacity, refill float64) *distributedLimiter {
	return &distributedLimiter{
		rdb:        newRedisClient(addr, password),
		capacity:   capacity,
		refillRate: refill,
		local:      newRateLimiter(capacity, refill),
	}
}

func (l *distributedLimiter) allow(tenant string) limitDecision {
	ctx, cancel := context.WithTimeout(context.Background(), 350*time.Millisecond)
	defer cancel()
	reply, err := l.rdb.do(ctx, "EVAL", tokenBucketScript, 1,
		"cots:rl:"+tenant, l.capacity, l.refillRate, time.Now().UnixMilli())
	if err != nil {
		// Degrade: independent local bucket keeps a safety bound.
		ok, retry := l.local.allow(tenant)
		return limitDecision{allowed: ok, retryAfter: retry, source: "local"}
	}
	arr, ok := reply.([]any)
	if !ok || len(arr) != 2 {
		ok, retry := l.local.allow(tenant)
		return limitDecision{allowed: ok, retryAfter: retry, source: "local"}
	}
	allowedFlag, _ := arr[0].(int64)
	retryMs, _ := arr[1].(int64)
	if allowedFlag == 1 {
		return limitDecision{allowed: true, source: "redis"}
	}
	return limitDecision{
		allowed:    false,
		retryAfter: time.Duration(retryMs)*time.Millisecond + 50*time.Millisecond,
		source:     "redis",
	}
}
