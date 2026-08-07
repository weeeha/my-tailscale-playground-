// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"io/fs"
	"runtime"
	"time"
)

// Collect reads one full Vitals snapshot through fsys (real root: os.DirFS("/"))
// using the injected Options for host-specific bits.
func Collect(fsys fs.FS, opt Options) (Vitals, error) {
	collectedAt := opt.CollectedAt
	if collectedAt == "" {
		collectedAt = time.Now().UTC().Format("2006-01-02T15:04:05Z")
	}
	sleep := opt.Sleep
	if sleep == nil {
		sleep = func() { time.Sleep(200 * time.Millisecond) }
	}

	read := func(name string) []byte { b, _ := fs.ReadFile(fsys, name); return b }

	memTotal, memAvail := parseMemInfo(read("proc/meminfo"))

	// CPU%: two samples of /proc/stat, sleep between.
	t1, i1 := cpuSample(read("proc/stat"))
	sleep()
	t2, i2 := cpuSample(read("proc/stat"))

	var disk DiskStats
	if opt.Statfs != nil {
		disk, _ = opt.Statfs("/")
	}

	present, throttled, underVolt := false, false, false
	if opt.Vcgencmd != nil {
		present, throttled, underVolt = opt.Vcgencmd()
	}

	v := Vitals{
		Schema:      1,
		Host:        opt.Host,
		CollectedAt: collectedAt,
		Config: Config{
			Model:       parseModel(read("proc/device-tree/model")),
			Serial:      parseSerial(read("proc/cpuinfo")),
			CPUCores:    runtime.NumCPU(),
			MemTotalMB:  int(memTotal / 1024),
			OS:          parseOSRelease(read("etc/os-release")),
			Kernel:      opt.Kernel,
			DiskTotalGB: disk.TotalGB,
		},
		Thermal: Thermal{
			SoCTempC:        readThermal(fsys),
			VcgencmdPresent: present,
			ThrottledNow:    throttled,
			UnderVoltageNow: underVolt,
		},
		Health: Health{
			Load1:       parseLoadavg(read("proc/loadavg")),
			CPUPct:      cpuPercent(t1, i1, t2, i2),
			MemPct:      memPct(memTotal, memAvail),
			DiskUsedPct: disk.UsedPct,
			DiskFreeGB:  disk.FreeGB,
			UptimeS:     parseUptime(read("proc/uptime")),
		},
		SideThings: SideThings{
			Displays: readDisplays(fsys),
			USB:      []string{},
			USBCount: usbCount(fsys),
			Battery:  readBattery(fsys),
		},
		App: appHealth(opt.Host, fsys, opt.HomeRel),
	}
	return v, nil
}
