// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"strings"
	"testing"
)

func TestWritePrometheus(t *testing.T) {
	temp := 54.7
	running := true
	v := Vitals{
		Host:    "plantdashboard",
		Config:  Config{CPUCores: 4},
		Thermal: Thermal{SoCTempC: &temp, ThrottledNow: true},
		Health:  Health{CPUPct: 17.4, MemPct: 38.0, DiskFreeGB: 18.6, UptimeS: 90432},
		App:     App{Name: "dashboard", Running: &running},
	}
	var sb strings.Builder
	WritePrometheus(&sb, v)
	out := sb.String()

	wantLines := []string{
		`# TYPE tailprobe_cpu_percent gauge`,
		`tailprobe_cpu_percent{host="plantdashboard"} 17.4`,
		`tailprobe_soc_temp_celsius{host="plantdashboard"} 54.7`,
		`tailprobe_throttled{host="plantdashboard"} 1`,
		`tailprobe_uptime_seconds{host="plantdashboard"} 90432`,
		`tailprobe_app_running{host="plantdashboard",app="dashboard"} 1`,
	}
	for _, w := range wantLines {
		if !strings.Contains(out, w) {
			t.Errorf("missing line:\n  %s\nin:\n%s", w, out)
		}
	}

	// nil temp must be omitted entirely (no NaN, no zero).
	v.Thermal.SoCTempC = nil
	sb.Reset()
	WritePrometheus(&sb, v)
	if strings.Contains(sb.String(), "tailprobe_soc_temp_celsius") {
		t.Errorf("nil temp must be omitted, got:\n%s", sb.String())
	}

	// app.running == false ⇒ 0
	falseR := false
	v.App.Running = &falseR
	sb.Reset()
	WritePrometheus(&sb, v)
	if !strings.Contains(sb.String(), `tailprobe_app_running{host="plantdashboard",app="dashboard"} 0`) {
		t.Errorf("running=false must emit 0, got:\n%s", sb.String())
	}
	// app.running == nil ⇒ -1 (unknown)
	v.App.Running = nil
	sb.Reset()
	WritePrometheus(&sb, v)
	if !strings.Contains(sb.String(), `tailprobe_app_running{host="plantdashboard",app="dashboard"} -1`) {
		t.Errorf("running=nil must emit -1, got:\n%s", sb.String())
	}
}
