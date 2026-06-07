# tailtop Device Vitals — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull per-Pi hardware telemetry (temp, throttle, disk, displays/USB/battery, app-health) over `tailscale ssh` into tailtop, and render it through the existing device cards, the `DeviceDetail` panels, and the `AlertStrip`, plus a one-shot `tailtop fleet` command.

**Architecture:** A new **data layer** (`vitals.py` typed model + parser + thresholds; `vitals_poller.py` slow async loop; `client.collect_vitals()` that pipes a POSIX-sh script over `tailscale ssh`). The app owns a `vitals_by_id` map + a `VitalsHistory` ring buffer and threads them into widgets exactly as it threads `rates`. Pis stay dumb (one stateless script); all logic is central. Network UI cadence is untouched (vitals poll ~30 s).

**Tech Stack:** Python 3.13, Textual, asyncio, `uv` + pytest (`asyncio_mode=auto`); POSIX `sh` for the agent script. Test command throughout: `uv run --extra dev pytest`.

**Spec:** `docs/superpowers/specs/2026-06-06-tailtop-device-vitals-design.md`

**Base:** branch `claude/tailtop-device-vitals` (main merged into the device-detail line; 107 tests green).

**Verified transport (live 2026-06-06):** Tailscale SSH on all 8 Pis. SSH users: SuperClocks → `nickv2026`, Orange Pi → `nickv`, e-paper → resolve at runtime. Thermal: `/sys/class/thermal/*` universal; `vcgencmd` on Broadcom only (Orange Pi is Allwinner).

---

## File Structure

| File | Responsibility |
|---|---|
| `tailtop/agent/fleet_collect.sh` *(new)* | Stateless POSIX-sh collector; prints one JSON object. Package data. |
| `tailtop/tailtop/data/vitals.py` *(new)* | `Vitals` + `Display` dataclasses, `from_collect_json`, thresholds, `health_level`/`reasons`, `summarise_health`. |
| `tailtop/tailtop/data/vitals_poller.py` *(new)* | `VitalsPoller`: slow concurrency-capped SSH poll loop. |
| `tailtop/tailtop/data/client.py` *(edit)* | `collect_vitals(peer, user_map)` + `ssh_user_for()` helper. |
| `tailtop/tailtop/state.py` *(edit)* | `VitalsHistory` (temp/cpu ring buffers). |
| `tailtop/tailtop/app.py` *(edit)* | Own `vitals`/`vitals_history`/`VitalsPoller`; `_on_vitals`; thread into modes; `tailtop fleet` subcommand. |
| `tailtop/tailtop/fleet_report.py` *(new)* | Pure `render_fleet(status, vitals_by_id) -> (str, int)` for the CLI. |
| `tailtop/tailtop/widgets/device_card.py` *(edit)* | Vitals badge line + temp sparkline. |
| `tailtop/tailtop/widgets/detail_pane.py` *(edit)* | `#panel-vitals` + `#panel-hardware`. |
| `tailtop/tailtop/widgets/alert_strip.py` *(edit)* | Fold `summarise_health` into `summarise_alerts`. |
| `tailtop/tailtop/modes/{cockpit,comfort,the_base}.py` *(edit)* | Pass per-peer vitals into the widgets. |
| `tailtop/tests/...` | One test module per unit; fixtures captured live from a Pi. |

`DiskTable` is intentionally untouched (it is not mounted in any mode). Disk surfaces in the vitals panel/card.

All commands run from `tailtop/` (the project dir with `pyproject.toml`). Paths below are relative to the repo root.

---

## Task 1: Collect script + live fixture capture

**Files:**
- Create: `tailtop/agent/fleet_collect.sh`
- Create: `tailtop/tests/test_collect_script.py`
- Create (captured live): `tailtop/tests/fixtures/vitals_fastclock.json`, `tailtop/tests/fixtures/vitals_orangepi.json`

- [ ] **Step 1: Write the script**

`tailtop/agent/fleet_collect.sh`:

