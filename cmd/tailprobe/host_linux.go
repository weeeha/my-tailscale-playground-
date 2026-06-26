// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

//go:build linux

package main

import (
	"strings"

	"golang.org/x/sys/unix"
)

// realKernel returns the kernel release string (uname -r), no subprocess.
func realKernel() string {
	var u unix.Utsname
	if err := unix.Uname(&u); err != nil {
		return ""
	}
	return strings.TrimRight(string(u.Release[:]), "\x00")
}
