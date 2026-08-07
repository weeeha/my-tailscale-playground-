// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"io/fs"
	"regexp"
	"strings"
)

type appClass struct {
	name string
	re   *regexp.Regexp
}

// classForHost maps a hostname to its app class (case-insensitive), porting the
// case statement in fleet_collect.sh. Order matters: first match wins.
func classForHost(host string) (appClass, bool) {
	h := strings.ToLower(host)
	switch {
	case strings.Contains(h, "clock"):
		return appClass{"superclock", regexp.MustCompile(`(?i)clock|server\.ts|tsx`)}, true
	case strings.Contains(h, "eink"), strings.Contains(h, "ink"):
		return appClass{"epaper", regexp.MustCompile(`(?i)eink|epaper|e-paper|render|display`)}, true
	case strings.Contains(h, "dashboard"), strings.Contains(h, "plant"), strings.Contains(h, "orangepi"):
		return appClass{"dashboard", regexp.MustCompile(`(?i)chromium|dashboard|kiosk|server\.py`)}, true
	}
	return appClass{}, false
}

// anyProcessMatches walks proc/<pid>/cmdline entries and reports whether any
// command line matches re. Returns true on the first match.
func anyProcessMatches(fsys fs.FS, re *regexp.Regexp) bool {
	entries, _ := fs.ReadDir(fsys, "proc")
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		b, err := fs.ReadFile(fsys, "proc/"+e.Name()+"/cmdline")
		if err != nil || len(b) == 0 {
			continue
		}
		// cmdline args are NUL-separated; join with spaces for matching.
		cmd := strings.ReplaceAll(string(b), "\x00", " ")
		if re.MatchString(cmd) {
			return true
		}
	}
	return false
}

// appHealth returns the app name/running/last_render for a host. running is nil
// (unknown) unless a process matches — never false (no false-critical).
func appHealth(host string, fsys fs.FS, homeRel string) App {
	cls, ok := classForHost(host)
	if !ok {
		return App{}
	}
	a := App{Name: cls.name}
	if anyProcessMatches(fsys, cls.re) {
		t := true
		a.Running = &t
	}
	if cls.name == "epaper" && homeRel != "" {
		a.LastRender = newestRenderMTime(fsys, homeRel)
	}
	return a
}

// newestRenderMTime returns the RFC3339 mtime of the newest $HOME/*.png or
// $HOME/last_frame* file, or "" if none.
func newestRenderMTime(fsys fs.FS, homeRel string) string {
	var newest string
	var newestUnix int64
	for _, pat := range []string{homeRel + "/*.png", homeRel + "/last_frame*"} {
		matches, _ := fs.Glob(fsys, pat)
		for _, m := range matches {
			info, err := fs.Stat(fsys, m)
			if err != nil {
				continue
			}
			if u := info.ModTime().Unix(); u > newestUnix {
				newestUnix = u
				newest = info.ModTime().UTC().Format("2006-01-02T15:04:05Z")
			}
		}
	}
	return newest
}
