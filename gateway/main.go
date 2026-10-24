// Command cots-gateway is the edge gateway in front of the FastAPI backend.
//
// Responsibilities:
//   - verify HS256 JWTs and inject identity headers (X-Tenant-Id, ...)
//   - generate / propagate a global X-Trace-Id
//   - reverse-proxy traffic, forcing an immediate Flush on every SSE write
//   - emit an SSE error fallback when the upstream goes silent
//   - retry idempotent non-stream failures once and trip a circuit breaker
//
// It uses only the Go standard library.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

type config struct {
	addr             string
	backend          *url.URL
	jwtSecret        string
	internalToken    string
	devMode          bool
	idleTimeout      time.Duration
	requestTimeout   time.Duration
	frontendDist     string
	maxBodyBytes     int64
	rateCapacity     float64
	rateRefill       float64
	redisAddr        string
	redisPassword    string
	breakerThreshold int
	breakerOpenFor   time.Duration
}

func loadConfig() *config {
	backendRaw := envOr("BACKEND_URL", "http://127.0.0.1:8000")
	backend, err := url.Parse(backendRaw)
	if err != nil {
		log.Fatalf("invalid BACKEND_URL %q: %v", backendRaw, err)
	}
	idleSec, _ := strconv.Atoi(envOr("SSE_IDLE_TIMEOUT_SEC", "45"))
	reqSec, _ := strconv.Atoi(envOr("UPSTREAM_TIMEOUT_SEC", "180"))
	return &config{
		addr:             envOr("GATEWAY_ADDR", ":8080"),
		backend:          backend,
		jwtSecret:        envOr("GATEWAY_JWT_SECRET", "cots-dev-secret-change-me-in-prod"),
		internalToken:    envOr("GATEWAY_INTERNAL_TOKEN", "cots-internal-dev-token"),
		devMode:          envOr("GATEWAY_DEV_MODE", "true") != "false",
		idleTimeout:      time.Duration(idleSec) * time.Second,
		requestTimeout:   time.Duration(reqSec) * time.Second,
		frontendDist:     os.Getenv("FRONTEND_DIST"),
		maxBodyBytes:     1 << 20, // 1 MiB
		rateCapacity:     20,      // burst
		rateRefill:       2,       // +2 requests/sec/tenant
		redisAddr:        envOr("REDIS_ADDR", ""),
		redisPassword:    os.Getenv("REDIS_PASSWORD"),
		breakerThreshold: 4,
		breakerOpenFor:   30 * time.Second,
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

var tracePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9\-_]{7,63}$`)

type ctxKey string

const traceCtxKey ctxKey = "traceID"

// ---------------------------------------------------------------------------
// Safe concurrent writer for the SSE watchdog
// ---------------------------------------------------------------------------
type sseWriter struct {
	http.ResponseWriter
	flusher http.Flusher
	mu      sync.Mutex
}

func (w *sseWriter) WriteChunk(p []byte) {
	w.mu.Lock()
	defer w.mu.Unlock()
	_, _ = w.ResponseWriter.Write(p)
	w.flusher.Flush() // force flush — never let a proxy buffer SSE events
}

func (w *sseWriter) WriteFallback(event string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	payload, _ := json.Marshal(map[string]any{
		"message": "upstream agent timed out (gateway idle fallback)",
		"event":   event,
	})
	_, _ = io.WriteString(w.ResponseWriter,
		"event: error\ndata: "+string(payload)+"\n\n")
	w.flusher.Flush()
}

// ---------------------------------------------------------------------------
// Gateway
// ---------------------------------------------------------------------------
type gateway struct {
	cfg     *config
	client  *http.Client
	breaker *circuitBreaker
	limiter *distributedLimiter
}

func newGateway(cfg *config) *gateway {
	transport := &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		MaxIdleConns:          100,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
	}
	return &gateway{
		cfg:     cfg,
		client:  &http.Client{Transport: transport},
		breaker: newCircuitBreaker(cfg.breakerThreshold, cfg.breakerOpenFor),
		limiter: newDistributedLimiter(
			cfg.redisAddr, cfg.redisPassword, cfg.rateCapacity, cfg.rateRefill),
	}
}

func (g *gateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	g.setCORSHeaders(w)
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	if strings.HasPrefix(r.URL.Path, "/api/") {
		g.proxyHandler(w, r)
		return
	}
	g.serveFrontend(w, r)
}

func (g *gateway) proxyHandler(w http.ResponseWriter, r *http.Request) {
	if !g.breaker.allow() {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{
			"error": "backend circuit breaker open",
		})
		return
	}

	traceID := r.Header.Get("X-Trace-Id")
	if !tracePattern.MatchString(traceID) {
		traceID = generateTraceID()
	}
	ctx := context.WithValue(r.Context(), traceCtxKey, traceID)
	r = r.WithContext(ctx)
	w.Header().Set("X-Trace-Id", traceID)

	tenantKey := "anon"
	if err := g.injectIdentity(r); err != nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": err.Error()})
		return
	}
	tenantKey = r.Header.Get("X-Tenant-Id")
	if tenantKey == "" {
		tenantKey = "anon"
	}

	// Predictable load: per-tenant token bucket on mutating/stream requests.
	if r.Method != http.MethodGet && r.Method != http.MethodHead &&
		r.Method != http.MethodOptions {
		decision := g.limiter.allow(tenantKey)
		if !decision.allowed {
			w.Header().Set("Retry-After",
				strconv.Itoa(int(decision.retryAfter.Seconds())+1))
			writeJSON(w, http.StatusTooManyRequests, map[string]string{
				"error":       "rate limit exceeded",
				"retry_after": decision.retryAfter.String(),
				"limiter":     decision.source,
			})
			return
		}
	}

	// Bound request bodies to protect the backend.
	if r.Body != nil {
		r.Body = http.MaxBytesReader(w, r.Body, g.cfg.maxBodyBytes)
	}

	if r.ContentLength > g.cfg.maxBodyBytes {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{
			"error":     "request body too large",
			"max_bytes": strconv.FormatInt(g.cfg.maxBodyBytes, 10),
		})
		return
	}

	isSSE := strings.Contains(r.URL.Path, "/stream") ||
		strings.Contains(r.Header.Get("Accept"), "text/event-stream")

	if isSSE {
		g.proxySSE(w, r, traceID)
		return
	}
	g.proxyBuffered(w, r)
}

func (g *gateway) doUpstreamWithCancel(r *http.Request) (*http.Response, context.CancelFunc, error) {
	upstreamURL := *g.cfg.backend
	upstreamURL.Path = r.URL.Path
	upstreamURL.RawQuery = r.URL.RawQuery

	ctx, cancel := context.WithTimeout(r.Context(), g.cfg.requestTimeout)
	req := r.Clone(ctx)
	req.URL = &upstreamURL
	req.RequestURI = ""
	req.Host = upstreamURL.Host
	// Prove to the backend that identity headers originate at the gateway.
	req.Header.Set("X-Gateway-Token", g.cfg.internalToken)
	resp, err := g.client.Do(req)
	if err != nil {
		cancel()
		return nil, nil, err
	}
	return resp, cancel, nil
}

// injectIdentity verifies the JWT and forwards canonical identity headers.
func (g *gateway) injectIdentity(r *http.Request) error {
	token := ""
	if h := r.Header.Get("Authorization"); strings.HasPrefix(h, "Bearer ") {
		token = strings.TrimPrefix(h, "Bearer ")
	}

	var claims *jwtClaims
	if token != "" {
		c, err := verifyJWT(token, g.cfg.jwtSecret)
		if err != nil {
			return err
		}
		claims = c
	} else if g.cfg.devMode {
		claims = &jwtClaims{
			Sub: "1", TenantID: float64(1), TenantCode: "acme",
			Email: "ops@acme.example",
		}
	} else {
		return errors.New("missing bearer token")
	}

	r.Header.Set("X-User-Id", claims.Sub)
	r.Header.Set("X-Tenant-Id", claims.tenantIDString())
	r.Header.Set("X-Tenant-Code", claims.TenantCode)
	r.Header.Set("X-User-Email", claims.Email)
	return nil
}

// ---- SSE: stream through with per-chunk flush + idle timeout fallback ----
func (g *gateway) proxySSE(w http.ResponseWriter, r *http.Request, traceID string) {
	resp, cancel, err := g.doUpstreamWithCancel(r)
	if err != nil {
		g.breaker.record(false)
		writeJSON(w, http.StatusBadGateway, map[string]string{
			"error": "upstream unavailable", "detail": err.Error(),
		})
		return
	}
	defer cancel()
	defer resp.Body.Close()
	g.breaker.record(resp.StatusCode < 500)

	h := w.Header()
	for k, vs := range resp.Header {
		if strings.EqualFold(k, "Content-Length") || strings.EqualFold(k, "Transfer-Encoding") {
			continue
		}
		for _, v := range vs {
			h.Add(k, v)
		}
	}
	h.Set("Cache-Control", "no-cache")
	h.Set("X-Accel-Buffering", "no")
	h.Set("Connection", "keep-alive")
	w.WriteHeader(resp.StatusCode)

	flusher, ok := w.(http.Flusher)
	if !ok {
		_, _ = io.Copy(w, resp.Body)
		return
	}
	flusher.Flush()
	sw := &sseWriter{ResponseWriter: w, flusher: flusher}

	chunkCh := make(chan []byte, 16)
	errCh := make(chan error, 1)
	go func() {
		buf := make([]byte, 2048)
		for {
			n, readErr := resp.Body.Read(buf)
			if n > 0 {
				piece := make([]byte, n)
				copy(piece, buf[:n])
				select {
				case chunkCh <- piece:
				case <-r.Context().Done():
					return
				}
			}
			if readErr != nil {
				select {
				case errCh <- readErr:
				case <-r.Context().Done():
				}
				return
			}
		}
	}()

	idle := time.NewTimer(g.cfg.idleTimeout)
	defer idle.Stop()
	for {
		select {
		case chunk := <-chunkCh:
			sw.WriteChunk(chunk)
			if !idle.Stop() {
				select {
				case <-idle.C:
				default:
				}
			}
			idle.Reset(g.cfg.idleTimeout)
		case <-idle.C:
			log.Printf("SSE idle timeout trace=%s after %s", traceID, g.cfg.idleTimeout)
			sw.WriteFallback("agent_idle_timeout")
			return
		case err := <-errCh:
			if !errors.Is(err, io.EOF) {
				log.Printf("SSE upstream closed with error trace=%s: %v", traceID, err)
			}
			return
		case <-r.Context().Done():
			log.Printf("client disconnected trace=%s", traceID)
			return
		}
	}
}

// ---- Buffered: one automatic retry for safe (non-body-replay) methods ----
func (g *gateway) proxyBuffered(w http.ResponseWriter, r *http.Request) {
	resp, cancel, err := g.doUpstreamWithCancel(r)
	if cancel != nil {
		defer cancel()
	}
	retryable := r.Method == http.MethodGet || r.Method == http.MethodHead ||
		r.Method == http.MethodDelete
	if (err != nil || (resp != nil && resp.StatusCode >= 500)) && retryable {
		if cancel != nil {
			cancel()
		}
		if resp != nil {
			_ = resp.Body.Close()
		}
		log.Printf("retrying upstream once trace=%v status=%v err=%v",
			r.Context().Value(traceCtxKey), respStatus(resp), err)
		g.breaker.record(false)
		resp, cancel, err = g.doUpstreamWithCancel(r)
		if cancel != nil {
			defer cancel()
		}
	}
	if err != nil {
		g.breaker.record(false)
		writeJSON(w, http.StatusBadGateway, map[string]string{
			"error": "upstream unavailable", "detail": err.Error(),
		})
		return
	}
	if resp.StatusCode >= 500 {
		g.breaker.record(false)
	} else {
		g.breaker.record(true)
	}
	defer resp.Body.Close()

	for k, vs := range resp.Header {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func respStatus(resp *http.Response) int {
	if resp == nil {
		return 0
	}
	return resp.StatusCode
}

func (g *gateway) setCORSHeaders(w http.ResponseWriter) {
	h := w.Header()
	h.Set("Access-Control-Allow-Origin", "*")
	h.Set("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,PATCH,OPTIONS")
	h.Set("Access-Control-Allow-Headers",
		"Authorization,Content-Type,Last-Event-ID,X-Trace-Id,X-Tenant-Id")
	h.Set("Access-Control-Expose-Headers", "X-Trace-Id,X-Run-Id")
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// serveFrontend serves the built SPA when FRONTEND_DIST is mounted.
func (g *gateway) serveFrontend(w http.ResponseWriter, r *http.Request) {
	if g.cfg.frontendDist == "" {
		writeJSON(w, http.StatusOK, map[string]string{
			"service": "cots-gateway",
			"api":     "/api/v1",
			"status":  "running",
			"ui":      "set FRONTEND_DIST to serve the built web app",
		})
		return
	}
	path := r.URL.Path
	if path == "/" {
		path = "/index.html"
	}
	file := g.cfg.frontendDist + path
	if _, err := os.Stat(file); os.IsNotExist(err) {
		file = g.cfg.frontendDist + "/index.html" // SPA fallback
	}
	http.ServeFile(w, r, file)
}

func main() {
	cfg := loadConfig()
	gw := newGateway(cfg)
	server := &http.Server{
		Addr:              cfg.addr,
		Handler:           gw,
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("Cots gateway listening on %s -> %s (dev=%v)",
		cfg.addr, cfg.backend, cfg.devMode)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
