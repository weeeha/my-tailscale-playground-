// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"errors"
	"net"
	"testing"
)

func TestPickTailscaleAddr(t *testing.T) {
	addrs := []net.Addr{
		&net.IPNet{IP: net.ParseIP("192.168.4.40")},
		&net.IPNet{IP: net.ParseIP("100.78.29.28")}, // CGNAT range
		&net.IPNet{IP: net.ParseIP("100.64.0.0")},
	}
	got, err := pickTailscaleAddr(addrs)
	if err != nil || got != "100.78.29.28" {
		t.Fatalf("got %q err=%v want 100.78.29.28", got, err)
	}
	if _, err := pickTailscaleAddr([]net.Addr{&net.IPNet{IP: net.ParseIP("10.0.0.1")}}); err == nil {
		t.Errorf("no 100.x => error")
	}
}

func TestListenWithRetry(t *testing.T) {
	calls := 0
	listen := func(addr string) (net.Listener, error) {
		calls++
		if calls < 3 {
			return nil, errors.New("cannot assign requested address")
		}
		return net.Listen("tcp", "127.0.0.1:0") // success on the 3rd try
	}
	ln, err := listenWithRetry("100.78.29.28:9100", 5, func() {}, listen)
	if err != nil || ln == nil || calls != 3 {
		t.Fatalf("calls=%d err=%v ln=%v (want 3 calls + non-nil listener)", calls, err, ln)
	}
	_ = ln.Close()
}

func TestListenWithRetryExhausted(t *testing.T) {
	calls := 0
	want := errors.New("always fails")
	ln, err := listenWithRetry("100.78.29.28:9100", 2, func() {}, func(string) (net.Listener, error) {
		calls++
		return nil, want
	})
	if ln != nil || !errors.Is(err, want) || calls != 2 {
		t.Fatalf("calls=%d ln=%v err=%v (want 2 calls, nil listener, want-err)", calls, ln, err)
	}
}

func TestPickTailscaleAddrIPAddr(t *testing.T) {
	got, err := pickTailscaleAddr([]net.Addr{
		&net.IPAddr{IP: net.ParseIP("192.168.4.40")},
		&net.IPAddr{IP: net.ParseIP("100.96.7.111")},
	})
	if err != nil || got != "100.96.7.111" {
		t.Fatalf("got %q err=%v want 100.96.7.111", got, err)
	}
}
