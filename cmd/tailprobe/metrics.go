// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

// Package main — Prometheus exposition for /metrics.
package main

import (
	"fmt"
	"io"
	"strconv"
)

func b2f(b bool) float64 {
	if b {
		return 1
	}
	return 0
}

// WritePrometheus writes the numeric vitals in Prometheus exposition format.
func WritePrometheus(w io.Writer, v Vitals) {
	host := strconv.Quote(v.Host)
	lbl := "{host=" + host + "}"

	type g struct {
		name string
		val  float64
	}
	gauges := []g{
		{"tailprobe_cpu_percent", v.Health.CPUPct},
		{"tailprobe_mem_percent", v.Health.MemPct},
		{"tailprobe_load1", v.Health.Load1},
		{"tailprobe_disk_used_percent", v.Health.DiskUsedPct},
		{"tailprobe_disk_free_gb", v.Health.DiskFreeGB},
		{"tailprobe_uptime_seconds", float64(v.Health.UptimeS)},
		{"tailprobe_cpu_cores", float64(v.Config.CPUCores)},
		{"tailprobe_throttled", b2f(v.Thermal.ThrottledNow)},
		{"tailprobe_under_voltage", b2f(v.Thermal.UnderVoltageNow)},
		{"tailprobe_usb_count", float64(v.SideThings.USBCount)},
	}
	for _, m := range gauges {
		fmt.Fprintf(w, "# TYPE %s gauge\n%s%s %s\n", m.name, m.name, lbl, strconv.FormatFloat(m.val, 'g', -1, 64))
	}
	// soc_temp is nullable: omit when absent.
	if v.Thermal.SoCTempC != nil {
		fmt.Fprintf(w, "# TYPE tailprobe_soc_temp_celsius gauge\ntailprobe_soc_temp_celsius%s %s\n",
			lbl, strconv.FormatFloat(*v.Thermal.SoCTempC, 'g', -1, 64))
	}
	// app_running carries an app label; only emit when the app class is known.
	if v.App.Name != "" {
		var val float64
		switch {
		case v.App.Running == nil:
			val = -1 // unknown
		case *v.App.Running:
			val = 1
		default:
			val = 0
		}
		fmt.Fprintf(w, "# TYPE tailprobe_app_running gauge\ntailprobe_app_running{host=%s,app=%s} %s\n",
			host, strconv.Quote(v.App.Name), strconv.FormatFloat(val, 'g', -1, 64))
	}
}
