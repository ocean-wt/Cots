package main

import (
	"context"
	"errors"
	"net"
	"strconv"
	"time"
)

// Minimal RESP2 client. Using RESP2 (not HELLO/RESP3) keeps one code path
// compatible with both Redis 6.x and 7.x. Every command opens a short-lived
// connection — the limiter is a single Lua call per request, so pooling adds
// complexity without value and lets a dead shared connection leak failures.
type redisClient struct {
	addr     string
	password string
}

func newRedisClient(addr, password string) *redisClient {
	return &redisClient{addr: addr, password: password}
}

var errRedisReply = errors.New("unexpected redis reply")

func (c *redisClient) do(ctx context.Context, args ...any) (any, error) {
	d := net.Dialer{Timeout: 200 * time.Millisecond}
	conn, err := d.DialContext(ctx, "tcp", c.addr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(300 * time.Millisecond))
	if c.password != "" {
		if _, err := c.writeRead(conn, "AUTH", c.password); err != nil {
			return nil, err
		}
	}
	return c.writeRead(conn, args...)
}

func (c *redisClient) writeRead(conn net.Conn, args ...any) (any, error) {
	if _, err := conn.Write(encodeCommand(args)); err != nil {
		return nil, err
	}
	return readReply(conn)
}

func encodeCommand(args []any) []byte {
	var b []byte
	b = append(b, '*')
	b = strconv.AppendInt(b, int64(len(args)), 10)
	b = append(b, '\r', '\n')
	for _, a := range args {
		var s string
		switch v := a.(type) {
		case string:
			s = v
		case int:
			s = strconv.Itoa(v)
		case int64:
			s = strconv.FormatInt(v, 10)
		case float64:
			s = strconv.FormatFloat(v, 'f', -1, 64)
		default:
			s = ""
		}
		b = append(b, '$')
		b = strconv.AppendInt(b, int64(len(s)), 10)
		b = append(b, '\r', '\n')
		b = append(b, s...)
		b = append(b, '\r', '\n')
	}
	return b
}

func readReply(conn net.Conn) (any, error) {
	line, err := readLine(conn)
	if err != nil {
		return nil, err
	}
	if len(line) == 0 {
		return nil, errRedisReply
	}
	switch line[0] {
	case '+':
		return string(line[1:]), nil
	case '-':
		return nil, errors.New(string(line[1:]))
	case ':':
		return strconv.ParseInt(string(line[1:]), 10, 64)
	case '$':
		n, err := strconv.Atoi(string(line[1:]))
		if err != nil {
			return nil, err
		}
		if n < 0 {
			return nil, nil
		}
		buf := make([]byte, n+2)
		if _, err := readFull(conn, buf); err != nil {
			return nil, err
		}
		return string(buf[:n]), nil
	case '*':
		n, err := strconv.Atoi(string(line[1:]))
		if err != nil {
			return nil, err
		}
		if n < 0 {
			return nil, nil
		}
		arr := make([]any, n)
		for i := 0; i < n; i++ {
			if arr[i], err = readReply(conn); err != nil {
				return nil, err
			}
		}
		return arr, nil
	}
	return nil, errRedisReply
}

func readLine(conn net.Conn) ([]byte, error) {
	var out []byte
	one := make([]byte, 1)
	for {
		if _, err := conn.Read(one); err != nil {
			return nil, err
		}
		if len(out) > 0 && out[len(out)-1] == '\r' && one[0] == '\n' {
			return out[:len(out)-1], nil
		}
		out = append(out, one[0])
		if len(out) > 1<<16 {
			return nil, errRedisReply
		}
	}
}

func readFull(conn net.Conn, buf []byte) (int, error) {
	total := 0
	for total < len(buf) {
		n, err := conn.Read(buf[total:])
		total += n
		if err != nil {
			if total == len(buf) {
				return total, nil
			}
			return total, err
		}
	}
	return total, nil
}
