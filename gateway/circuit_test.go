package main

import (
	"testing"
	"time"
)

func TestCircuitBreakerOpensAndProbes(t *testing.T) {
	cb := newCircuitBreaker(3, 20*time.Millisecond)
	for i := 0; i < 3; i++ {
		if !cb.allow() {
			t.Fatal("breaker should allow before threshold")
		}
		cb.record(false)
	}
	if cb.allow() {
		t.Fatal("breaker should be open after threshold")
	}
	time.Sleep(25 * time.Millisecond)
	if !cb.allow() {
		t.Fatal("breaker should allow one half-open probe after cool down")
	}
	// Failed probe re-opens immediately.
	cb.record(false)
	if cb.allow() {
		t.Fatal("failed half-open probe must re-open the breaker")
	}
	// Success resets.
	time.Sleep(25 * time.Millisecond)
	cb.allow()
	cb.record(true)
	if !cb.allow() {
		t.Fatal("successful probe should close the breaker")
	}
}
