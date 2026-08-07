// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"math"
	"testing"
)

func approx(a, b float64) bool { return math.Abs(a-b) < 0.05 }

func TestParseMemInfo(t *testing.T) {
	in := []byte("MemTotal:     429876 kB\nMemFree: 100000 kB\nMemAvailable:  214938 kB\n")
	total, avail := parseMemInfo(in)
	if total != 429876 || avail != 214938 {
		t.Fatalf("got total=%d avail=%d", total, avail)
	}
	if !approx(memPct(total, avail), 50.0) {
		t.Errorf("memPct=%v want ~50", memPct(total, avail))
	}
	if memPct(0, 0) != 0 {
		t.Errorf("memPct(0,0) must be 0, not NaN")
	}
}

func TestCPUSampleAndPercent(t *testing.T) {
	// fields: user nice system idle iowait irq softirq ...
	s1 := []byte("cpu  100 0 50 1000 0 0 0\ncpu0 ...\n")
	s2 := []byte("cpu  175 0 75 1100 0 0 0\n") // total=1350 => dt=200, di=100 => 50%
	t1, i1 := cpuSample(s1)
	t2, i2 := cpuSample(s2)
	if t1 != 1150 || i1 != 1000 {
		t.Fatalf("sample1 total=%d idle=%d", t1, i1)
	}
	// dt=200, didle=100 => busy fraction = 50%
	if !approx(cpuPercent(t1, i1, t2, i2), 50.0) {
		t.Errorf("cpuPercent=%v want ~50", cpuPercent(t1, i1, t2, i2))
	}
	if cpuPercent(10, 5, 10, 5) != 0 {
		t.Errorf("zero delta must be 0%%")
	}
}

func TestParseScalars(t *testing.T) {
	if v := parseLoadavg([]byte("0.34 0.22 0.18 1/200 1234")); !approx(v, 0.34) {
		t.Errorf("load=%v", v)
	}
	if v := parseUptime([]byte("90432.12 360000.00")); v != 90432 {
		t.Errorf("uptime=%d", v)
	}
	if s := parseSerial([]byte("foo\nSerial\t\t: 10000000abcd1234\nbar")); s != "10000000abcd1234" {
		t.Errorf("serial=%q", s)
	}
	if s := parseSerial([]byte("no serial here")); s != "" {
		t.Errorf("missing serial must be empty, got %q", s)
	}
	if s := parseOSRelease([]byte(`PRETTY_NAME="Debian GNU/Linux 13 (trixie)"` + "\nID=debian\n")); s != "Debian GNU/Linux 13 (trixie)" {
		t.Errorf("os=%q", s)
	}
	if s := parseModel([]byte("Raspberry Pi Zero 2 W\x00\x00")); s != "Raspberry Pi Zero 2 W" {
		t.Errorf("model=%q", s)
	}
}
