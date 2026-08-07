# tailprobe Agent Implementation Plan (Phase 0, Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tailprobe`, a single static Go binary that runs on each Linux SBC and serves that device's vitals over a Tailscale-only HTTP endpoint (`/healthz`, `/vitals`, `/metrics`), reproducing the exact `fleet_collect.sh` `schema:1` JSON.

**Architecture:** A new in-tree command at `cmd/tailprobe/`. The vitals collector is built from small **pure parse functions** over `/proc` and `/sys` data, composed by a `Collect(fsys fs.FS, opt Options)` function that reads through an injectable `fs.FS` root (real root = `os.DirFS("/")`; tests use `testing/fstest.MapFS`). The two host-specific bits — disk (`unix.Statfs`) and `vcgencmd` (subprocess) — are injected as function values so everything is unit-testable on macOS. An HTTP mux serves the collector; the listener binds an explicit `--addr` (the device's `100.x:9100`, supplied by the installer in Plan 3) with retry, so there is no runtime Tailscale discovery in Phase 0.

**Tech Stack:** Go (built via the repo's pinned `./tool/go`), `golang.org/x/sys/unix` (already a dependency), `io/fs` + `testing/fstest`, `net/http` + `net/http/httptest`. No new dependencies.

**Contract source of truth:** `tailtop/agent/fleet_collect.sh` (the shell script being ported) and `tailtop/tests/fixtures/vitals_orangepi.json` / `vitals_fastclock.json` (the JSON shape `tailtop`'s `Vitals.from_collect_json` consumes). The probe's `/vitals` output MUST deserialize through that same parser.

**Build/test commands:** This repo vendors its Go toolchain — there is no system `go` on `PATH`. Use `./tool/go` for everything (e.g. `./tool/go test ./cmd/tailprobe/...`). All commands below assume CWD = repo root.

---

## File Structure

All files live under `cmd/tailprobe/` (Go `package main`, module `tailscale.com`):

| File | Responsibility |
|------|----------------|
| `vitals_types.go` | The `Vitals`/`Config`/`Thermal`/`Health`/`SideThings`/`App` structs (the `schema:1` shape) + `Options`. |
| `parse.go` | Pure `/proc` text parsers: meminfo, loadavg, uptime, cpuinfo serial, os-release, model, CPU sampling. |
| `sysread.go` | `fs.FS` readers for `/sys`: thermal, DRM displays, USB count, battery. |
| `host.go` (+ `host_linux.go`/`host_other.go`) | Injected host bits: disk via `unix.Statfs`, `vcgencmd` subprocess; kernel via `unix.Uname` is build-tag-split so the package builds on the macOS dev host. |
| `apphealth.go` | App-health by hostname class (the `pgrep` port over `/proc/<pid>/cmdline`). |
| `collect.go` | `Collect(fsys, opt)` — composes everything into a `Vitals`. |
| `metrics.go` | `WritePrometheus(w, v)` — Prometheus exposition text for `/metrics`. |
| `server.go` | `newMux(collect)` — `/healthz`, `/vitals`, `/metrics` handlers. |
| `main.go` | Flags, address resolution + retry listen, wiring. |
| `*_test.go` | One test file per source file above. |

---

## Task 1: Scaffold `cmd/tailprobe/` and the Vitals types

**Files:**
- Create: `cmd/tailprobe/vitals_types.go`
- Test: `cmd/tailprobe/vitals_types_test.go`

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/vitals_types_test.go
package main

import (
	"encoding/json"
	"testing"
)

func TestVitalsMarshalsSchema1Shape(t *testing.T) {
	temp := 54.7
	running := true
	v := Vitals{
		Schema:      1,
		Host:        "fastclock",
		CollectedAt: "2026-06-07T00:24:42Z",
		Config:      Config{Model: "Raspberry Pi Zero 2 W", CPUCores: 4, MemTotalMB: 419},
		Thermal:     Thermal{SoCTempC: &temp, VcgencmdPresent: true},
		Health:      Health{Load1: 0.34, CPUPct: 17.4, UptimeS: 90432},
		SideThings:  SideThings{Displays: []Display{}, USB: []string{}, Battery: Battery{Present: false}},
		App:         App{Name: "superclock", Running: &running},
	}
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var got map[string]any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	// schema:1 top-level keys the tailtop parser reads.
	for _, k := range []string{"schema", "host", "collected_at", "config", "thermal", "health", "side_things", "app"} {
		if _, ok := got[k]; !ok {
			t.Errorf("missing top-level key %q in %s", k, b)
		}
	}
	// nullable fields must be JSON null when nil, never omitted.
	none := Vitals{}
	b2, _ := json.Marshal(none)
	var got2 map[string]any
	_ = json.Unmarshal(b2, &got2)
	thermal := got2["thermal"].(map[string]any)
	if v, ok := thermal["soc_temp_c"]; !ok || v != nil {
		t.Errorf("soc_temp_c should be JSON null when unset, got %v (present=%v)", v, ok)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run TestVitalsMarshals -v`
Expected: FAIL — `undefined: Vitals` (package doesn't compile yet).

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/vitals_types.go
// Command tailprobe serves one device's vitals over a Tailscale-only HTTP
// endpoint, reproducing the schema:1 JSON of tailtop/agent/fleet_collect.sh.
package main

// Vitals is the schema:1 object consumed by tailtop's Vitals.from_collect_json.
type Vitals struct {
	Schema      int        `json:"schema"`
	Host        string     `json:"host"`
	CollectedAt string     `json:"collected_at"`
	Config      Config     `json:"config"`
	Thermal     Thermal    `json:"thermal"`
	Health      Health     `json:"health"`
	SideThings  SideThings `json:"side_things"`
	App         App        `json:"app"`
}

type Config struct {
	Model       string  `json:"model"`
	Serial      string  `json:"serial"`
	CPUCores    int     `json:"cpu_cores"`
	MemTotalMB  int     `json:"mem_total_mb"`
	OS          string  `json:"os"`
	Kernel      string  `json:"kernel"`
	DiskTotalGB float64 `json:"disk_total_gb"`
}

type Thermal struct {
	SoCTempC        *float64 `json:"soc_temp_c"` // nil => JSON null (no sensor)
	VcgencmdPresent bool     `json:"vcgencmd_present"`
	ThrottledNow    bool     `json:"throttled_now"`
	UnderVoltageNow bool     `json:"under_voltage_now"`
}

type Health struct {
	Load1       float64 `json:"load1"`
	CPUPct      float64 `json:"cpu_pct"`
	MemPct      float64 `json:"mem_pct"`
	DiskUsedPct float64 `json:"disk_used_pct"`
	DiskFreeGB  float64 `json:"disk_free_gb"`
	UptimeS     int64   `json:"uptime_s"`
}

type Display struct {
	Connector string `json:"connector"`
	Status    string `json:"status"`
}

type SideThings struct {
	Displays []Display `json:"displays"`
	USB      []string  `json:"usb"` // always [] (parity with the script)
	USBCount int       `json:"usb_count"`
	Battery  Battery   `json:"battery"`
}

type Battery struct {
	Present bool `json:"present"`
	Pct     *int `json:"pct,omitempty"`
}

type App struct {
	Name       string `json:"name"`
	Running    *bool  `json:"running"` // nil => JSON null (unknown, never false-critical)
	LastRender string `json:"last_render"`
}

// DiskStats is the disk reading produced by the injected statfs function.
type DiskStats struct {
	TotalGB  float64
	UsedPct  float64
	FreeGB   float64
}

// Options carries the host-specific, injectable inputs to Collect so the
// collector is fully unit-testable off-device.
type Options struct {
	Host        string                             // os.Hostname() in production
	CollectedAt string                             // RFC3339; empty => time.Now().UTC()
	Kernel      string                             // unix.Uname Release in production
	HomeRel     string                             // home dir relative to fsys root, e.g. "home/pi"
	Statfs      func(path string) (DiskStats, error)
	Vcgencmd    func() (present, throttled, underVolt bool)
	Sleep       func()                             // CPU%% inter-sample sleep; nil => 200ms
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run TestVitalsMarshals -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/vitals_types.go cmd/tailprobe/vitals_types_test.go
git commit -m "feat(tailprobe): scaffold cmd/tailprobe with schema:1 vitals types"
```

---

## Task 2: Pure `/proc` parsers

**Files:**
- Create: `cmd/tailprobe/parse.go`
- Test: `cmd/tailprobe/parse_test.go`

These functions operate on raw bytes so they need no filesystem. They port lines 9–27 of `fleet_collect.sh`.

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/parse_test.go
package main

import (
	"math"
	"testing"
)

func approx(a, b float64) bool { return math.Abs(a-b) < 0.05 }

func TestParseMemInfo(t *testing.T) {
	in := []byte("MemTotal:     429876 kB\nMemFree: 100000 kB\nMemAvailable:  214938 kB\n")
	total, avail := parseMemInfo(in)
	if total != 429876 || avail != 214938 {
		t.Fatalf("got total=%d avail=%d", total, avail)
	}
	if !approx(memPct(total, avail), 50.0) {
		t.Errorf("memPct=%v want ~50", memPct(total, avail))
	}
	if memPct(0, 0) != 0 {
		t.Errorf("memPct(0,0) must be 0, not NaN")
	}
}

func TestCPUSampleAndPercent(t *testing.T) {
	// fields: user nice system idle iowait irq softirq ...
	s1 := []byte("cpu  100 0 50 1000 0 0 0\ncpu0 ...\n")
	s2 := []byte("cpu  150 0 75 1100 0 0 0\n")
	t1, i1 := cpuSample(s1)
	t2, i2 := cpuSample(s2)
	if t1 != 1150 || i1 != 1000 {
		t.Fatalf("sample1 total=%d idle=%d", t1, i1)
	}
	// dt=200, didle=100 => busy fraction = 50%
	if !approx(cpuPercent(t1, i1, t2, i2), 50.0) {
		t.Errorf("cpuPercent=%v want ~50", cpuPercent(t1, i1, t2, i2))
	}
	if cpuPercent(10, 5, 10, 5) != 0 {
		t.Errorf("zero delta must be 0%%")
	}
}

func TestParseScalars(t *testing.T) {
	if v := parseLoadavg([]byte("0.34 0.22 0.18 1/200 1234")); !approx(v, 0.34) {
		t.Errorf("load=%v", v)
	}
	if v := parseUptime([]byte("90432.12 360000.00")); v != 90432 {
		t.Errorf("uptime=%d", v)
	}
	if s := parseSerial([]byte("foo\nSerial\t\t: 10000000abcd1234\nbar")); s != "10000000abcd1234" {
		t.Errorf("serial=%q", s)
	}
	if s := parseSerial([]byte("no serial here")); s != "" {
		t.Errorf("missing serial must be empty, got %q", s)
	}
	if s := parseOSRelease([]byte(`PRETTY_NAME="Debian GNU/Linux 13 (trixie)"` + "\nID=debian\n")); s != "Debian GNU/Linux 13 (trixie)" {
		t.Errorf("os=%q", s)
	}
	if s := parseModel([]byte("Raspberry Pi Zero 2 W\x00\x00")); s != "Raspberry Pi Zero 2 W" {
		t.Errorf("model=%q", s)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run 'TestParse|TestCPU' -v`
Expected: FAIL — `undefined: parseMemInfo` etc.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/parse.go
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

// cpuSample parses the aggregate "cpu " line of /proc/stat into total and idle
// jiffies. idle is the 4th numeric field (idle).
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run 'TestParse|TestCPU' -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/parse.go cmd/tailprobe/parse_test.go
git commit -m "feat(tailprobe): pure /proc parsers (mem, cpu, load, uptime, serial, os, model)"
```

---

## Task 3: `/sys` readers over `fs.FS`

**Files:**
- Create: `cmd/tailprobe/sysread.go`
- Test: `cmd/tailprobe/sysread_test.go`

Ports lines 37–64 of `fleet_collect.sh` (thermal, DRM displays, USB, battery), reading through an `fs.FS` so paths are relative (no leading `/`).

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/sysread_test.go
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
		"sys/bus/usb/devices/1-1/idVendor":  {Data: []byte("1234\n")},
		"sys/bus/usb/devices/usb1/idVendor": {Data: []byte("1d6b\n")},
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run 'TestRead|TestUSB' -v`
Expected: FAIL — `undefined: readThermal` etc.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/sysread.go
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run 'TestRead|TestUSB' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/sysread.go cmd/tailprobe/sysread_test.go
git commit -m "feat(tailprobe): /sys readers (thermal, DRM displays, USB count, battery)"
```

---

## Task 4: Injected host bits — disk, vcgencmd, kernel

**Files:**
- Create: `cmd/tailprobe/host.go` (untagged: `parseThrottled`, `realStatfs`, `realVcgencmd`)
- Create: `cmd/tailprobe/host_linux.go` + `cmd/tailprobe/host_other.go` (`realKernel`, build-tag split)
- Test: `cmd/tailprobe/host_test.go`

`unix.Statfs` and `vcgencmd` are the only non-`fs.FS` inputs. Real implementations live here; `Collect` receives them via `Options` so tests inject fakes.

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/host_test.go
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run TestVcgencmd -v`
Expected: FAIL — `undefined: parseThrottled`.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/host.go
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
	used := total - free
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
```

Also add the Linux-gated kernel reader and a non-Linux stub so the package builds and unit-tests on the macOS dev host (`realStatfs`/`realVcgencmd` stay in the untagged `host.go` — they compile on darwin; only `unix.Uname` needs gating):

```go
// cmd/tailprobe/host_linux.go
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
```

```go
// cmd/tailprobe/host_other.go
//go:build !linux

// Stub so the package builds/tests on non-Linux dev hosts; the probe only runs on the Linux SBCs.
package main

func realKernel() string { return "" }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run TestVcgencmd -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/host.go cmd/tailprobe/host_linux.go cmd/tailprobe/host_other.go cmd/tailprobe/host_test.go
git commit -m "feat(tailprobe): injected host bits (statfs/vcgencmd/kernel), kernel build-tag split"
```

---

## Task 5: App-health by hostname class

**Files:**
- Create: `cmd/tailprobe/apphealth.go`
- Test: `cmd/tailprobe/apphealth_test.go`

Ports lines 66–90 of `fleet_collect.sh`: classify by hostname, then match a regex against process command lines read from `proc/<pid>/cmdline` (the `pgrep -fi` port). **Contract: a match => `running=true`; no match => `running=nil` (JSON null, unknown), never `false`.**

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/apphealth_test.go
package main

import (
	"testing"
	"testing/fstest"
)

func procFS(cmdlines ...string) fstest.MapFS {
	m := fstest.MapFS{}
	for i, c := range cmdlines {
		// /proc/<pid>/cmdline is NUL-separated.
		m["proc/"+pid(i)+"/cmdline"] = &fstest.MapFile{Data: []byte(c)}
	}
	return m
}
func pid(i int) string { return []string{"101", "202", "303"}[i] }

func TestAppHealthClassesAndMatch(t *testing.T) {
	// clock host, a matching process running.
	a := appHealth("SuperClockFast", procFS("node\x00--import\x00tsx\x00server.ts"), "")
	if a.Name != "superclock" || a.Running == nil || !*a.Running {
		t.Fatalf("clock running: %+v", a)
	}
	// dashboard host, no matching process => running nil (unknown), NOT false.
	d := appHealth("plantdashboard", procFS("bash\x00-c\x00sleep"), "")
	if d.Name != "dashboard" || d.Running != nil {
		t.Fatalf("dashboard unknown: %+v (running must be nil)", d)
	}
	// unknown host class => empty name, running nil.
	u := appHealth("mac-studio", procFS("anything"), "")
	if u.Name != "" || u.Running != nil {
		t.Fatalf("unknown class: %+v", u)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run TestAppHealth -v`
Expected: FAIL — `undefined: appHealth`.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/apphealth.go
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run TestAppHealth -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/apphealth.go cmd/tailprobe/apphealth_test.go
git commit -m "feat(tailprobe): app-health by hostname class (/proc cmdline match)"
```

---

## Task 6: Compose `Collect()`

**Files:**
- Create: `cmd/tailprobe/collect.go`
- Test: `cmd/tailprobe/collect_test.go`

Assembles all readers into a `Vitals`, reading everything through `fsys` plus the injected `Options`. CPU% samples `/proc/stat` twice (`Options.Sleep` between).

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/collect_test.go
package main

import (
	"encoding/json"
	"testing"
	"testing/fstest"
)

func fixtureFS() fstest.MapFS {
	return fstest.MapFS{
		"proc/device-tree/model": {Data: []byte("Raspberry Pi Zero 2 W\x00")},
		"proc/cpuinfo":           {Data: []byte("processor\t: 0\nSerial\t\t: 10000000abcd\n")},
		"proc/meminfo":           {Data: []byte("MemTotal: 429876 kB\nMemAvailable: 214938 kB\n")},
		"proc/loadavg":           {Data: []byte("0.34 0.2 0.1 1/100 5\n")},
		"proc/uptime":            {Data: []byte("90432.0 1.0\n")},
		"proc/stat":              {Data: []byte("cpu  100 0 50 1000 0 0 0\n")},
		"etc/os-release":         {Data: []byte("PRETTY_NAME=\"Debian GNU/Linux 13 (trixie)\"\n")},
		"sys/class/thermal/thermal_zone0/temp":  {Data: []byte("54731\n")},
		"sys/class/drm/card0-HDMI-A-1/status":   {Data: []byte("connected\n")},
		"proc/101/cmdline":                      {Data: []byte("chromium\x00--kiosk")},
	}
}

func TestCollectProducesSchema1(t *testing.T) {
	opt := Options{
		Host:        "plantdashboard",
		CollectedAt: "2026-06-07T00:00:00Z",
		Kernel:      "6.12.0-rpi",
		Statfs:      func(string) (DiskStats, error) { return DiskStats{TotalGB: 29.0, UsedPct: 36.0, FreeGB: 18.6}, nil },
		Vcgencmd:    func() (bool, bool, bool) { return false, false, false },
		Sleep:       func() {},
	}
	v, err := Collect(fixtureFS(), opt)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}
	if v.Schema != 1 || v.Host != "plantdashboard" {
		t.Errorf("schema/host: %+v", v)
	}
	if v.Config.Model != "Raspberry Pi Zero 2 W" || v.Config.CPUCores < 1 || v.Config.Kernel != "6.12.0-rpi" {
		t.Errorf("config: %+v", v.Config)
	}
	if v.Thermal.SoCTempC == nil || *v.Thermal.SoCTempC < 54.7 {
		t.Errorf("thermal: %+v", v.Thermal)
	}
	if v.Health.DiskFreeGB != 18.6 || v.Health.UptimeS != 90432 {
		t.Errorf("health: %+v", v.Health)
	}
	if len(v.SideThings.Displays) != 1 {
		t.Errorf("displays: %+v", v.SideThings.Displays)
	}
	if v.App.Name != "dashboard" || v.App.Running == nil || !*v.App.Running {
		t.Errorf("app: %+v", v.App)
	}
	// Must round-trip as valid JSON with non-nil slices (never JSON null arrays).
	b, _ := json.Marshal(v)
	if !json.Valid(b) {
		t.Fatalf("invalid json")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run TestCollect -v`
Expected: FAIL — `undefined: Collect`.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/collect.go
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run TestCollect -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/collect.go cmd/tailprobe/collect_test.go
git commit -m "feat(tailprobe): compose Collect() over an injectable fs.FS root"
```

---

## Task 7: Prometheus `/metrics` rendering

**Files:**
- Create: `cmd/tailprobe/metrics.go`
- Test: `cmd/tailprobe/metrics_test.go`

The hybrid hook: emit the numeric vitals in Prometheus exposition format. Non-numeric fields (model, displays, app name) are not metrics. A `nil` `soc_temp_c` is **omitted** (no sample), not `NaN`.

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/metrics_test.go
package main

import (
	"strings"
	"testing"
)

func TestWritePrometheus(t *testing.T) {
	temp := 54.7
	running := true
	v := Vitals{
		Host:    "plantdashboard",
		Config:  Config{CPUCores: 4},
		Thermal: Thermal{SoCTempC: &temp, ThrottledNow: true},
		Health:  Health{CPUPct: 17.4, MemPct: 38.0, DiskFreeGB: 18.6, UptimeS: 90432},
		App:     App{Name: "dashboard", Running: &running},
	}
	var sb strings.Builder
	WritePrometheus(&sb, v)
	out := sb.String()

	wantLines := []string{
		`# TYPE tailprobe_cpu_percent gauge`,
		`tailprobe_cpu_percent{host="plantdashboard"} 17.4`,
		`tailprobe_soc_temp_celsius{host="plantdashboard"} 54.7`,
		`tailprobe_throttled{host="plantdashboard"} 1`,
		`tailprobe_uptime_seconds{host="plantdashboard"} 90432`,
		`tailprobe_app_running{host="plantdashboard",app="dashboard"} 1`,
	}
	for _, w := range wantLines {
		if !strings.Contains(out, w) {
			t.Errorf("missing line:\n  %s\nin:\n%s", w, out)
		}
	}

	// nil temp must be omitted entirely (no NaN, no zero).
	v.Thermal.SoCTempC = nil
	sb.Reset()
	WritePrometheus(&sb, v)
	if strings.Contains(sb.String(), "tailprobe_soc_temp_celsius") {
		t.Errorf("nil temp must be omitted, got:\n%s", sb.String())
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run TestWritePrometheus -v`
Expected: FAIL — `undefined: WritePrometheus`.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/metrics.go
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run TestWritePrometheus -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/metrics.go cmd/tailprobe/metrics_test.go
git commit -m "feat(tailprobe): Prometheus /metrics exposition (nullable temp omitted)"
```

---

## Task 8: HTTP server

**Files:**
- Create: `cmd/tailprobe/server.go`
- Test: `cmd/tailprobe/server_test.go`

A mux with `/healthz`, `/vitals` (JSON), `/metrics` (Prometheus). The collector is a `func() (Vitals, error)` so handlers are testable without touching the host.

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/server_test.go
package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func testMux() http.Handler {
	temp := 50.0
	return newMux(func() (Vitals, error) {
		return Vitals{Schema: 1, Host: "h", Thermal: Thermal{SoCTempC: &temp},
			SideThings: SideThings{Displays: []Display{}, USB: []string{}}}, nil
	})
}

func TestServerRoutes(t *testing.T) {
	mux := testMux()

	r := httptest.NewRecorder()
	mux.ServeHTTP(r, httptest.NewRequest("GET", "/healthz", nil))
	if r.Code != 200 || !strings.Contains(r.Body.String(), "ok") {
		t.Errorf("healthz: %d %q", r.Code, r.Body.String())
	}

	r = httptest.NewRecorder()
	mux.ServeHTTP(r, httptest.NewRequest("GET", "/vitals", nil))
	if r.Code != 200 || r.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("vitals: %d ct=%q", r.Code, r.Header().Get("Content-Type"))
	}
	var v Vitals
	if err := json.Unmarshal(r.Body.Bytes(), &v); err != nil || v.Schema != 1 {
		t.Errorf("vitals body: %v %s", err, r.Body.String())
	}

	r = httptest.NewRecorder()
	mux.ServeHTTP(r, httptest.NewRequest("GET", "/metrics", nil))
	if r.Code != 200 || !strings.Contains(r.Body.String(), "tailprobe_soc_temp_celsius") {
		t.Errorf("metrics: %d %q", r.Code, r.Body.String())
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run TestServerRoutes -v`
Expected: FAIL — `undefined: newMux`.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/server.go
package main

import (
	"encoding/json"
	"net/http"
)

// newMux builds the probe's HTTP routes. collect is called per request.
func newMux(collect func() (Vitals, error)) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		_, _ = w.Write([]byte("ok\n"))
	})

	mux.HandleFunc("/vitals", func(w http.ResponseWriter, r *http.Request) {
		v, err := collect()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		enc := json.NewEncoder(w)
		enc.SetEscapeHTML(false)
		_ = enc.Encode(v)
	})

	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		v, err := collect()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		WritePrometheus(w, v)
	})

	return mux
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -run TestServerRoutes -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/server.go cmd/tailprobe/server_test.go
git commit -m "feat(tailprobe): HTTP mux for /healthz, /vitals, /metrics"
```

---

## Task 9: Address resolution, retry-listen, and `main`

**Files:**
- Create: `cmd/tailprobe/main.go`
- Test: `cmd/tailprobe/main_test.go`

`main` resolves the bind address from `--addr` (the installer supplies `100.x:9100`) or, if empty, auto-detects the device's `100.64.0.0/10` address from interface addrs (dependency-free fallback). Because `100.x` isn't bindable until `tailscaled` assigns it at boot, listening **retries** rather than exits.

- [ ] **Step 1: Write the failing test**

```go
// cmd/tailprobe/main_test.go
package main

import (
	"errors"
	"net"
	"testing"
)

func TestPickTailscaleAddr(t *testing.T) {
	addrs := []net.Addr{
		&net.IPNet{IP: net.ParseIP("192.168.4.40")},
		&net.IPNet{IP: net.ParseIP("100.78.29.28")}, // CGNAT range
		&net.IPNet{IP: net.ParseIP("100.64.0.0")},
	}
	got, err := pickTailscaleAddr(addrs)
	if err != nil || got != "100.78.29.28" {
		t.Fatalf("got %q err=%v want 100.78.29.28", got, err)
	}
	if _, err := pickTailscaleAddr([]net.Addr{&net.IPNet{IP: net.ParseIP("10.0.0.1")}}); err == nil {
		t.Errorf("no 100.x => error")
	}
}

func TestListenWithRetry(t *testing.T) {
	calls := 0
	listen := func(addr string) (net.Listener, error) {
		calls++
		if calls < 3 {
			return nil, errors.New("cannot assign requested address")
		}
		return net.Listen("tcp", "127.0.0.1:0") // success on the 3rd try
	}
	ln, err := listenWithRetry("100.78.29.28:9100", 5, func() {}, listen)
	if err != nil || ln == nil || calls != 3 {
		t.Fatalf("calls=%d err=%v ln=%v (want 3 calls + non-nil listener)", calls, err, ln)
	}
	_ = ln.Close()
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tool/go test ./cmd/tailprobe/ -run 'TestPickTailscale|TestListenWithRetry' -v`
Expected: FAIL — `undefined: pickTailscaleAddr`.

- [ ] **Step 3: Write minimal implementation**

```go
// cmd/tailprobe/main.go
package main

import (
	"errors"
	"flag"
	"log"
	"net"
	"net/http"
	"os"
	"time"
)

// cgnat is Tailscale's 100.64.0.0/10 range.
var cgnat = func() *net.IPNet { _, n, _ := net.ParseCIDR("100.64.0.0/10"); return n }()

// pickTailscaleAddr returns the first IPv4 address inside 100.64.0.0/10.
func pickTailscaleAddr(addrs []net.Addr) (string, error) {
	for _, a := range addrs {
		var ip net.IP
		switch v := a.(type) {
		case *net.IPNet:
			ip = v.IP
		case *net.IPAddr:
			ip = v.IP
		}
		if ip4 := ip.To4(); ip4 != nil && cgnat.Contains(ip4) {
			return ip4.String(), nil
		}
	}
	return "", errors.New("no 100.64.0.0/10 (Tailscale) address found")
}

func resolveBindAddr(explicit string) (string, error) {
	if explicit != "" {
		return explicit, nil
	}
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return "", err
	}
	ip, err := pickTailscaleAddr(addrs)
	if err != nil {
		return "", err
	}
	return net.JoinHostPort(ip, "9100"), nil
}

// listenWithRetry retries listen until it succeeds or attempts is exhausted,
// returning the bound listener. At boot, binding the 100.x fails until
// tailscaled assigns it.
func listenWithRetry(addr string, attempts int, sleep func(), listen func(string) (net.Listener, error)) (net.Listener, error) {
	var last error
	for i := 0; i < attempts; i++ {
		ln, err := listen(addr)
		if err == nil {
			return ln, nil
		}
		last = err
		sleep()
	}
	return nil, last
}

func main() {
	addrFlag := flag.String("addr", "", "explicit bind address host:port (default: auto-detect 100.x:9100)")
	flag.Parse()

	addr, err := resolveBindAddr(*addrFlag)
	if err != nil {
		log.Fatalf("tailprobe: resolve bind addr: %v", err)
	}

	host, _ := os.Hostname()
	collect := func() (Vitals, error) {
		return Collect(os.DirFS("/"), Options{
			Host:     host,
			Kernel:   realKernel(),
			HomeRel:  "", // last_render disabled in Phase 0 unless configured
			Statfs:   realStatfs,
			Vcgencmd: realVcgencmd,
		})
	}
	srv := &http.Server{Handler: newMux(collect), ReadHeaderTimeout: 5 * time.Second}

	// Retry until tailscaled has assigned the address, then serve.
	ln, err := listenWithRetry(addr, 60, func() { time.Sleep(2 * time.Second) },
		func(a string) (net.Listener, error) { return net.Listen("tcp", a) })
	if err != nil {
		log.Fatalf("tailprobe: could not bind %s: %v", addr, err)
	}
	log.Printf("tailprobe: serving on %s", addr)
	log.Fatal(srv.Serve(ln))
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tool/go test ./cmd/tailprobe/ -v`
Expected: PASS (all tests in the package).

- [ ] **Step 5: Commit**

```bash
git add cmd/tailprobe/main.go cmd/tailprobe/main_test.go
git commit -m "feat(tailprobe): main with --addr, 100.x auto-detect, retry-listen"
```

---

## Task 10: Cross-compile and on-device verification

**Files:**
- Create: `cmd/tailprobe/README.md`

This task produces the deployable artifact and verifies it against the real script's output on one Pi. (No unit test — this is build + manual acceptance. Plan 3, the installer, automates the push to all 8 hosts.)

- [ ] **Step 1: Build the static arm64 binary**

Run:
```bash
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 ./tool/go build -trimpath -ldflags='-s -w' -o dist/tailprobe-linux-arm64 ./cmd/tailprobe
file dist/tailprobe-linux-arm64
```
Expected: `dist/tailprobe-linux-arm64: ELF 64-bit LSB executable, ARM aarch64, ... statically linked`.

- [ ] **Step 2: Copy to one Pi and run it (manual, against `plantdashboard`)**

Run (from the Mac Studio; mirrors tailtop's OpenSSH path, `nickv2026` per the infra doc):
```bash
ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=accept-new nickv2026@plantdashboard \
  'cat > /tmp/tailprobe && chmod +x /tmp/tailprobe' < dist/tailprobe-linux-arm64
# Run bound to the device's Tailscale IP (from §12 table): 100.64.79.16
ssh -i ~/.ssh/id_ed25519 nickv2026@plantdashboard '/tmp/tailprobe --addr 100.64.79.16:9100 &>/tmp/tailprobe.log & sleep 2; cat /tmp/tailprobe.log'
```
Expected: log line `tailprobe: serving on 100.64.79.16:9100`.

- [ ] **Step 3: Verify `/vitals` matches the shell script's shape**

Run (from the Mac Studio, over Tailscale):
```bash
curl -fsS --max-time 5 http://100.64.79.16:9100/healthz
curl -fsS --max-time 5 http://100.64.79.16:9100/vitals | python3 -m json.tool
curl -fsS --max-time 5 http://100.64.79.16:9100/metrics | head
```
Expected: `/healthz` → `ok`; `/vitals` → a `schema:1` object whose keys match `tailtop/tests/fixtures/vitals_orangepi.json` (config/thermal/health/side_things/app); `/metrics` → `tailprobe_*` gauge lines. Spot-check that `thermal.soc_temp_c` is a number and `app.name` is `dashboard`.

- [ ] **Step 4: Confirm the probe's JSON deserializes through tailtop's parser**

Run:
```bash
cd tailtop
curl -fsS http://100.64.79.16:9100/vitals > /tmp/probe_vitals.json
uv run python -c "import json; from tailtop.data.vitals import Vitals; v=Vitals.from_collect_json(json.load(open('/tmp/probe_vitals.json'))); print('parsed OK:', v.host, v.soc_temp_c, v.health_level)"
cd ..
```
Expected: `parsed OK: plantdashboard <temp> <level>` — proving the probe is drop-in compatible with the existing consumer (the acceptance criterion for Plan 4, tailtop repoint).

- [ ] **Step 5: Write the README and commit**

Create `cmd/tailprobe/README.md`:
```markdown
# tailprobe

A single static Go binary that serves one device's vitals over a Tailscale-only
HTTP endpoint, reproducing the `schema:1` JSON of `tailtop/agent/fleet_collect.sh`.

## Endpoints
- `GET /healthz` — liveness (`ok`).
- `GET /vitals` — the full `schema:1` JSON (consumed by `tailhub` and `tailtop`).
- `GET /metrics` — Prometheus exposition of the numeric vitals.

## Build
    CGO_ENABLED=0 GOOS=linux GOARCH=arm64 ./tool/go build -trimpath -ldflags='-s -w' \
      -o dist/tailprobe-linux-arm64 ./cmd/tailprobe

One arm64 build covers the whole Phase-0 fleet (4 clocks, 3 dashboards, the Orange Pi).

## Run
    tailprobe --addr 100.x.y.z:9100      # bind the device's Tailscale IP only

With `--addr` omitted, the probe auto-detects its `100.64.0.0/10` address. Binding
retries until `tailscaled` has assigned the address at boot. The probe is
read-only and never executes caller-supplied commands.
```

Run:
```bash
git add cmd/tailprobe/README.md
git commit -m "docs(tailprobe): usage + build/run; verified on plantdashboard"
```

---

## Self-Review

**Spec coverage (against design §6.1 + §12 probe rows):**
- Vitals port of `fleet_collect.sh` → Tasks 2–6 (every signal: model, serial, cores, mem, os, kernel, load, cpu%, disk, uptime, thermal+throttle, displays, usb, battery, app-health). ✅
- `/metrics` Prometheus exposition → Task 7. ✅
- `/vitals` rich JSON (schema:1) + `/healthz` → Tasks 1, 8. ✅
- Tailscale-only bind, never `0.0.0.0`, with boot retry → Task 9 (`--addr` + 100.x auto-detect + retry-listen). ✅
- `vcgencmd` Broadcom-only, Allwinner stays `false` (no false-critical) → Task 4. ✅
- `app.running = null` (unknown, never false) contract → Task 5 (+ asserted in Task 6). ✅
- Single arm64 build via `./tool/go` → Task 10. ✅
- Acceptance = deserializes through `tailtop`'s `Vitals.from_collect_json` → Task 10 Step 4. ✅
- *Deferred to later plans (correctly out of scope):* hub scrape/store/API (Plan 2), installer + systemd unit + ACL (Plan 3), tailtop data-source swap (Plan 4), rolling CPU sampler optimization, `client/local` authoritative bind + `WhoIs` (Phase-0 uses the simpler `--addr`/interface-scan; noted in design §6.1 as the alternative).

**Placeholder scan:** No TBD/TODO; every code step contains complete, runnable code; every test step has real assertions and an exact command + expected result. ✅

**Type consistency:** `Vitals`/`Config`/`Thermal`/`Health`/`SideThings`/`Display`/`Battery`/`App`/`DiskStats`/`Options` are defined once (Task 1) and used consistently. Function names are stable across tasks: `parseMemInfo`, `memPct`, `cpuSample`, `cpuPercent`, `parseLoadavg`, `parseUptime`, `parseSerial`, `parseOSRelease`, `parseModel` (Task 2); `readThermal`, `readDisplays`, `usbCount`, `readBattery` (Task 3); `realStatfs`, `parseThrottled`, `realVcgencmd`, `realKernel` (Task 4); `classForHost`, `anyProcessMatches`, `appHealth` (Task 5); `Collect` (Task 6); `WritePrometheus` (Task 7); `newMux` (Task 8); `pickTailscaleAddr`, `resolveBindAddr`, `listenWithRetry`, `main` (Task 9). `Collect`'s signature `(fs.FS, Options)` matches its callers in Tasks 8/9. ✅

---

## Phase 0 remaining plans (written next, in order)

2. **`tailhub` core** — async scrape scheduler + SQLite (WAL, 4 tables) + `/fleet`, `/device/{host}`, `/history`; reuse `lifelog` store idioms + `TailscaleOnlineCollector`. Consumes this probe's `/vitals`.
3. **Installer** — OpenSSH push of `tailprobe-linux-arm64` + a system systemd unit (`--addr <100.x>`, `After=tailscaled`, `DynamicUser`) to the 8 SBCs + ACL stanza + verify.
4. **tailtop repoint** — `TailscaleClient.fetch_fleet(hub_url)` + `vitals_poller` hub GET + `--hub-url`/`TAILTOP_HUB_URL`, keeping the OpenSSH path as fallback.
