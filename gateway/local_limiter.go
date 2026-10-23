package main

import (
	"sync"
	"time"
)

// In-process token bucket, used for unit tests and as the safety fallback
// when the shared Redis limiter is unreachable.
type tokenBucket struct {
	capacity   float64
	refillRate float64 // tokens per second
	tokens     float64
	last       time.Time
}

func (b *tokenBucket) take(now time.Time) bool {
	elapsed := now.Sub(b.last).Seconds()
	b.last = now
	b.tokens = min64(b.capacity, b.tokens+elapsed*b.refillRate)
	if b.tokens >= 1 {
		b.tokens--
		return true
	}
	return false
}

func (b *tokenBucket) retryAfter(now time.Time) time.Duration {
	needed := 1 - b.tokens
	return time.Duration(needed/b.refillRate*float64(time.Second)) + 100*time.Millisecond
}

func min64(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

type rateLimiter struct {
	mu       sync.Mutex
	buckets  map[string]*tokenBucket
	capacity float64
	rate     float64
}

func newRateLimiter(capacity, rate float64) *rateLimiter {
	return &rateLimiter{
		buckets:  make(map[string]*tokenBucket),
		capacity: capacity,
		rate:     rate,
	}
}

func (l *rateLimiter) allow(key string) (bool, time.Duration) {
	now := time.Now()
	l.mu.Lock()
	defer l.mu.Unlock()
	bucket, ok := l.buckets[key]
	if !ok {
		bucket = &tokenBucket{
			capacity:   l.capacity,
			refillRate: l.rate,
			tokens:     l.capacity,
			last:       now,
		}
		l.buckets[key] = bucket
	}
	if bucket.take(now) {
		return true, 0
	}
	return false, bucket.retryAfter(now)
}
