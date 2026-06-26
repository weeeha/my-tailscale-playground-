// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

// Command tailprobe serves one device's vitals over a Tailscale-only HTTP
// endpoint, reproducing the schema:1 JSON of tailtop/agent/fleet_collect.sh.
package main

// Vitals is the schema:1 object consumed by tailtop's Vitals.from_collect_json.
type Vitals struct {
	Schema      int        `json:"schema"`
	Host        string     `json:"host"`
	CollectedAt string     `json:"collected_at"`
	Config      Config     `json:"config"`
	Thermal     Thermal    `json:"thermal"`
	Health      Health     `json:"health"`
	SideThings  SideThings `json:"side_things"`
	App         App        `json:"app"`
}

type Config struct {
	Model       string  `json:"model"`
	Serial      string  `json:"serial"`
	CPUCores    int     `json:"cpu_cores"`
	MemTotalMB  int     `json:"mem_total_mb"`
	OS          string  `json:"os"`
	Kernel      string  `json:"kernel"`
	DiskTotalGB float64 `json:"disk_total_gb"`
}

type Thermal struct {
	SoCTempC        *float64 `json:"soc_temp_c"` // nil => JSON null (no sensor)
	VcgencmdPresent bool     `json:"vcgencmd_present"`
	ThrottledNow    bool     `json:"throttled_now"`
	UnderVoltageNow bool     `json:"under_voltage_now"`
}

type Health struct {
	Load1       float64 `json:"load1"`
	CPUPct      float64 `json:"cpu_pct"`
	MemPct      float64 `json:"mem_pct"`
	DiskUsedPct float64 `json:"disk_used_pct"`
	DiskFreeGB  float64 `json:"disk_free_gb"`
	UptimeS     int64   `json:"uptime_s"`
}

type Display struct {
	Connector string `json:"connector"`
	Status    string `json:"status"`
}

type SideThings struct {
	Displays []Display `json:"displays"`
	USB      []string  `json:"usb"` // always [] (parity with the script)
	USBCount int       `json:"usb_count"`
	Battery  Battery   `json:"battery"`
}

type Battery struct {
	Present bool `json:"present"`
	Pct     *int `json:"pct,omitempty"`
}

type App struct {
	Name       string `json:"name"`
	Running    *bool  `json:"running"` // nil => JSON null (unknown, never false-critical)
	LastRender string `json:"last_render"`
}

// DiskStats is the disk reading produced by the injected statfs function.
type DiskStats struct {
	TotalGB float64
	UsedPct float64
	FreeGB  float64
}

// Options carries the host-specific, injectable inputs to Collect so the
// collector is fully unit-testable off-device.
type Options struct {
	Host        string                          // os.Hostname() in production
	CollectedAt string                          // RFC3339; empty => time.Now().UTC()
	Kernel      string                          // unix.Uname Release in production
	HomeRel     string                          // home dir relative to fsys root, e.g. "home/pi"
	Statfs      func(path string) (DiskStats, error)
	Vcgencmd    func() (present, throttled, underVolt bool)
	Sleep       func() // CPU% inter-sample sleep; nil => 200ms
}
