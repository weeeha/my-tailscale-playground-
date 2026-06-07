# tailtop Device Vitals — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. TDD throughout: failing test → run → implement → green → commit. Full suite + `uvx ruff check tailtop/` must stay clean after every task.

**Goal:** Extend the shipped Phase-1 vitals feature with (A) persisted history + Cockpit sparklines, (B) a `tailscale ssh` transport so all 8 Pis report (and it works off-LAN), (C) out-of-band Telegram/Slack/ntfy alerts, (D) inventory export to `INFRASTRUCTURE.md`.

**Base:** branch `claude/tailtop-device-vitals` (Phase 1 merged + 133 tests green). Project dir: `tailtop/`. Test: `uv run --extra dev pytest -q`. Lint: `uvx ruff check tailtop/`.

**Builds on:** `2026-06-06-tailtop-device-vitals-design.md` (Phase 1). Existing pieces to reuse: `data/vitals.py` (`Vitals`, thresholds, `summarise_health`), `data/vitals_poller.py` (`VitalsPoller`, `PI_HOSTS`, `USER_MAP`), `state.py` (`VitalsHistory`, `sparkline`), `data/client.py` (`collect_vitals`, `_ssh_collect`, `ssh_user_for`), `app.py` (`pid_for`, `_on_vitals`), `fleet_report.py`.

---

## Feature A — Persisted history + Cockpit sparklines

### Task 14: SQLite vitals history store

**Files:** Create `tailtop/tailtop/data/history.py`, `tailtop/tests/test_history.py`.

`history.py` — a tiny stdlib `sqlite3` store. One table `samples(host TEXT, ts REAL, temp_c REAL, cpu_pct REAL, disk_pct REAL, health TEXT)`. Default DB path `~/.local/state/tailtop/vitals.db` (create parent dirs; allow an explicit path for tests).

```python
class VitalsStore:
    def __init__(self, path: str | Path | None = None) -> None: ...   # ":memory:" allowed
    def record(self, host: str, ts: float, v: "Vitals") -> None: ...  # one row
    def recent_temps(self, host: str, limit: int = 32) -> list[float]: ...  # oldest→newest
    def recent_cpu(self, host: str, limit: int = 32) -> list[float]: ...
    def close(self) -> None: ...
```

- [ ] **Step 1 (test):** in-memory store — `record` two samples for a host, assert `recent_temps`/`recent_cpu` return them oldest→newest; assert `recent_temps("absent") == []`; assert a third `record` past `limit` truncates (query `limit=2`).
- [ ] **Step 2:** run → fail (no module).
- [ ] **Step 3:** implement `VitalsStore` (use `sqlite3`, `CREATE TABLE IF NOT EXISTS`, parametrized inserts, `ORDER BY ts DESC LIMIT ?` then reverse for oldest→newest). `record` reads `v.soc_temp_c`/`v.cpu_pct`/`v.disk_used_pct`/`v.health_level`; skip the temp row only if both temp and cpu are None.
- [ ] **Step 4:** run → green; full suite green.
- [ ] **Step 5:** commit `feat(vitals): SQLite VitalsStore for history`.

### Task 15: Persist rounds + backfill history on launch

**Files:** Modify `tailtop/tailtop/app.py`; Create `tailtop/tests/test_history_wiring.py`.

- In `TailtopApp.__init__`, add `self.vitals_store = VitalsStore()` (real DB; tests inject a `:memory:` store via a new optional `store=` kwarg — add `store: VitalsStore | None = None` param, default constructs one).
- In `_on_vitals`, after remapping, for each `(pid, v)` call `self.vitals_store.record(v.host, time.monotonic(), v)` AND `self.vitals_history.update(pid, ...)` as today.
- On `on_mount` (before polling), backfill `vitals_history` from the store for known hosts: for each peer in `self.status` (may be None — guard), seed `vitals_history` from `store.recent_temps/cpu`. Since status isn't ready at mount, instead backfill lazily in `_on_status` the first time: add a `self._history_backfilled = False` guard; on first status, for each peer call `vitals_history`-seed from `store.recent_*(peer.host_name)`. Add a `VitalsHistory.seed(peer_id, temps, cpus)` helper (extend `state.py`) that appends a list at once.
- `on_unmount`: `self.vitals_store.close()`.

- [ ] **Step 1 (test):** construct `TailtopApp(client=FakeClient(status), store=VitalsStore(":memory:"), auto_poll=False, splash=False)`; pre-`record` two samples for a host in the store; drive one `_on_status(status)`; assert `vitals_history.temp_series(pid)` is seeded from the store. Then call `_on_vitals({host: Vitals(...)})`; assert a new row is in the store (`recent_temps` grew).
- [ ] **Step 2–5:** fail → implement (`VitalsHistory.seed`, app wiring, backfill guard) → green → full suite green → commit `feat(vitals): persist rounds + backfill sparkline history on launch`.

### Task 16: Cockpit card temp sparkline

