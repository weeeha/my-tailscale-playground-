// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"encoding/json"
	"testing"
	"testing/fstest"
)

func fixtureFS() fstest.MapFS {
	return fstest.MapFS{
		"proc/device-tree/model": {Data: []byte("Raspberry Pi Zero 2 W\x00")},
		"proc/cpuinfo":           {Data: []byte("processor\t: 0\nSerial\t\t: 10000000abcd\n")},
		"proc/meminfo":           {Data: []byte("MemTotal: 429876 kB\nMemAvailable: 214938 kB\n")},
		"proc/loadavg":           {Data: []byte("0.34 0.2 0.1 1/100 5\n")},
		"proc/uptime":            {Data: []byte("90432.0 1.0\n")},
		"proc/stat":              {Data: []byte("cpu  100 0 50 1000 0 0 0\n")},
		"etc/os-release":         {Data: []byte("PRETTY_NAME=\"Debian GNU/Linux 13 (trixie)\"\n")},
		"sys/class/thermal/thermal_zone0/temp": {Data: []byte("54731\n")},
		"sys/class/drm/card0-HDMI-A-1/status": {Data: []byte("connected\n")},
		"proc/101/cmdline":                    {Data: []byte("chromium\x00--kiosk")},
	}
}

func TestCollectProducesSchema1(t *testing.T) {
	opt := Options{
		Host:        "plantdashboard",
		CollectedAt: "2026-06-07T00:00:00Z",
		Kernel:      "6.12.0-rpi",
		Statfs:      func(string) (DiskStats, error) { return DiskStats{TotalGB: 29.0, UsedPct: 36.0, FreeGB: 18.6}, nil },
		Vcgencmd:    func() (bool, bool, bool) { return false, false, false },
		Sleep:       func() {},
	}
	v, err := Collect(fixtureFS(), opt)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}
	if v.Schema != 1 || v.Host != "plantdashboard" {
		t.Errorf("schema/host: %+v", v)
	}
	if v.Config.Model != "Raspberry Pi Zero 2 W" || v.Config.CPUCores < 1 || v.Config.Kernel != "6.12.0-rpi" {
		t.Errorf("config: %+v", v.Config)
	}
	if v.Thermal.SoCTempC == nil || *v.Thermal.SoCTempC < 54.7 {
		t.Errorf("thermal: %+v", v.Thermal)
	}
	if v.Health.DiskFreeGB != 18.6 || v.Health.UptimeS != 90432 {
		t.Errorf("health: %+v", v.Health)
	}
	if len(v.SideThings.Displays) != 1 {
		t.Errorf("displays: %+v", v.SideThings.Displays)
	}
	if v.App.Name != "dashboard" || v.App.Running == nil || !*v.App.Running {
		t.Errorf("app: %+v", v.App)
	}
	// Must round-trip as valid JSON with non-nil slices (never JSON null arrays).
	b, _ := json.Marshal(v)
	if !json.Valid(b) {
		t.Fatalf("invalid json")
	}
}
