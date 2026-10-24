package main

import (
	"testing"
	"time"
)

func TestRateLimiterBurstAndRefill(t *testing.T) {
	now := time.Now()
	l := newRateLimiter(3, 10) // 3 burst, +10/sec
	for i := 0; i < 3; i++ {
		if ok, _ := l.allow("tenant-a"); !ok {
			t.Fatalf("request %d within burst should pass", i+1)
		}
	}
	if ok, retry := l.allow("tenant-a"); ok || retry <= 0 {
		t.Fatalf("4th request must be rejected with retry-after, got ok=%v retry=%v", ok, retry)
	}
	// Other tenants have independent buckets.
	if ok, _ := l.allow("tenant-b"); !ok {
		t.Fatal("tenants must be isolated")
	}
	// After refill time the bucket accepts again.
	if ok, _ := l.allowAt("tenant-a", now.Add(200*time.Millisecond)); !ok {
		t.Fatal("bucket should have refilled after 200ms at 10 tokens/sec")
	}
}

// allowAt is a test-only variant accepting a synthetic clock.
func (l *rateLimiter) allowAt(key string, now time.Time) (bool, time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()
	bucket, ok := l.buckets[key]
	if !ok {
		return false, 0
	}
	elapsed := now.Sub(bucket.last).Seconds()
	bucket.last = now
	bucket.tokens = min64(bucket.capacity, bucket.tokens+elapsed*bucket.refillRate)
	if bucket.tokens >= 1 {
		bucket.tokens--
		return true, 0
	}
	return false, bucket.retryAfter(now)
}