**Files:** Modify `tailtop/tailtop/widgets/device_card.py`, `tailtop/tailtop/modes/cockpit.py`; Modify `tailtop/tests/test_device_card_vitals.py`.

- `update_card(self, peer, rates, vitals=None, temp_series=None)` — add `temp_series: list[float] | None = None`. When `vitals` and a non-empty `temp_series` are present, append a line `temp ▁▂▃▅▇` using the existing `sparkline(temp_series, width=12)` (import from `tailtop.state`) colored by `vitals.health_level`.
- `cockpit.py`: pass `temp_series=getattr(self.app, "vitals_history", None).temp_series(peer.id) if hasattr(self.app, "vitals_history") else None` into `update_card`.

- [ ] **Step 1 (test):** add `test_card_renders_temp_sparkline` — `update_card(peer, RateHistory(), vitals, temp_series=[40,45,50,55])` and assert the rendered card text contains a spark glyph (e.g. any of `▁▂▃▄▅▆▇█`).
- [ ] **Step 2–5:** fail → implement → green → full suite green → commit `feat(vitals): temp sparkline on Cockpit card`.

---

## Feature B — `tailscale ssh` transport (all 8 Pis, off-LAN)

**Context:** Live testing proved key-based OpenSSH to a Pi's Tailscale IP hangs — those nodes run **Tailscale SSH**, which intercepts port 22 on the `100.x` address and applies its own auth. The e-paper Pis + Orange Pi have no `.local` ssh-config entry, so they never report via OpenSSH. The fix: collect via `tailscale ssh`, which is the intended path for these nodes and works off-LAN.

**Requires (user, one-time):** a tailnet ACL SSH rule permitting the Mac → Pis without check-mode. Provide this snippet in the task output and the final report:
```jsonc
// in the tailnet policy file, "ssh" section:
{
  "action": "accept",
  "src":    ["autogroup:member"],     // or the Mac's user/tag
  "dst":    ["autogroup:self", "tag:pi"],  // or the specific Pi hosts
  "users":  ["nickv2026", "nickv"]
}
```
(`action: accept` — not `check` — so no browser prompt for unattended polling.)

### Task 17: select transport (openssh | tailscale-ssh), default tailscale-ssh

**Files:** Modify `tailtop/tailtop/data/client.py`, `tailtop/tailtop/data/vitals_poller.py`; Modify `tailtop/tests/test_collect_vitals.py`.

- In `client._ssh_collect(self, dest, user)`, branch on a new `self.ssh_transport` attribute (set in `__init__`, default `"tailscale"`, override `"openssh"`):
  - `"tailscale"`: `await self._run_pipe(self._binary, "ssh", f"{user}@{dest}", "--", "sh", "-s", script)` — i.e. shell `tailscale ssh <user>@<dest> -- sh -s` with the script on stdin.
  - `"openssh"`: the current `ssh -i ~/.ssh/id_ed25519 …` path (keep as fallback).
  - Factor the subprocess+timeout+stdin-pipe into a private `_run_pipe(*argv, stdin_bytes)` helper used by both, with the existing 12 s timeout (bump to 20 s for cold Tailscale paths).
- `collect_vitals` resolves `dest`: for `tailscale` transport use the **bare host** (`tailscale ssh nickv2026@fastclock` resolves via MagicDNS); for `openssh`, keep the addr_map/hostname behavior. So pass `host` (not the Tailscale IP) for tailscale-ssh.
- `VitalsPoller.__init__`: accept `ssh_transport="tailscale"` and set it on the client? No — the client owns it. Instead, ensure the app's `TailscaleClient()` uses the default `"tailscale"`. Add a `--openssh` escape hatch later if needed (not now).

- [ ] **Step 1 (test):** add `test_transport_tailscale_builds_tailscale_ssh_argv` — monkeypatch `_run_pipe` to capture argv; `TailscaleClient(); client.ssh_transport == "tailscale"`; `await collect_vitals("fastclock", USER_MAP)`; assert captured argv starts with `[binary, "ssh", "nickv2026@fastclock", "--", "sh", "-s"]`. Keep an `openssh` variant test asserting the `ssh -i` argv. Update the existing `_ssh_collect` monkeypatch test to the new structure.
- [ ] **Step 2–5:** fail → implement → green → full suite green → commit `feat(vitals): tailscale ssh transport (default) so all Pis report off-LAN`.
- [ ] **Step 6 (live, optional):** `uv run python -c "..."` collecting `dashboard-ink-bed` via tailscale-ssh; if it still hits a check-mode prompt, note that the ACL rule above must be applied. Don't block the task on it.

---

## Feature C — Out-of-band alerts (Telegram / Slack / ntfy)

