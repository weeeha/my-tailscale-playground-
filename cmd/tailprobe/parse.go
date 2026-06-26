// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"strconv"
	"strings"
)

// parseMemInfo returns MemTotal and MemAvailable in kB.
func parseMemInfo(b []byte) (totalKB, availKB int64) {
	for _, ln := range strings.Split(string(b), "\n") {
		f := strings.Fields(ln)
		if len(f) < 2 {
			continue
		}
		switch f[0] {
		case "MemTotal:":
			totalKB, _ = strconv.ParseInt(f[1], 10, 64)
		case "MemAvailable:":
			availKB, _ = strconv.ParseInt(f[1], 10, 64)
		}
	}
	return totalKB, availKB
}

func memPct(totalKB, availKB int64) float64 {
	if totalKB <= 0 {
		return 0
	}
	return (1 - float64(availKB)/float64(totalKB)) * 100
}

// cpuSample sums ALL fields of the aggregate "cpu " line as the busy+idle total
// (the standard htop/vmstat method). This intentionally differs from
// fleet_collect.sh, which summed only user+nice+system+idle; the difference is a
// slightly lower cpu_pct during heavy iowait and is not a bug.
// idle is the 4th numeric field (index 3).
func cpuSample(b []byte) (total, idle int64) {
	for _, ln := range strings.Split(string(b), "\n") {
		if !strings.HasPrefix(ln, "cpu ") {
			continue
		}
		f := strings.Fields(ln)[1:] // drop "cpu"
		for i, tok := range f {
			n, err := strconv.ParseInt(tok, 10, 64)
			if err != nil {
				break
			}
			total += n
			if i == 3 { // idle
				idle = n
			}
		}
		return total, idle
	}
	return 0, 0
}

func cpuPercent(total1, idle1, total2, idle2 int64) float64 {
	dt := total2 - total1
	di := idle2 - idle1
	if dt <= 0 {
		return 0
	}
	return (1 - float64(di)/float64(dt)) * 100
}

func parseLoadavg(b []byte) float64 {
	f := strings.Fields(string(b))
	if len(f) == 0 {
		return 0
	}
	v, _ := strconv.ParseFloat(f[0], 64)
	return v
}

func parseUptime(b []byte) int64 {
	f := strings.Fields(string(b))
	if len(f) == 0 {
		return 0
	}
	v, _ := strconv.ParseFloat(f[0], 64)
	return int64(v)
}

func parseSerial(cpuinfo []byte) string {
	for _, ln := range strings.Split(string(cpuinfo), "\n") {
		if strings.HasPrefix(ln, "Serial") {
			if _, val, ok := strings.Cut(ln, ":"); ok {
				return strings.TrimSpace(val)
			}
		}
	}
	return ""
}

func parseOSRelease(b []byte) string {
	for _, ln := range strings.Split(string(b), "\n") {
		if v, ok := strings.CutPrefix(ln, "PRETTY_NAME="); ok {
			return strings.Trim(strings.TrimSpace(v), `"`)
		}
	}
	return ""
}

func parseModel(b []byte) string {
	return strings.Trim(string(b), "\x00\r\n\t ")
}
