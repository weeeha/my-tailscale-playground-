// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"io/fs"
	"path"
	"regexp"
	"strconv"
	"strings"
)

func readTrimmed(fsys fs.FS, name string) (string, bool) {
	b, err := fs.ReadFile(fsys, name)
	if err != nil {
		return "", false
	}
	return strings.TrimSpace(string(b)), true
}

// readThermal returns SoC temp in °C, or nil if no thermal_zone0 (=> JSON null).
func readThermal(fsys fs.FS) *float64 {
	s, ok := readTrimmed(fsys, "sys/class/thermal/thermal_zone0/temp")
	if !ok {
		return nil
	}
	milli, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil
	}
	c := milli / 1000
	return &c
}

var cardPrefix = regexp.MustCompile(`^card[0-9]*-`)

func readDisplays(fsys fs.FS) []Display {
	out := []Display{}
	matches, _ := fs.Glob(fsys, "sys/class/drm/*/status")
	for _, m := range matches {
		s, ok := readTrimmed(fsys, m)
		if !ok || s != "connected" {
			continue
		}
		name := cardPrefix.ReplaceAllString(path.Base(path.Dir(m)), "")
		out = append(out, Display{Connector: name, Status: "connected"})
	}
	return out
}

// usbCount counts real USB devices (entries exposing idVendor) under
// /sys/bus/usb/devices. NOTE: this differs slightly from `lsusb | wc -l`
// (which counts interfaces too); it is informational, not alerting-critical.
func usbCount(fsys fs.FS) int {
	matches, _ := fs.Glob(fsys, "sys/bus/usb/devices/*/idVendor")
	return len(matches)
}

func readBattery(fsys fs.FS) Battery {
	matches, _ := fs.Glob(fsys, "sys/class/power_supply/*/capacity")
	for _, m := range matches {
		s, ok := readTrimmed(fsys, m)
		if !ok {
			continue
		}
		if pct, err := strconv.Atoi(s); err == nil {
			return Battery{Present: true, Pct: &pct}
		}
	}
	return Battery{Present: false}
}