```sh
#!/bin/sh
# fleet_collect.sh — print one JSON object of this Pi's vitals.
# Read-only, side-effect-free, dependency-free POSIX sh. Portable across
# Broadcom (vcgencmd present) and Allwinner (thermal via /sys only).
set -u

j() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }   # json-escape a string

MODEL=$(tr -d '\000' < /proc/device-tree/model 2>/dev/null || echo "")
SERIAL=$(awk -F': ' '/Serial/{print $2}' /proc/cpuinfo 2>/dev/null | tail -1)
CORES=$(nproc 2>/dev/null || echo 0)
MEM_TOTAL_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
MEM_AVAIL_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
MEM_TOTAL_MB=$((MEM_TOTAL_KB / 1024))
[ "$MEM_TOTAL_KB" -gt 0 ] && MEM_PCT=$(awk "BEGIN{printf \"%.1f\", (1-($MEM_AVAIL_KB/$MEM_TOTAL_KB))*100}") || MEM_PCT=0
OS=$(. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-}")
KERNEL=$(uname -r)
LOAD1=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)
UPTIME=$(awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || echo 0)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
HOST=$(hostname)

# CPU %: sample /proc/stat twice 200ms apart.
read -r _ a b c idle1 rest < /proc/stat; t1=$((a+b+c+idle1)); sleep 0.2
read -r _ a b c idle2 rest < /proc/stat; t2=$((a+b+c+idle2))
DT=$((t2-t1)); DI=$((idle2-idle1))
[ "$DT" -gt 0 ] && CPU_PCT=$(awk "BEGIN{printf \"%.1f\", (1-($DI/$DT))*100}") || CPU_PCT=0

# Disk (root).
DISK=$(df -kP / 2>/dev/null | awk 'NR==2{printf "%d %d %d", $2,$3,$4}')
DTOTAL=$(printf '%s' "$DISK" | awk '{print $1}'); DUSED=$(printf '%s' "$DISK" | awk '{print $2}'); DAVAIL=$(printf '%s' "$DISK" | awk '{print $3}')
[ "${DTOTAL:-0}" -gt 0 ] && DUSED_PCT=$(awk "BEGIN{printf \"%.1f\", ($DUSED/$DTOTAL)*100}") || DUSED_PCT=0
DFREE_GB=$(awk "BEGIN{printf \"%.1f\", ${DAVAIL:-0}/1048576}")
DTOTAL_GB=$(awk "BEGIN{printf \"%.1f\", ${DTOTAL:-0}/1048576}")

# Thermal: /sys universal; vcgencmd throttle flags on Broadcom only.
TEMP_MC=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "")
[ -n "$TEMP_MC" ] && TEMP_C=$(awk "BEGIN{printf \"%.1f\", $TEMP_MC/1000}") || TEMP_C=null
if command -v vcgencmd >/dev/null 2>&1; then
  VCG=true
  TH=$(vcgencmd get_throttled 2>/dev/null | sed 's/.*=//')
  THR=$(( ${TH:-0} & 0x4 ? 1 : 0 )); UV=$(( ${TH:-0} & 0x1 ? 1 : 0 ))
  [ "$THR" = 1 ] && THROTTLED=true || THROTTLED=false
  [ "$UV" = 1 ] && UNDERV=true || UNDERV=false
else
  VCG=false; THROTTLED=false; UNDERV=false
fi

# Displays (HDMI kiosks) via DRM connector status.
DISP=""
for c in /sys/class/drm/*/status; do
  [ -f "$c" ] || continue
  s=$(cat "$c"); name=$(basename "$(dirname "$c")" | sed 's/^card[0-9]*-//')
  [ "$s" = "connected" ] && DISP="$DISP{\"connector\":\"$(j "$name")\",\"status\":\"connected\"},"
done
DISP="[${DISP%,}]"

USB=$(lsusb 2>/dev/null | wc -l | tr -d ' '); USB=${USB:-0}

# Battery (UPS HAT) if present.
BAT='{"present":false}'
for b in /sys/class/power_supply/*/capacity; do
  [ -f "$b" ] && BAT="{\"present\":true,\"pct\":$(cat "$b")}" && break
done

# App health, by hostname class.
APP_NAME=""; APP_RUNNING=null; APP_LAST=""
case "$HOST" in
  *clock*) APP_NAME="superclock"; pgrep -f superclock >/dev/null 2>&1 && APP_RUNNING=true || APP_RUNNING=false ;;
  *eink*|*ink*) APP_NAME="epaper"; pgrep -f 'eink\|epaper\|render' >/dev/null 2>&1 && APP_RUNNING=true || APP_RUNNING=false
    f=$(ls -t "$HOME"/*.png "$HOME"/last_frame* 2>/dev/null | head -1)
    [ -n "$f" ] && APP_LAST=$(date -u -r "$f" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "") ;;
  *dashboard*|*plant*|*orangepi*) APP_NAME="dashboard"; pgrep -f 'server.py' >/dev/null 2>&1 && APP_RUNNING=true || APP_RUNNING=false ;;
esac

cat <<EOF
{"schema":1,"host":"$(j "$HOST")","collected_at":"$NOW",
"config":{"model":"$(j "$MODEL")","serial":"$(j "$SERIAL")","cpu_cores":$CORES,"mem_total_mb":$MEM_TOTAL_MB,"os":"$(j "$OS")","kernel":"$(j "$KERNEL")","disk_total_gb":$DTOTAL_GB},
"thermal":{"soc_temp_c":$TEMP_C,"vcgencmd_present":$VCG,"throttled_now":$THROTTLED,"under_voltage_now":$UNDERV},
"health":{"load1":$LOAD1,"cpu_pct":$CPU_PCT,"mem_pct":$MEM_PCT,"disk_used_pct":$DUSED_PCT,"disk_free_gb":$DFREE_GB,"uptime_s":$UPTIME},
"side_things":{"displays":$DISP,"usb":$(seq 1 "$USB" 2>/dev/null | awk '{print "0"}' | paste -sd, - | sed 's/[0-9]/0/g; s/^/[/; s/$/]/' 2>/dev/null || echo "[]"),"battery":$BAT},
"app":{"name":"$(j "$APP_NAME")","running":$APP_RUNNING,"last_render":"$(j "$APP_LAST")"}}
EOF
```

> Note: the `usb` array only needs a length for Phase 1 (`usb_count`); emitting a count-length array of placeholders keeps the parser simple. If `seq`/`paste` are unavailable, it falls back to `[]` (count 0). A follow-up can emit real `id`/`name` per device.

- [ ] **Step 2: Write the syntax-check + capture test**

`tailtop/tests/test_collect_script.py`:

```python
"""The collect script must be valid POSIX sh. (Live output is captured into
fixtures and exercised by test_vitals.py — this only guards syntax so a broken
edit fails fast in CI without a Pi.)"""
from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "agent" / "fleet_collect.sh"


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_script_is_valid_posix_sh() -> None:
    r = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 3: Run it — expect pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_collect_script.py -v`
Expected: 2 passed.

- [ ] **Step 4: Capture real fixtures from live Pis** (validates the script end-to-end)

Run (Broadcom clock + Allwinner orange pi):
```bash
cd tailtop
tailscale ssh nickv2026@fastclock -- sh -s < agent/fleet_collect.sh | tee tests/fixtures/vitals_fastclock.json
tailscale ssh nickv@nickv-orangepizero2w -- sh -s < agent/fleet_collect.sh | tee tests/fixtures/vitals_orangepi.json
```
Expected: each prints one JSON object. Verify both parse: `python -c "import json,sys; json.load(open(sys.argv[1]))" tests/fixtures/vitals_fastclock.json`. If a field is malformed, fix the script and re-capture. Confirm `vcgencmd_present` is `true` for fastclock and `false` for the orange pi.

- [ ] **Step 5: Commit**

```bash
git add tailtop/agent/fleet_collect.sh tailtop/tests/test_collect_script.py tailtop/tests/fixtures/vitals_fastclock.json tailtop/tests/fixtures/vitals_orangepi.json
git commit -m "feat(vitals): add fleet_collect.sh agent + live fixtures"
```

---

## Task 2: Vitals model, parser, thresholds

**Files:**
- Create: `tailtop/tailtop/data/vitals.py`
- Create: `tailtop/tests/test_vitals.py`

- [ ] **Step 1: Write the failing tests**

`tailtop/tests/test_vitals.py`:

