// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"testing"
	"testing/fstest"
)

func TestReadThermal(t *testing.T) {
	fsys := fstest.MapFS{
		"sys/class/thermal/thermal_zone0/temp": {Data: []byte("54731\n")},
	}
	got := readThermal(fsys)
	if got == nil || *got < 54.7 || *got > 54.8 {
		t.Fatalf("thermal=%v want ~54.7", got)
	}
	if readThermal(fstest.MapFS{}) != nil {
		t.Errorf("absent thermal must be nil (=> JSON null)")
	}
}

func TestReadDisplays(t *testing.T) {
	fsys := fstest.MapFS{
		"sys/class/drm/card0-HDMI-A-1/status": {Data: []byte("connected\n")},
		"sys/class/drm/card0-HDMI-A-2/status": {Data: []byte("disconnected\n")},
	}
	got := readDisplays(fsys)
	if len(got) != 1 || got[0].Connector != "HDMI-A-1" || got[0].Status != "connected" {
		t.Fatalf("displays=%+v", got)
	}
}

func TestUSBCountAndBattery(t *testing.T) {
	fsys := fstest.MapFS{
		"sys/bus/usb/devices/1-1/idVendor":            {Data: []byte("1234\n")},
		"sys/bus/usb/devices/usb1/idVendor":           {Data: []byte("1d6b\n")},
		"sys/bus/usb/devices/1-0:1.0/bInterfaceClass": {Data: []byte("09\n")}, // not counted (no idVendor)
	}
	if n := usbCount(fsys); n != 2 {
		t.Errorf("usbCount=%d want 2", n)
	}
	if b := readBattery(fstest.MapFS{}); b.Present {
		t.Errorf("no power_supply => present:false")
	}
	bat := readBattery(fstest.MapFS{"sys/class/power_supply/BAT0/capacity": {Data: []byte("87\n")}})
	if !bat.Present || bat.Pct == nil || *bat.Pct != 87 {
		t.Errorf("battery=%+v want present:true pct:87", bat)
	}
}
