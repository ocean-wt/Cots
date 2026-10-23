package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

// Minimal HS256 JWT verification — zero third-party dependencies.

type jwtClaims struct {
	Sub        string `json:"sub"`
	TenantID   any    `json:"tenant_id"`
	TenantCode string `json:"tenant_code"`
	Email      string `json:"email"`
	Exp        int64  `json:"exp"`
}

func sign(signingInput, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(signingInput))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

var (
	errBadJWT = errors.New("malformed token")
	errAlg    = errors.New("unsupported jwt alg")
	errSig    = errors.New("invalid signature")
	errExp    = errors.New("token expired")
)

func verifyJWT(token, secret string) (*jwtClaims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, errBadJWT
	}

	headerBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return nil, errBadJWT
	}
	var header struct {
		Alg string `json:"alg"`
		Typ string `json:"typ"`
	}
	if err := json.Unmarshal(headerBytes, &header); err != nil || header.Alg != "HS256" {
		return nil, errAlg
	}

	signingInput := parts[0] + "." + parts[1]
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(signingInput))
	expected := mac.Sum(nil)
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !hmac.Equal(signature, expected) {
		return nil, errSig
	}

	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, errBadJWT
	}
	var claims jwtClaims
	if err := json.Unmarshal(payload, &claims); err != nil {
		return nil, errBadJWT
	}
	if claims.Exp > 0 && time.Now().Unix() > claims.Exp {
		return nil, errExp
	}
	return &claims, nil
}

// asInt coerces the numeric/string tenant id claim into a header-safe string.
func (c *jwtClaims) tenantIDString() string {
	switch v := c.TenantID.(type) {
	case float64:
		return formatInt(int64(v))
	case string:
		return v
	case int:
		return formatInt(int64(v))
	default:
		return "1"
	}
}