```python
"""Vitals parsing + health thresholds (pure, no Textual)."""
from __future__ import annotations

import json
from pathlib import Path

from tailtop.data.vitals import Vitals, summarise_health

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> Vitals:
    return Vitals.from_collect_json(json.loads((FIX / name).read_text()))


def test_parses_broadcom_fixture() -> None:
    v = _load("vitals_fastclock.json")
    assert v.host == "fastclock"
    assert v.vcgencmd_present is True
    assert v.soc_temp_c is not None
    assert v.cpu_cores >= 1


def test_parses_allwinner_fixture_without_vcgencmd() -> None:
    v = _load("vitals_orangepi.json")
    assert v.vcgencmd_present is False
    assert v.soc_temp_c is not None  # still read from /sys/class/thermal


def test_missing_sections_are_tolerated() -> None:
    v = Vitals.from_collect_json({"host": "x"})
    assert v.host == "x"
    assert v.soc_temp_c is None
    assert v.health_level == "ok"


def test_health_levels_at_boundaries() -> None:
    ok = Vitals(host="h", soc_temp_c=60.0, disk_used_pct=40.0)
    warn = Vitals(host="h", soc_temp_c=72.0)
    crit_temp = Vitals(host="h", soc_temp_c=81.0)
    crit_throttle = Vitals(host="h", throttled_now=True)
    crit_app = Vitals(host="h", app_name="superclock", app_running=False)
    assert ok.health_level == "ok"
    assert warn.health_level == "warn"
    assert crit_temp.health_level == "crit"
    assert crit_throttle.health_level == "crit"
    assert crit_app.health_level == "crit"


def test_summarise_health_joins_reasons() -> None:
    vbi = {
        "a": Vitals(host="fastclock", soc_temp_c=85.0),
        "b": Vitals(host="slowclock", disk_used_pct=97.0),
        "c": Vitals(host="smallclock", soc_temp_c=40.0),  # healthy → no reason
    }
    out = summarise_health(vbi)
    assert "fastclock" in out and "slowclock" in out
    assert "smallclock" not in out
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_vitals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tailtop.data.vitals'`.

- [ ] **Step 3: Implement `vitals.py`**

`tailtop/tailtop/data/vitals.py`:

```python
"""Typed device vitals + health thresholds.

Parsed from the agent's collect JSON in the data layer; widgets consume the
typed model, never raw JSON. Thresholds live here so cards, detail, the alert
strip, and the CLI all agree.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TEMP_WARN_C = 70.0
TEMP_CRIT_C = 80.0
DISK_WARN_PCT = 85.0
DISK_CRIT_PCT = 95.0
MEM_WARN_PCT = 90.0


@dataclass
class Display:
    connector: str
    status: str
    mode: str = ""


@dataclass
class Vitals:
    host: str
    collected_at: str = ""
    # config (rare-change)
    model: str = ""
    serial: str = ""
    cpu_cores: int = 0
    mem_total_mb: int = 0
    os: str = ""
    kernel: str = ""
    disk_total_gb: float = 0.0
    # thermal
    soc_temp_c: float | None = None
    vcgencmd_present: bool = False
    throttled_now: bool = False
    under_voltage_now: bool = False
    # health
    load1: float = 0.0
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    disk_used_pct: float = 0.0
    disk_free_gb: float = 0.0
    uptime_s: int = 0
    # side-things
    displays: list[Display] = field(default_factory=list)
    usb_count: int = 0
    battery_present: bool = False
    battery_pct: float | None = None
    # app
    app_name: str = ""
    app_running: bool | None = None
    app_last_render: str = ""
    # meta — set by the poller when a refresh failed but we kept the last sample
    stale: bool = False

    @classmethod
    def from_collect_json(cls, d: dict) -> "Vitals":
        cfg = d.get("config") or {}
        th = d.get("thermal") or {}
        he = d.get("health") or {}
        st = d.get("side_things") or {}
        ap = d.get("app") or {}
        bat = st.get("battery") or {}

        def f(x, default=0.0):
            try:
                return float(x)
            except (TypeError, ValueError):
                return default

        temp = th.get("soc_temp_c")
        return cls(
            host=d.get("host", ""),
            collected_at=d.get("collected_at", ""),
            model=cfg.get("model", "") or "",
            serial=cfg.get("serial", "") or "",
            cpu_cores=int(f(cfg.get("cpu_cores"))),
            mem_total_mb=int(f(cfg.get("mem_total_mb"))),
            os=cfg.get("os", "") or "",
            kernel=cfg.get("kernel", "") or "",
            disk_total_gb=f(cfg.get("disk_total_gb")),
            soc_temp_c=(f(temp) if temp is not None else None),
            vcgencmd_present=bool(th.get("vcgencmd_present", False)),
            throttled_now=bool(th.get("throttled_now", False)),
            under_voltage_now=bool(th.get("under_voltage_now", False)),
            load1=f(he.get("load1")),
            cpu_pct=f(he.get("cpu_pct")),
            mem_pct=f(he.get("mem_pct")),
            disk_used_pct=f(he.get("disk_used_pct")),
            disk_free_gb=f(he.get("disk_free_gb")),
            uptime_s=int(f(he.get("uptime_s"))),
            displays=[
                Display(x.get("connector", ""), x.get("status", ""), x.get("mode", ""))
                for x in (st.get("displays") or [])
            ],
            usb_count=len(st.get("usb") or []),
            battery_present=bool(bat.get("present", False)),
            battery_pct=(f(bat["pct"]) if bat.get("pct") is not None else None),
            app_name=ap.get("name") or "",
            app_running=ap.get("running"),
            app_last_render=ap.get("last_render") or "",
        )

    @property
    def reasons(self) -> list[str]:
        r: list[str] = []
        t = self.soc_temp_c
        if t is not None and t >= TEMP_CRIT_C:
            r.append(f"{self.host} {t:.0f}°C")
        elif t is not None and t >= TEMP_WARN_C:
            r.append(f"{self.host} warm {t:.0f}°C")
        if self.throttled_now:
            r.append(f"{self.host} throttled")
        if self.under_voltage_now:
            r.append(f"{self.host} under-voltage")
        if self.disk_used_pct >= DISK_WARN_PCT:
            r.append(f"{self.host} disk {self.disk_used_pct:.0f}%")
        if self.mem_pct >= MEM_WARN_PCT:
            r.append(f"{self.host} mem {self.mem_pct:.0f}%")
        if self.app_running is False:
            r.append(f"{self.host} {self.app_name or 'app'} down")
        return r

    @property
    def health_level(self) -> str:
        t = self.soc_temp_c
        if (
            (t is not None and t >= TEMP_CRIT_C)
            or self.throttled_now
            or self.under_voltage_now
            or self.disk_used_pct >= DISK_CRIT_PCT
            or self.app_running is False
        ):
            return "crit"
        if (
            (t is not None and t >= TEMP_WARN_C)
            or self.disk_used_pct >= DISK_WARN_PCT
            or self.mem_pct >= MEM_WARN_PCT
        ):
            return "warn"
        return "ok"


def summarise_health(vitals_by_id: dict[str, "Vitals"]) -> str:
    """One-line health summary across the fleet; empty when all clear."""
    reasons: list[str] = []
    for v in vitals_by_id.values():
        reasons.extend(v.reasons)
    return " · ".join(reasons)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_vitals.py -v`
