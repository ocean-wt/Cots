package main

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

// Integration test against a real Redis (REDIS_ADDR env). Skips when absent.
// Proves the shared quota: a single tenant bucket is exhausted regardless of
// which gateway "replica" (separate limiter instances, same Redis) calls it.
func TestDistributedLimiterSharedAcrossReplicas(t *testing.T) {
	addr := os.Getenv("REDIS_ADDR")
	if addr == "" {
		t.Skip("REDIS_ADDR not set")
	}
	a := newDistributedLimiter(addr, "", 5, 10)
	b := newDistributedLimiter(addr, "", 5, 10)
	key := "shared-" + strings.ReplaceAll(t.Name(), "/", "-")
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if _, err := a.rdb.do(ctx, "DEL", "cots:rl:"+key); err != nil {
		t.Skipf("redis not reachable: %v", err)
	}

	allowed, rejected := 0, 0
	for i := 0; i < 8; i++ {
		l := a
		if i%2 == 0 {
			l = b
		}
		d := l.allow(key)
		if d.allowed {
			allowed++
			if d.source != "redis" {
				t.Fatalf("expected redis decision, got %q", d.source)
			}
		} else {
			rejected++
			if d.retryAfter <= 0 {
				t.Fatal("rejected decision must carry retry-after")
			}
		}
	}
	if allowed != 5 || rejected != 3 {
		t.Fatalf("shared quota wrong: allowed=%d rejected=%d", allowed, rejected)
	}
}

func TestDistributedLimiterFallsBackWhenRedisDown(t *testing.T) {
	// Nothing listens on 6398: fail fast to the local bucket, not hang.
	l := newDistributedLimiter("127.0.0.1:6398", "", 3, 100)
	done := make(chan limitDecision, 1)
	go func() { done <- l.allow("tenant-fallback") }()
	select {
	case d := <-done:
		if !d.allowed || d.source != "local" {
			t.Fatalf("expected local-fallback allow, got %+v", d)
		}
	case <-time.After(time.Second):
		t.Fatal("Redis-down fallback took too long (must fail fast)")
	}
}
