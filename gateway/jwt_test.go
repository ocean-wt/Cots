package main

import (
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

func b64JSON(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func makeToken(t *testing.T, secret, alg string, claims map[string]any, sig string) string {
	t.Helper()
	return b64JSON(t, map[string]any{"alg": alg, "typ": "JWT"}) +
		"." + b64JSON(t, claims) + "." + sig
}

func signInput(t *testing.T, secret, alg string, claims map[string]any) string {
	t.Helper()
	input := b64JSON(t, map[string]any{"alg": alg, "typ": "JWT"}) +
		"." + b64JSON(t, claims)
	return input + "." + sign(input, secret)
}

func TestVerifyJWTValid(t *testing.T) {
	claims := map[string]any{
		"sub": "42", "tenant_id": 7.0, "tenant_code": "acme",
		"email": "a@b.c", "exp": time.Now().Add(time.Hour).Unix(),
	}
	token := signInput(t, "secret", "HS256", claims)

	got, err := verifyJWT(token, "secret")
	if err != nil {
		t.Fatalf("expected valid token, got %v", err)
	}
	if got.Sub != "42" || got.tenantIDString() != "7" || got.TenantCode != "acme" {
		t.Fatalf("unexpected claims: %+v", got)
	}
}

func TestVerifyJWTRejects(t *testing.T) {
	claims := map[string]any{"sub": "1", "exp": time.Now().Add(time.Hour).Unix()}

	wrongSecretInput := b64JSON(t, map[string]any{"alg": "HS256"}) +
		"." + b64JSON(t, claims)
	wrongSecret := wrongSecretInput + "." + sign(wrongSecretInput, "other")

	cases := map[string]string{
		"bad signature": makeToken(t, "s", "HS256", claims, "deadbeef"),
		"alg none":      makeToken(t, "s", "none", claims, ""),
		"alg RS256":     makeToken(t, "s", "RS256", claims, "x"),
		"garbage":       "not-a-jwt",
		"wrong secret":  wrongSecret,
		"empty":         "",
	}
	for name, token := range cases {
		if _, err := verifyJWT(token, "s"); err == nil {
			t.Errorf("%s: expected rejection", name)
		}
	}
}

func TestVerifyJWTExpired(t *testing.T) {
	claims := map[string]any{"sub": "1", "exp": time.Now().Add(-time.Minute).Unix()}
	token := signInput(t, "s", "HS256", claims)
	if _, err := verifyJWT(token, "s"); err != errExp {
		t.Fatalf("expected expiry error, got %v", err)
	}
}

func TestTraceIDPolicy(t *testing.T) {
	id := generateTraceID()
	if !tracePattern.MatchString(id) {
		t.Fatalf("trace id does not match policy: %s", id)
	}
	seen := map[string]bool{}
	for i := 0; i < 1000; i++ {
		x := generateTraceID()
		if seen[x] {
			t.Fatal("trace id collision")
		}
		seen[x] = true
	}
	if !tracePattern.MatchString("trc-9f3a2c7b1e4d") {
		t.Fatal("seed trace id should be accepted")
	}
	if tracePattern.MatchString("../etc/passwd") {
		t.Fatal("path traversal must not be accepted as trace id")
	}
}
