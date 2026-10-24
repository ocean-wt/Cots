package main

import (
	"sync"
	"time"
)

// Tiny consecutive-failure circuit breaker for the upstream backend.
type circuitBreaker struct {
	mu             sync.Mutex
	failThreshold  int
	openFor        time.Duration
	failures       int
	openedAt       time.Time
	halfOpenProbed bool
}

func newCircuitBreaker(threshold int, openFor time.Duration) *circuitBreaker {
	return &circuitBreaker{failThreshold: threshold, openFor: openFor}
}

func (cb *circuitBreaker) allow() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	if cb.failures < cb.failThreshold {
		return true
	}
	if time.Since(cb.openedAt) > cb.openFor {
		// half-open: let one probe through and re-arm around its result.
		cb.halfOpenProbed = true
		return true
	}
	return false
}

func (cb *circuitBreaker) record(success bool) {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	if success {
		cb.failures = 0
		cb.halfOpenProbed = false
		return
	}
	if cb.halfOpenProbed {
		cb.openedAt = time.Now()
		cb.halfOpenProbed = false
		return
	}
	cb.failures++
	if cb.failures >= cb.failThreshold {
		cb.openedAt = time.Now()
	}
}
