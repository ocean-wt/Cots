package main

import (
	"crypto/rand"
	"encoding/hex"
	"strconv"
)

// generateTraceID returns a globally unique trc-<24 hex chars> identifier.
func generateTraceID() string {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		// rand.Read never fails on supported platforms; keep the format.
		return "trc-000000000000000000000000"
	}
	return "trc-" + hex.EncodeToString(b)
}

func formatInt(v int64) string {
	return strconv.FormatInt(v, 10)
}