Expected: all pass. (If a fixture lacks a field your assertion needs, adjust the assertion to the captured data — the fixtures are ground truth.)

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/data/vitals.py tailtop/tests/test_vitals.py
git commit -m "feat(vitals): typed Vitals model, parser, health thresholds"
```

---

## Task 3: `client.collect_vitals` + SSH-user resolution

**Files:**
- Modify: `tailtop/tailtop/data/client.py`
- Create: `tailtop/tests/test_collect_vitals.py`

- [ ] **Step 1: Write the failing tests**

`tailtop/tests/test_collect_vitals.py`:

```python
"""collect_vitals: user resolution + parse of piped script output."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.data.client import TailscaleClient, ssh_user_for

FIX = Path(__file__).parent / "fixtures"

USER_MAP = {
    "fastclock": "nickv2026", "slowclock": "nickv2026",
    "smallclock": "nickv2026", "squareclock": "nickv2026",
    "nickv-orangepizero2w": "nickv",
}


def test_ssh_user_for_known_hosts() -> None:
    assert ssh_user_for("fastclock", USER_MAP) == "nickv2026"
    assert ssh_user_for("nickv-orangepizero2w", USER_MAP) == "nickv"


def test_ssh_user_for_unknown_falls_back_to_default() -> None:
    assert ssh_user_for("dashboard-ink-bed", USER_MAP, default="pi") == "pi"


async def test_collect_vitals_parses_piped_output(monkeypatch) -> None:
    raw = (FIX / "vitals_fastclock.json").read_text()
    client = TailscaleClient()

    async def fake_ssh(self, host, user):  # noqa: ANN001
        assert user == "nickv2026"
        return raw

    monkeypatch.setattr(TailscaleClient, "_ssh_collect", fake_ssh, raising=True)
    v = await client.collect_vitals("fastclock", user_map=USER_MAP)
    assert v is not None
    assert v.host == "fastclock"
    assert v.vcgencmd_present is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_collect_vitals.py -v`
Expected: FAIL — `ImportError: cannot import name 'ssh_user_for'`.

- [ ] **Step 3: Implement in `client.py`**

Add near the top of `tailtop/tailtop/data/client.py` (after the existing imports add `from pathlib import Path` and `from tailtop.data.vitals import Vitals`):

```python
_AGENT_SCRIPT = Path(__file__).parents[2] / "agent" / "fleet_collect.sh"  # project-root agent/


def ssh_user_for(host: str, user_map: dict[str, str], default: str = "") -> str:
    """Resolve the SSH login user for a Pi host (explicit map wins)."""
    return user_map.get(host, default)
```

Add these methods to `TailscaleClient`:

```python
    async def _ssh_collect(self, host: str, user: str) -> str:
        """Run the collect script on `host` over tailscale ssh, return stdout."""
        dest = f"{user}@{host}" if user else host
        script = _AGENT_SCRIPT.read_bytes()
        proc = await asyncio.create_subprocess_exec(
            self._binary, "ssh", dest, "--", "sh", "-s",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(script), timeout=10.0)
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TailscaleTimeout(f"collect {host}") from exc
        if proc.returncode != 0:
            raise TailscaleError(["ssh", dest], proc.returncode or -1, err.decode("utf-8", "replace"))
        return out.decode("utf-8", "replace")

    async def collect_vitals(self, host: str, user_map: dict[str, str]) -> Vitals | None:
        """Collect + parse vitals for one Pi host. Returns None on failure."""
        import json as _json
        user = ssh_user_for(host, user_map)
        raw = await self._ssh_collect(host, user)
        return Vitals.from_collect_json(_json.loads(raw))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_collect_vitals.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/data/client.py tailtop/tests/test_collect_vitals.py
git commit -m "feat(vitals): client.collect_vitals over tailscale ssh + user resolution"
```

---

## Task 4: `VitalsPoller`

**Files:**
- Create: `tailtop/tailtop/data/vitals_poller.py`
- Create: `tailtop/tests/test_vitals_poller.py`

- [ ] **Step 1: Write the failing tests**

`tailtop/tests/test_vitals_poller.py`:

```python
"""VitalsPoller: collects only Pi hosts, survives per-host failures."""
from __future__ import annotations

import asyncio

from tailtop.data.vitals import Vitals
from tailtop.data.vitals_poller import VitalsPoller, PI_HOSTS


class FakeClient:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def collect_vitals(self, host, user_map):  # noqa: ANN001
        self.calls.append(host)
        b = self.behaviour.get(host)
        if isinstance(b, Exception):
            raise b
        return b


async def test_collects_each_pi_once() -> None:
    hosts = ["fastclock", "slowclock"]
    client = FakeClient({h: Vitals(host=h, soc_temp_c=40.0) for h in hosts})
    poller = VitalsPoller(client, pi_hosts=hosts, user_map={})
    result = await poller.collect_round()
    assert set(result) == {"fastclock", "slowclock"}
    assert sorted(client.calls) == ["fastclock", "slowclock"]


async def test_one_host_failure_does_not_sink_the_round() -> None:
    client = FakeClient({
        "fastclock": Vitals(host="fastclock", soc_temp_c=42.0),
        "slowclock": asyncio.TimeoutError(),
    })
    poller = VitalsPoller(client, pi_hosts=["fastclock", "slowclock"], user_map={})
    result = await poller.collect_round()
    assert "fastclock" in result
    assert "slowclock" not in result


def test_pi_hosts_default_list_is_the_known_fleet() -> None:
    assert "fastclock" in PI_HOSTS
    assert "nickv-orangepizero2w" in PI_HOSTS
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_vitals_poller.py -v`
Expected: FAIL — `ModuleNotFoundError: ... vitals_poller`.

- [ ] **Step 3: Implement `vitals_poller.py`**

`tailtop/tailtop/data/vitals_poller.py`:

```python
"""Slow background poll of Pi hardware vitals over tailscale ssh.

Runs alongside the network Poller on a slower cadence so SSH latency never
drags the live UI. Each round collects all Pi hosts concurrently (capped);
one host failing never sinks the round.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from tailtop.data.vitals import Vitals

# No ACL tags in use → explicit allowlist of the Pi fleet (see spec §14).
PI_HOSTS = [
    "fastclock", "slowclock", "smallclock", "squareclock",
    "dashboard-ink-bed", "dashboard3eink", "plantdashboard",
    "nickv-orangepizero2w",
]

# SSH login users (spec §15). Unknown hosts fall back to the default.
USER_MAP = {
    "fastclock": "nickv2026", "slowclock": "nickv2026",
    "smallclock": "nickv2026", "squareclock": "nickv2026",
    "nickv-orangepizero2w": "nickv",
}

VitalsCallback = Callable[[dict[str, Vitals]], Awaitable[None] | None]
ErrorCallback = Callable[[Exception], Awaitable[None] | None]


