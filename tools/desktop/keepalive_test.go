package main

import (
	"testing"
	"time"
)

// With keepalives firing often, a healthy connection keeps working: the fake server replies to the pings (ssh
// DiscardRequests), so the fail counter never reaches the limit and the connection is not closed.
func TestKeepalivePingsDoNotDisturbAHealthyConnection(t *testing.T) {
	oldInt, oldFails := keepaliveInterval, keepaliveMaxFails
	keepaliveInterval, keepaliveMaxFails = 15*time.Millisecond, 2
	defer func() { keepaliveInterval, keepaliveMaxFails = oldInt, oldFails }()

	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()

	time.Sleep(100 * time.Millisecond) // several keepalive ticks hit the live server
	code, err := d.Run("echo hi", nil, nil)
	if err != nil || code != 0 {
		t.Fatalf("connection should still be healthy after keepalives: code=%d err=%v", code, err)
	}
}

// Close() is safe to call more than once and stops the keepalive goroutine without blocking.
func TestCloseIsIdempotentAndStopsKeepalive(t *testing.T) {
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	d.Close()
	d.Close() // must not panic (closeOnce) or block
}
