// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"context"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

// realStatfs reads disk stats for path using statfs(2). Used in production;
// tests inject a fake via Options.Statfs.
func realStatfs(path string) (DiskStats, error) {
	var st unix.Statfs_t
	if err := unix.Statfs(path, &st); err != nil {
		return DiskStats{}, err
	}
	bs := uint64(st.Bsize)
	total := st.Blocks * bs
	free := st.Bavail * bs
	var used uint64
	if total > free {
		used = total - free
	}
	var usedPct float64
	if total > 0 {
		usedPct = float64(used) / float64(total) * 100
	}
	const gb = 1 << 30
	return DiskStats{
		TotalGB: float64(total) / gb,
		UsedPct: usedPct,
		FreeGB:  float64(free) / gb,
	}, nil
}

// parseThrottled interprets `vcgencmd get_throttled` output. An error (e.g.
// vcgencmd absent on Allwinner) yields present:false and no flags — never a
// false-critical (parity with fleet_collect.sh).
func parseThrottled(out string, err error) (present, throttled, underVolt bool) {
	if err != nil {
		return false, false, false
	}
	_, hex, ok := strings.Cut(strings.TrimSpace(out), "=")
	if !ok {
		return true, false, false
	}
	v, perr := strconv.ParseInt(strings.TrimPrefix(hex, "0x"), 16, 64)
	if perr != nil {
		return true, false, false
	}
	return true, v&0x4 != 0, v&0x1 != 0
}

// realVcgencmd shells out to vcgencmd (Broadcom only) with a short timeout.
func realVcgencmd() (present, throttled, underVolt bool) {
	if _, err := exec.LookPath("vcgencmd"); err != nil {
		return false, false, false
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "vcgencmd", "get_throttled").Output()
	return parseThrottled(string(out), err)
}

// realKernel is OS-specific (uname -r on Linux); see host_linux.go / host_other.go.
