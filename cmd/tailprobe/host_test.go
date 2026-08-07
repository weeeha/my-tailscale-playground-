// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"errors"
	"testing"
)

func TestVcgencmdParse(t *testing.T) {
	// 0x50005 has bit 0x1 (under-voltage now) and bit 0x4 (throttled now).
	present, thr, uv := parseThrottled("throttled=0x50005", nil)
	if !present || !thr || !uv {
		t.Fatalf("present=%v thr=%v uv=%v want all true", present, thr, uv)
	}
	// 0x0 => no flags.
	_, thr, uv = parseThrottled("throttled=0x0", nil)
	if thr || uv {
		t.Errorf("0x0 must clear flags")
	}
	// command error (non-Broadcom) => present:false, flags false.
	present, thr, uv = parseThrottled("", errors.New("not found"))
	if present || thr || uv {
		t.Errorf("error => present:false and no flags, got present=%v", present)
	}
}
