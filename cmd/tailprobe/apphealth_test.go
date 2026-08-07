// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"fmt"
	"testing"
	"testing/fstest"
	"time"
)

func procFS(cmdlines ...string) fstest.MapFS {
	m := fstest.MapFS{}
	for i, c := range cmdlines {
		// /proc/<pid>/cmdline is NUL-separated.
		m["proc/"+pid(i)+"/cmdline"] = &fstest.MapFile{Data: []byte(c)}
	}
	return m
}
func pid(i int) string { return fmt.Sprintf("%d", 100+i) }

func TestAppHealthClassesAndMatch(t *testing.T) {
	// clock host, a matching process running.
	a := appHealth("SuperClockFast", procFS("node\x00--import\x00tsx\x00server.ts"), "")
	if a.Name != "superclock" || a.Running == nil || !*a.Running {
		t.Fatalf("clock running: %+v", a)
	}
	// dashboard host, no matching process => running nil (unknown), NOT false.
	d := appHealth("plantdashboard", procFS("bash\x00-c\x00sleep"), "")
	if d.Name != "dashboard" || d.Running != nil {
		t.Fatalf("dashboard unknown: %+v (running must be nil)", d)
	}
	// unknown host class => empty name, running nil.
	u := appHealth("mac-studio", procFS("anything"), "")
	if u.Name != "" || u.Running != nil {
		t.Fatalf("unknown class: %+v", u)
	}
}

func TestAppHealthEpaperLastRender(t *testing.T) {
	ts := time.Date(2026, 6, 7, 1, 2, 3, 0, time.UTC)
	fsys := fstest.MapFS{
		"proc/101/cmdline":       {Data: []byte("python3\x00epaper_render.py")},
		"home/pi/last_frame.png": {Data: []byte("x"), ModTime: ts},
	}
	a := appHealth("bedroom-eink", fsys, "home/pi")
	if a.Name != "epaper" || a.Running == nil || !*a.Running {
		t.Fatalf("epaper running: %+v", a)
	}
	if a.LastRender != "2026-06-07T01:02:03Z" {
		t.Errorf("last_render=%q want 2026-06-07T01:02:03Z", a.LastRender)
	}
}
