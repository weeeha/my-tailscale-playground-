// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

//go:build !linux

// Stub so the package builds/tests on non-Linux dev hosts; the probe only runs on the Linux SBCs.
package main

func realKernel() string { return "" }