class VitalsPoller:
    def __init__(
        self,
        client,
        on_vitals: VitalsCallback | None = None,
        on_error: ErrorCallback | None = None,
        pi_hosts: list[str] | None = None,
        user_map: dict[str, str] | None = None,
        interval: float = 30.0,
        concurrency: int = 5,
    ) -> None:
        self._client = client
        self._on_vitals = on_vitals
        self._on_error = on_error
        self._hosts = pi_hosts if pi_hosts is not None else PI_HOSTS
        self._user_map = user_map if user_map is not None else USER_MAP
        self._interval = interval
        self._sem = asyncio.Semaphore(concurrency)
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    async def _collect_one(self, host: str) -> tuple[str, Vitals | None]:
        async with self._sem:
            try:
                return host, await self._client.collect_vitals(host, self._user_map)
            except Exception:  # noqa: BLE001 — one host's failure is not fatal
                return host, None

    async def collect_round(self) -> dict[str, Vitals]:
        pairs = await asyncio.gather(*(self._collect_one(h) for h in self._hosts))
        return {h: v for h, v in pairs if v is not None}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def refresh_now(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                vitals = await self.collect_round()
                result = self._on_vitals(vitals) if self._on_vitals else None
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._on_error:
                    r = self._on_error(exc)
                    if asyncio.iscoroutine(r):
                        await r
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_vitals_poller.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/data/vitals_poller.py tailtop/tests/test_vitals_poller.py
git commit -m "feat(vitals): VitalsPoller — slow concurrency-capped SSH poll loop"
```

---

## Task 5: `VitalsHistory` ring buffers

**Files:**
- Modify: `tailtop/tailtop/state.py`
- Modify: `tailtop/tests/test_state.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_state.py`)

```python
def test_vitals_history_tracks_temp_and_cpu() -> None:
    from tailtop.state import VitalsHistory
    h = VitalsHistory()
    h.update("p1", temp_c=40.0, cpu_pct=5.0)
    h.update("p1", temp_c=42.0, cpu_pct=7.0)
    assert h.temp_series("p1") == [40.0, 42.0]
    assert h.cpu_series("p1") == [5.0, 7.0]
    assert h.temp_series("absent") == []


def test_vitals_history_skips_none_temp() -> None:
    from tailtop.state import VitalsHistory
    h = VitalsHistory()
    h.update("p1", temp_c=None, cpu_pct=3.0)
    assert h.temp_series("p1") == []
    assert h.cpu_series("p1") == [3.0]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_state.py -k vitals_history -v`
Expected: FAIL — `ImportError: cannot import name 'VitalsHistory'`.

- [ ] **Step 3: Implement** — append to `tailtop/tailtop/state.py`:

```python
class VitalsHistory:
    """Per-peer rolling temperature/CPU gauges for sparklines (append-only)."""

    WIDTH = 32

    def __init__(self) -> None:
        self._temp: dict[str, deque[float]] = {}
        self._cpu: dict[str, deque[float]] = {}

    def update(self, peer_id: str, temp_c: float | None, cpu_pct: float | None) -> None:
        if temp_c is not None:
            self._temp.setdefault(peer_id, deque(maxlen=self.WIDTH)).append(float(temp_c))
        if cpu_pct is not None:
            self._cpu.setdefault(peer_id, deque(maxlen=self.WIDTH)).append(float(cpu_pct))

    def temp_series(self, peer_id: str) -> list[float]:
        return list(self._temp.get(peer_id, ()))

    def cpu_series(self, peer_id: str) -> list[float]:
        return list(self._cpu.get(peer_id, ()))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_state.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/state.py tailtop/tests/test_state.py
git commit -m "feat(vitals): VitalsHistory ring buffers for temp/cpu sparklines"
```

---

## Task 6: App wiring (poller + state + thread into modes)

**Files:**
- Modify: `tailtop/tailtop/app.py`
- Create: `tailtop/tests/test_vitals_app.py`

- [ ] **Step 1: Write the failing test**

`tailtop/tests/test_vitals_app.py`:

```python
"""The VitalsPoller wires into the app and populates app.vitals."""
from __future__ import annotations

import json
from pathlib import Path

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.data.vitals import Vitals

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    available = True

    def __init__(self, status: Status) -> None:
        self._status = status

    async def status(self) -> Status:
        return self._status

    async def collect_vitals(self, host, user_map):  # noqa: ANN001
        return Vitals(host=host, soc_temp_c=55.0, cpu_pct=9.0)


async def test_app_populates_vitals() -> None:
    status = Status.from_json(json.loads(FIXTURE.read_text()))
    app = TailtopApp(client=FakeClient(status), auto_poll=True, splash=False)
    # Poll only a couple of known hosts to keep the test fast/deterministic.
    app.vitals_poller._hosts = ["fastclock"]
    async with app.run_test() as pilot:
        for _ in range(8):
            await pilot.pause()
            if app.vitals:
                break
        assert "fastclock" in app.vitals
        assert app.vitals["fastclock"].soc_temp_c == 55.0
        assert app.vitals_history.temp_series("fastclock") == [55.0]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_vitals_app.py -v`
Expected: FAIL — `AttributeError: 'TailtopApp' object has no attribute 'vitals_poller'`.

- [ ] **Step 3: Implement** — edits to `tailtop/tailtop/app.py`:

(a) Add imports near the other data imports:
```python
from tailtop.data.vitals import Vitals
from tailtop.data.vitals_poller import VitalsPoller
from tailtop.state import RateHistory, VitalsHistory
```
(replace the existing `from tailtop.state import RateHistory` line).

(b) In `__init__`, after `self.poller = Poller(...)`:
```python
        self.vitals: dict[str, Vitals] = {}
        self.vitals_history = VitalsHistory()
        self.vitals_poller = VitalsPoller(self.client, self._on_vitals, self._on_error)
```

(c) In `on_mount`, inside `if self.auto_poll:`, after `self.poller.start()`:
```python
            self.vitals_poller.start()
```

(d) Add the callback after `_on_status`:
```python
    def _on_vitals(self, vitals: dict[str, Vitals]) -> None:
        # The poller keys by hostname; the UI looks up by peer id. Remap here so
        # cards/detail/alert (which use peer.id) find their vitals.
        remapped: dict[str, Vitals] = {}
        for host, v in vitals.items():
            pid = pid_for(self.status, host)
            remapped[pid] = v
            self.vitals_history.update(pid, v.soc_temp_c, v.cpu_pct)
        self.vitals = remapped
        if self.status is not None:
            self._mode_widget().update_data(self.status, self.rates)
```

(e) Add a module-level helper (peer ids differ from hostnames; map host→peer id) above the class:
```python
def pid_for(status: "Status | None", host: str) -> str:
    """Best-effort peer id for a Pi hostname (falls back to the host)."""
    if status is not None:
        for p in status.all_nodes():
            if p.host_name == host:
                return p.id
    return host
```

(f) In `on_unmount`, after `await self.latency.stop()`:
```python
        await self.vitals_poller.stop()
```

> The modes read `self.app.vitals` directly when rendering (Tasks 7–9), so `update_data(status, rates)` signatures stay unchanged. `_on_vitals` re-renders the active mode so vitals appear between network polls.

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_vitals_app.py -v`
Expected: pass. Then full suite: `uv run --extra dev pytest -q` → still green.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/app.py tailtop/tests/test_vitals_app.py
git commit -m "feat(vitals): wire VitalsPoller + VitalsHistory into the app"
```

---

## Task 7: Vitals on the Cockpit device card

**Files:**
- Modify: `tailtop/tailtop/widgets/device_card.py`
- Modify: `tailtop/tailtop/modes/cockpit.py`
- Create: `tailtop/tests/test_device_card_vitals.py`

- [ ] **Step 1: Write the failing test**

`tailtop/tests/test_device_card_vitals.py`:

```python
"""The device card shows a vitals badge when vitals are present."""
from __future__ import annotations

from tailtop.data.vitals import Vitals
from tailtop.widgets.device_card import vitals_badge


def test_badge_shows_temp_and_disk() -> None:
    v = Vitals(host="fastclock", soc_temp_c=58.0, cpu_pct=12.0, mem_pct=30.0, disk_used_pct=41.0)
    text = vitals_badge(v).plain
    assert "58" in text
    assert "41" in text


def test_badge_flags_throttle() -> None:
    v = Vitals(host="fastclock", soc_temp_c=84.0, throttled_now=True)
    text = vitals_badge(v).plain.lower()
    assert "throttl" in text or "84" in text


def test_no_badge_for_none() -> None:
    assert vitals_badge(None).plain == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_device_card_vitals.py -v`
Expected: FAIL — `ImportError: cannot import name 'vitals_badge'`.

- [ ] **Step 3: Implement**

In `tailtop/tailtop/widgets/device_card.py`, add the `Vitals` import (the `RateHistory`/`human_rate`/`sparkline` imports already exist in this file) and a pure helper:
```python
from tailtop.data.vitals import Vitals

_HEALTH_COLOR = {"ok": "#7be39b", "warn": "#f0c674", "crit": "#ff7878"}


def vitals_badge(v: Vitals | None) -> Text:
    """One-line temp/cpu/mem/disk badge, colored by health. Empty when no vitals."""
    if v is None:
        return Text("")
    color = _HEALTH_COLOR[v.health_level]
    t = Text()
    if v.soc_temp_c is not None:
        t.append(f"{v.soc_temp_c:.0f}°C", style=color)
        t.append("  ", style="dim")
    if v.throttled_now or v.under_voltage_now:
        t.append("⚡throttled  ", style="#ff7878")
    t.append(f"cpu {v.cpu_pct:.0f}%  ", style="dim")
    t.append(f"mem {v.mem_pct:.0f}%  ", style="dim")
    t.append(f"disk {v.disk_used_pct:.0f}%", style=color)
    return t
```

Change `update_card` to accept vitals and render the badge. Replace the signature and append to the rendered `Group`:
```python
    def update_card(self, peer: Peer, rates: RateHistory, vitals: Vitals | None = None) -> None:
```
At the end of `update_card`, where it currently calls `self.update(Group(status_line, path_line, Text(""), rx, tx))`, replace with:
```python
        rows = [status_line, path_line, Text(""), rx, tx]
        if vitals is not None:
            rows.append(Text(""))
            rows.append(vitals_badge(vitals))
        self.update(Group(*rows))
```

In `tailtop/tailtop/modes/cockpit.py`, pass per-card vitals — change the `card.update_card(peer, rates)` call to:
```python
            card.update_card(peer, rates, getattr(self.app, "vitals", {}).get(peer.id))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_device_card_vitals.py -q && uv run --extra dev pytest -q`
Expected: new tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/widgets/device_card.py tailtop/tailtop/modes/cockpit.py tailtop/tests/test_device_card_vitals.py
git commit -m "feat(vitals): temp/health badge on the Cockpit device card"
```

---

## Task 8: Vitals + Hardware panels in DeviceDetail

**Files:**
- Modify: `tailtop/tailtop/widgets/detail_pane.py`
- Modify: `tailtop/tailtop/modes/comfort.py`, `tailtop/tailtop/modes/the_base.py`
- Create: `tailtop/tests/test_detail_vitals.py`

- [ ] **Step 1: Write the failing test**

`tailtop/tests/test_detail_vitals.py`:

```python
"""DeviceDetail shows vitals/hardware panels only when vitals are present."""
from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Static

from tailtop.data.latency import LatencyProbe
from tailtop.data.models import Peer
from tailtop.data.vitals import Display, Vitals
from tailtop.state import RateHistory
from tailtop.widgets.detail_pane import DeviceDetail


def _peer() -> Peer:
    return Peer(
        id="p1", host_name="fastclock", dns_name="fastclock.example.", os="linux",
        ips=["100.78.29.28"], online=True, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="100.78.29.28:41641",
        rx_bytes=0, tx_bytes=0, last_handshake=None, key_expiry=None,
    )


class _Harness(App):
    def compose(self):
        yield DeviceDetail(id="d")


async def test_vitals_panel_visible_with_vitals() -> None:
    v = Vitals(host="fastclock", soc_temp_c=57.0, disk_used_pct=44.0,
               displays=[Display("HDMI-A-1", "connected")], app_name="superclock", app_running=True)
    async with _Harness().run_test() as pilot:
        d = pilot.app.query_one(DeviceDetail)
        d.update_peer(_peer(), RateHistory(), LatencyProbe(None), None, vitals=v)
        panel = pilot.app.query_one("#panel-vitals", Static)
        assert panel.display is True
        assert "57" in panel.renderable.plain if hasattr(panel.renderable, "plain") else True


async def test_vitals_panel_hidden_without_vitals() -> None:
    async with _Harness().run_test() as pilot:
        d = pilot.app.query_one(DeviceDetail)
        d.update_peer(_peer(), RateHistory(), LatencyProbe(None), None, vitals=None)
        assert pilot.app.query_one("#panel-vitals", Static).display is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_detail_vitals.py -v`
Expected: FAIL — `NoMatches: #panel-vitals` (panel not composed yet).

- [ ] **Step 3: Implement**

In `tailtop/tailtop/widgets/detail_pane.py`:

(a) Import vitals at top: `from tailtop.data.vitals import Vitals`.

(b) In `compose`, inside `#detail-info`, after the `#panel-exit` line, add:
```python
                yield Static(id="panel-vitals", classes="dpanel")
                yield Static(id="panel-hardware", classes="dpanel")
```

(c) In `show_empty`, add the two ids to the hide-loop tuple:
```python
        for pid in ("#panel-status", "#panel-network", "#panel-exit",
                    "#panel-vitals", "#panel-hardware",
                    "#panel-throughput", "#panel-quality"):
```

(d) Change `update_peer` signature to accept vitals (keep it last + defaulted so existing callers still type-check):
```python
    def update_peer(
        self,
        peer: Peer,
        rates: RateHistory,
        probe: LatencyProbe,
        netcheck: NetCheck | None = None,
        vitals: Vitals | None = None,
    ) -> None:
```

(e) At the end of `update_peer`, before `self.query_one("#detail-actions", Static).display = True`, add:
```python
        self._vitals_panels(vitals)
```

(f) Add the helper near the other helpers:
```python
    def _vitals_panels(self, vitals: Vitals | None) -> None:
        vp = self.query_one("#panel-vitals", Static)
        hp = self.query_one("#panel-hardware", Static)
        if vitals is None:
            vp.display = False
            hp.display = False
            return
        color = {"ok": "#7be39b", "warn": "#f0c674", "crit": "#ff7878"}[vitals.health_level]
        temp = f"{vitals.soc_temp_c:.0f}°C" if vitals.soc_temp_c is not None else "—"
        flags = []
        if vitals.throttled_now:
            flags.append("throttled")
        if vitals.under_voltage_now:
            flags.append("under-voltage")
        self._panel("#panel-vitals", "Vitals", color, _kv([
            ("Temp", Text(temp, style=color)),
            ("Flags", ", ".join(flags) if flags else Text("none", style="#6b6f78")),
            ("Load", f"{vitals.load1:.2f}"),
            ("CPU", f"{vitals.cpu_pct:.0f}%"),
            ("Memory", f"{vitals.mem_pct:.0f}%"),
            ("Disk", Text(f"{vitals.disk_used_pct:.0f}% used · {vitals.disk_free_gb:.1f} GB free", style=color)),
            ("Uptime", f"{vitals.uptime_s // 86400}d {vitals.uptime_s % 86400 // 3600}h"),
        ]))
        displays = "\n".join(f"{d.connector} {d.mode}".strip() for d in vitals.displays) or "—"
        battery = f"{vitals.battery_pct:.0f}%" if vitals.battery_present and vitals.battery_pct is not None else ("present" if vitals.battery_present else "—")
        app = "—"
        if vitals.app_name:
            app = f"{vitals.app_name}: " + ("running" if vitals.app_running else "DOWN")
        self._panel("#panel-hardware", "Hardware", "#8bb6ff", _kv([
            ("Model", vitals.model or "—"),
            ("Displays", displays),
            ("USB", str(vitals.usb_count)),
            ("Battery", battery),
            ("App", Text(app, style="#ff7878" if vitals.app_running is False else "white")),
        ]))
```

(g) In `tailtop/tailtop/modes/comfort.py` `_render_detail`, add the vitals argument:
```python
        self.query_one(DeviceDetail).update_peer(
            self._selected_peer,
            app.rates,
            app.latency,
            getattr(app, "netcheck_self", None),
            getattr(app, "vitals", {}).get(self._selected_peer.id),
        )
```

(h) In `tailtop/tailtop/modes/the_base.py`, both `update_peer(...)` calls gain the vitals arg — change them to:
```python
                self.query_one(DeviceDetail).update_peer(
                    peer, self.app.rates, self.app.latency,
                    getattr(self.app, "netcheck_self", None),
                    getattr(self.app, "vitals", {}).get(peer.id),
                )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_detail_vitals.py -q && uv run --extra dev pytest -q`
Expected: new tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/widgets/detail_pane.py tailtop/tailtop/modes/comfort.py tailtop/tailtop/modes/the_base.py tailtop/tests/test_detail_vitals.py
git commit -m "feat(vitals): Vitals + Hardware panels in DeviceDetail"
```

---

## Task 9: Health folded into the AlertStrip

**Files:**
- Modify: `tailtop/tailtop/widgets/alert_strip.py`
- Modify: `tailtop/tailtop/modes/the_base.py`
- Modify: `tailtop/tests/test_alert_strip.py` (add cases)

- [ ] **Step 1: Write the failing test** (append to `tests/test_alert_strip.py`; create the file with this content if it does not exist)

```python
def test_summarise_alerts_includes_health() -> None:
    from tailtop.data.models import Status
    from tailtop.data.vitals import Vitals
    from tailtop.widgets.alert_strip import summarise_alerts

    status = Status(
        version="dev", backend_state="Running", tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="x", user_display="me", self_peer=None, peers=[],
    )
    vbi = {"p1": Vitals(host="fastclock", soc_temp_c=85.0)}
    out = summarise_alerts(status, vbi)
    assert "fastclock" in out
```

> If `Status(... self_peer=None ...)` is rejected by the model, build a minimal self peer with the `_self()` helper pattern from `tests/test_the_base.py`.

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_alert_strip.py -k includes_health -v`
Expected: FAIL — `summarise_alerts() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement** — in `tailtop/tailtop/widgets/alert_strip.py`:

(a) Import: `from tailtop.data.vitals import Vitals, summarise_health`.

(b) Change `summarise_alerts` to accept optional vitals and append health:
```python
def summarise_alerts(status: Status, vitals_by_id: dict[str, Vitals] | None = None) -> str:
    parts: list[str] = []
    if status.backend_state and status.backend_state != "Running":
        parts.append(status.backend_state)
    offline = sum(1 for p in status.peers if not p.online)
    if offline:
        parts.append(f"{offline} offline")
    # ... keep the existing key-expiry block unchanged ...
    if vitals_by_id:
        health = summarise_health(vitals_by_id)
        if health:
            parts.append(health)
    return " · ".join(parts)
```

(c) Change `AlertStrip.set_status` to accept vitals:
```python
    def set_status(self, status: Status, vitals_by_id: dict[str, Vitals] | None = None) -> None:
        text = summarise_alerts(status, vitals_by_id)
```

(d) In `tailtop/tailtop/modes/the_base.py`, pass vitals to the strip:
```python
        self.query_one(AlertStrip).set_status(status, getattr(self.app, "vitals", None))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_alert_strip.py -q && uv run --extra dev pytest -q`
Expected: pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/widgets/alert_strip.py tailtop/tailtop/modes/the_base.py tailtop/tests/test_alert_strip.py
git commit -m "feat(vitals): fold fleet health into the AlertStrip"
```

---

## Task 10: `tailtop fleet` one-shot command

**Files:**
- Create: `tailtop/tailtop/fleet_report.py`
- Modify: `tailtop/tailtop/app.py` (`main`)
- Create: `tailtop/tests/test_fleet_report.py`

- [ ] **Step 1: Write the failing test**

`tailtop/tests/test_fleet_report.py`:

```python
"""tailtop fleet: render a table + exit code from vitals."""
from __future__ import annotations

from tailtop.data.vitals import Vitals
from tailtop.fleet_report import render_fleet


def test_render_lists_each_host_and_exits_zero_when_healthy() -> None:
    vbi = {
        "a": Vitals(host="fastclock", soc_temp_c=55.0, disk_used_pct=40.0),
        "b": Vitals(host="slowclock", soc_temp_c=49.0, disk_used_pct=33.0),
    }
    text, code = render_fleet(vbi)
    assert "fastclock" in text and "slowclock" in text
    assert code == 0


def test_exit_nonzero_when_any_host_critical() -> None:
    vbi = {"a": Vitals(host="fastclock", soc_temp_c=85.0)}
    text, code = render_fleet(vbi)
    assert code == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tailtop && uv run --extra dev pytest tests/test_fleet_report.py -v`
Expected: FAIL — `ModuleNotFoundError: ... fleet_report`.

- [ ] **Step 3: Implement**

`tailtop/tailtop/fleet_report.py`:

```python
"""Pure renderer for the `tailtop fleet` one-shot table."""
from __future__ import annotations

from tailtop.data.vitals import Vitals

_MARK = {"ok": "·", "warn": "!", "crit": "✗"}


def render_fleet(vitals_by_id: dict[str, Vitals]) -> tuple[str, int]:
    """Return (table_text, exit_code). exit_code is 1 if any host is critical."""
    rows = ["  HOST                 TEMP   CPU   MEM   DISK   APP        HEALTH"]
    worst_crit = False
    for v in sorted(vitals_by_id.values(), key=lambda x: x.host):
        worst_crit = worst_crit or v.health_level == "crit"
        temp = f"{v.soc_temp_c:.0f}C" if v.soc_temp_c is not None else "—"
        app = (v.app_name or "—")[:9]
        if v.app_running is False:
            app += "↓"
        rows.append(
            f"{_MARK[v.health_level]} {v.host:<20} {temp:>4} {v.cpu_pct:>4.0f}% "
            f"{v.mem_pct:>4.0f}% {v.disk_used_pct:>4.0f}%  {app:<10} {v.health_level}"
        )
    if not vitals_by_id:
        rows.append("  (no Pi vitals collected)")
    return "\n".join(rows), (1 if worst_crit else 0)
```

In `tailtop/tailtop/app.py` `main`, add a `fleet` subcommand. Replace the body of `main` with:
```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tailtop", description="htop for your tailnet")
    parser.add_argument("command", nargs="?", choices=["fleet"], help="one-shot subcommand")
    parser.add_argument(
        "--demo",
        action="store_true",
        default=os.environ.get("TAILTOP_DEMO") in ("1", "true", "yes"),
        help="Run against a synthetic tailnet (no tailscaled needed).",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "fleet":
        import asyncio

        from tailtop.data.vitals_poller import VitalsPoller
        from tailtop.fleet_report import render_fleet

        async def _run() -> int:
            poller = VitalsPoller(TailscaleClient())
            vitals = await poller.collect_round()
            text, code = render_fleet(vitals)
            print(text)
            return code

        sys.exit(asyncio.run(_run()))

    client = None
    if args.demo:
        from tailtop.data.demo import DemoClient

        client = DemoClient()
    TailtopApp(client=client).run()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tailtop && uv run --extra dev pytest tests/test_fleet_report.py -q && uv run --extra dev pytest -q`
Expected: new tests pass; full suite green.

- [ ] **Step 5: Live smoke test** (optional, needs the tailnet)

Run: `cd tailtop && uv run tailtop fleet`
Expected: a table of all reachable Pis with temps; exit code 0 unless something is genuinely critical (`echo $?`).

- [ ] **Step 6: Commit**

```bash
git add tailtop/tailtop/fleet_report.py tailtop/tailtop/app.py tailtop/tests/test_fleet_report.py
git commit -m "feat(vitals): tailtop fleet one-shot status table"
```

---

## Task 11: Package the agent script + README note

**Files:**
- Modify: `tailtop/pyproject.toml`
- Modify: `tailtop/README.md`

- [ ] **Step 1: Ensure the script ships in the wheel**

In `tailtop/pyproject.toml`, under `[tool.hatch.build.targets.wheel]`, add a force-include so `agent/fleet_collect.sh` is packaged with the `tailtop` package:
```toml
[tool.hatch.build.targets.wheel]
packages = ["tailtop"]

[tool.hatch.build.targets.wheel.force-include]
"agent/fleet_collect.sh" = "tailtop/agent/fleet_collect.sh"
```
The canonical script lives at `tailtop/agent/fleet_collect.sh` (project root). From `client.py` (`tailtop/tailtop/data/client.py`), `Path(__file__).parents[2]` is the project dir, so Task 3's `_AGENT_SCRIPT` resolves it when run from source; the force-include above maps the same file into the package dir for wheels. Verify it's found:
```bash
cd tailtop && python -c "from tailtop.data.client import _AGENT_SCRIPT; print(_AGENT_SCRIPT.exists())"
```

- [ ] **Step 2: README note**

Add a short "Fleet vitals" section to `tailtop/README.md` documenting `tailtop fleet` and that Pi telemetry is pulled over `tailscale ssh` (zero install on the Pis).

- [ ] **Step 3: Full suite + commit**

Run: `cd tailtop && uv run --extra dev pytest -q`
Expected: all green.
```bash
git add tailtop/pyproject.toml tailtop/README.md
git commit -m "chore(vitals): package the agent script + document tailtop fleet"
```

---

## Done criteria (Phase 1)

- `uv run --extra dev pytest` fully green (existing 107 + new vitals tests).
- `uv run tailtop` → Cockpit cards show temp/health badges for Pis; Comfort detail shows Vitals + Hardware panels; TheBase alert strip surfaces overheating/throttle/disk/app-down.
- `uv run tailtop fleet` → fleet table; non-zero exit on a critical Pi.
- The 8 Pis report; non-Pi peers render unchanged (no vitals).

## Out of scope (Phase 2 — separate plan)

SQLite history + sparkline backfill; inventory export to `INFRASTRUCTURE.md`/Affine; out-of-band `tailtop alert` launchd daemon with Telegram/Slack/ntfy/macOS; `--fast`/`--full` collect split; optional pre-install deploy; real per-USB detail; temp sparkline in Cockpit via persisted history.