**Secrets:** read from env, never hardcoded. Channels enabled when their env var is set:
- Telegram: `TAILTOP_TELEGRAM_TOKEN` + `TAILTOP_TELEGRAM_CHAT_ID`
- Slack: `TAILTOP_SLACK_WEBHOOK`
- ntfy: `TAILTOP_NTFY_TOPIC` (+ optional `TAILTOP_NTFY_SERVER`, default `https://ntfy.sh`)

### Task 18: notifier backends

**Files:** Create `tailtop/tailtop/data/notify.py`, `tailtop/tests/test_notify.py`.

```python
def enabled_channels(env: Mapping[str, str]) -> list[str]: ...   # which are configured
async def notify_all(message: str, env: Mapping[str, str], *, post=None) -> list[str]:
    # post: injectable async HTTP poster (url, json|data) for tests; defaults to urllib in a thread.
    # returns the list of channels notified.
```
Backends build the right request: Telegram `POST https://api.telegram.org/bot<token>/sendMessage {chat_id,text}`; Slack `POST <webhook> {text}`; ntfy `POST <server>/<topic>` body=message. Use stdlib `urllib.request` wrapped in `asyncio.to_thread` for the default poster (no new deps).

- [ ] **Step 1 (test):** `enabled_channels` reflects which env vars are set; `notify_all("hi", env, post=fake)` calls `fake` once per enabled channel with the right URL/payload, and returns those channel names; empty env → no calls, `[]`.
- [ ] **Step 2–5:** fail → implement → green → suite green → commit `feat(vitals): pluggable Telegram/Slack/ntfy notifier`.

### Task 19: `tailtop alert` subcommand + launchd plist

**Files:** Modify `tailtop/tailtop/app.py` (`main`); Create `tailtop/tailtop/com.weeeha.tailtop-alert.plist`; Modify `tailtop/tests/test_fleet_report.py` (or new `test_alert_cmd.py`).

- Add a pure `alert_message(vitals_by_id) -> str | None` to `fleet_report.py`: returns a one-line summary of only `warn`/`crit` hosts (reuse `Vitals.reasons`/`summarise_health`), or `None` when all clear.
- `main`: add `command` choice `"alert"` — runs one `VitalsPoller().collect_round()`, computes `alert_message`, and if non-empty calls `notify.notify_all(msg, os.environ)`; prints what it sent; exit 0. (No TUI.)
- Add a launchd plist (`StartInterval` 900 s) modeled on the repo's existing Affine plist style — runs `uv run tailtop alert` (or the installed entrypoint), logs to `~/Library/Logs/tailtop-alert.log`. Do NOT auto-install it; the README documents `launchctl load`.

- [ ] **Step 1 (test):** `alert_message` returns `None` for all-ok vitals and a string naming the host for a crit; (the env/notify path is covered by Task 18 — here just test the pure message + that the subcommand wiring calls notify when a message exists, via monkeypatch).
- [ ] **Step 2–5:** fail → implement → green → suite green → commit `feat(vitals): tailtop alert subcommand + launchd plist`.

---

## Feature D — Inventory export to INFRASTRUCTURE.md

### Task 20: `tailtop inventory` → markdown table

**Files:** Create `tailtop/tailtop/inventory.py`, `tailtop/tests/test_inventory.py`; Modify `tailtop/tailtop/app.py` (`main`).

- `render_inventory(vitals_by_id) -> str`: a markdown table — `| Host | Model | Serial | Cores | RAM | OS | Kernel | Disk |` from each `Vitals`' config fields, sorted by host.
- `update_markdown_file(path, table, marker="<!-- tailtop:inventory -->") -> None`: replace the block between `<marker>` and `<marker end>` (insert the markers + table if absent at EOF). Pure string transform + a file write; test the transform on a temp file.
- `main`: add `command` choice `"inventory"` with optional `--write PATH` (default: just print). Runs one collect round, prints the table; if `--write`, updates that file's marker block.

- [ ] **Step 1 (test):** `render_inventory` contains each host + its model/serial; `update_markdown_file` on a temp file inserts the table inside the markers and is idempotent (running twice yields the same content).
- [ ] **Step 2–5:** fail → implement → green → suite green → commit `feat(vitals): tailtop inventory export to markdown`.

---

## Done criteria (Phase 2)

- Full suite green; `uvx ruff check tailtop/` clean.
- Cockpit cards show a temp sparkline that survives a restart (SQLite-backed).
- `uv run tailtop` collects all 8 Pis via `tailscale ssh` once the ACL rule is applied (4 clocks already work; the other 4 start reporting).
- `TAILTOP_*` env set → `uv run tailtop alert` pushes a message on breach; launchd plist documented.
- `uv run tailtop inventory --write <INFRASTRUCTURE.md>` updates the device table.

## Notes / user actions required

1. **ACL rule** (Feature B) — apply the `action: accept` SSH rule above in the tailnet policy file, else `tailscale ssh` prompts for check-mode and unattended polling can't auth.
2. **Alert secrets** (Feature C) — export the `TAILTOP_*` env vars (or add them to the launchd plist's `EnvironmentVariables`) for the channels you want.
