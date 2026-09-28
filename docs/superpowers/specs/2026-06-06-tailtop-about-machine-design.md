# tailtop — "About this machine" screen — Design Spec

**Status:** Approved direction (brainstorm complete)
**Date:** 2026-06-06
**Owner:** nickv
**Parent spec:** [`2026-06-05-tailtop-tui-design.md`](2026-06-05-tailtop-tui-design.md)

---

## 1. Summary

Add an **"About this machine"** screen to `tailtop`: a modal that shows a photo
of the actual hardware running the app (the self-built Raspberry Pi clock)
rendered at the highest fidelity the terminal supports, alongside this node's
host and tailnet facts.

The photo is rendered with the [`textual-image`](https://pypi.org/project/textual-image/)
widget, which uses the **kitty / iTerm graphics protocol or Sixel for true
pixels** where available and falls back to Unicode half-blocks elsewhere. The
screen doubles as the project's first real "about/help" surface — today `?` is
only a transient toast.

This is a focused addition to the existing app (one screen, one widget, one key
binding, one dependency); it does not touch the data layer.

## 2. Goals

- Show the device's true-pixel photo in capable terminals (the user runs
  `kitty`), degrading gracefully in lesser terminals.
- Surface this node's identity at a glance: host basics + tailnet context.
- Reinforce `tailtop`'s "strong visual identity" goal from the parent spec.
- Reuse the existing `Status`/`self_peer` model — **no data-layer changes**.
- Work in `--demo` mode (synthetic tailnet) as well as live.

## 3. Non-Goals

- **Not** a per-peer photo system. Exactly one baked-in device image for the
  local machine. (A generic "any peer can have an image" feature is out of scope —
  YAGNI.)
- **Not** a configurable settings surface. The caption is a module constant in
  v1, not a config file.
- **Not** a replacement for the boot splash; the splash stays as-is.
- **No** runtime image processing — the asset is pre-sized at author time.

## 4. Placement & Open Mechanism

- New `AboutScreen(ModalScreen[None])` lives in `tailtop/screens.py`, beside the
  existing `ConfirmScreen` / `ResultScreen` / `InputScreen`.
- **Open:** the `A` key (Shift-A). All lowercase letters are peer verbs
  (`p c w n e f s r`); `A` is free and reads as a global view-action, like `?`.
  Also added as a command-palette entry: *"about this machine"*.
- **Dismiss:** `escape` / `enter` / `q`, matching `ResultScreen`.
- The `action_help` toast string gains `A about`.

## 5. Screen Layout

Centered modal dialog. Border title = the machine's hostname. Stacked vertical:

```
┌─ tinyclock ───────────────────────────────┐
│            ▓▓ device photo ▓▓              │  ← textual-image Image widget
│           (true pixels in kitty)           │
│          tinyclock · Raspberry Pi          │  ← custom caption (dim/italic)
│  ────────────────────────────────────────  │
│  Host                 Tailnet               │
│   OS         linux     tailnet   …​.ts.net   │
│   Tailscale  1.80.0    account   you@…      │
│   IPv4       100.x.y.z exit node  none      │
│   IPv6       fd7a:…     peers     6 / 9 up  │
│   MagicDNS   tinyclock.…​.ts.net             │
│               esc to close                  │
└─────────────────────────────────────────────┘
```

The info area is two side-by-side definition lists ("Host" and "Tailnet")
rendered as a single Rich `Table.grid`, consistent with how `DeviceCard` builds
Rich renderables today.

## 6. Components & Boundaries

### `tailtop/widgets/device_image.py` — `DevicePortrait`
- **Purpose:** render the device photo + caption as one unit.
- **API:** `DevicePortrait(asset_path: Path, caption: str)`.
- **Composition:** yields a `textual_image.widget.Image(asset_path)` followed by
  a dim/italic `Static(caption)`.
- **Degradation:** if `asset_path` does not exist, yield a bordered text
  placeholder (`"device photo unavailable"`) instead of the image — never raise.
- **Dependencies:** `textual-image`. No CLI, no app state. Independently testable.

### `tailtop/screens.py` — `AboutScreen(ModalScreen[None])`
- **API:** `AboutScreen(status: Status | None, *, caption: str = DEVICE_CAPTION,
  asset_path: Path)`.
- **Composition:** a `#dialog` `Vertical` containing `DevicePortrait`, a rule, the
  info `Static`, and an `esc to close` hint. `border_title` = `status.self_peer.host_name`
  (or `"this machine"` when `status is None`).
- **Behavior:** pure formatting of the passed-in `Status`; no CLI, no polling.
  A private helper builds the two-column Rich renderable from `status`.
- **Bindings:** `escape` / `enter` / `q` → `dismiss(None)`.

### `tailtop/app.py` — wiring
- `Binding("A", "about", "About")` added to `BINDINGS`.
- `ASSETS = Path(__file__).parent / "assets"` (mirrors the existing `_THEMES`
  pattern); `DEVICE_ASSET = ASSETS / "device.jpg"`.
- `def action_about(self) -> None: self.push_screen(AboutScreen(self.status, asset_path=DEVICE_ASSET))`.
- One row added to `palette_entries()`:
  `("about this machine", self.action_about, "Host & tailnet info + device photo")`.
- `action_help` toast updated to include `A about`.

## 7. Data Mapping

All read from the existing reactive `self.status` (`Status`); nothing new parsed.

| Screen line | Source |
|-------------|--------|
| Title / hostname | `status.self_peer.host_name` |
| OS | `status.self_peer.os` |
| Tailscale version | `status.version` |
| IPv4 | `status.self_peer.ipv4` |
| IPv6 | `status.self_peer.ipv6` |
| MagicDNS name | `status.self_peer.magic_dns` |
| Tailnet | `status.magic_dns_suffix` |
| Account | `status.user_display` |
| Exit node | `self_peer.exit_node_option` → *"advertising"*; else a peer with `exit_node` → *"using &lt;name&gt;"*; else *"none"* |
| Peers | `f"{status.online_count} / {status.total_count} up"` |

Caption: `DEVICE_CAPTION = "tinyclock · Raspberry Pi"` (module constant; trivially editable).

## 8. Rendering & Fallback

- `textual-image` auto-detects the terminal and selects, in order: kitty graphics
  protocol → iTerm protocol → Sixel → Unicode half-block fallback.
- In the user's `kitty`: true-pixel photo. In other truecolor terminals:
  half-blocks. In macOS Terminal.app: half-blocks degrade to 256-color (acceptable;
  a hand-drawn-Pi fallback is a noted future upgrade, not in v1).
- The widget boundary keeps the renderer swappable — a future hybrid fallback is a
  drop-in replacement of `DevicePortrait` internals.

## 9. Assets & Packaging

- New asset `tailtop/assets/device.jpg`: the side-view ("guts") photo, downscaled
  at author time to ≤ ~1000 px on the long edge, JPEG quality ~85, to keep the
  wheel small. Source: `tailtop/scratch/pi_side.jpg`.
- Packaging: the build backend is `hatchling` with `packages = ["tailtop"]`. Add
  `artifacts = ["tailtop/assets/*"]` under `[tool.hatch.build.targets.wheel]` so
  the non-Python asset is guaranteed into the wheel.

## 10. Dependencies

- Add `textual-image` to `[project].dependencies`. Pin a range compatible with
  `textual>=1.0,<2.0` (verify the installed `textual-image` resolves against
  Textual 1.x during implementation; adjust the bound if needed).
- `Pillow` arrives transitively via `textual-image`. It is **not** a declared
  runtime dependency for our code; the one-time asset downscale uses Pillow as an
  author-time tool only.

## 11. Edge Cases & States

- **`status is None`** (before first poll): every value renders as `—`; title is
  `"this machine"`; the photo still renders.
- **Disconnected / logged out** (`backend_state != "Running"`): host basics shown
  where known; the Tailnet column reflects the state honestly (e.g. account/tailnet
  may be `—`).
- **Asset missing:** `DevicePortrait` shows its text placeholder; the screen still
  opens with all info.
- **Open while a modal is up:** `A` is a global binding; pressing it over another
  modal is a no-op by Textual's normal screen-stack behavior (not specially handled).

## 12. Testing

Follows the existing pattern (`tests/test_splash.py`): async `app.run_test()`
pilots + unit asserts. No snapshot harness is introduced.

`tests/test_about.py`:
- **Unit — info formatting:** build the info renderable from the `status.json`
  fixture; assert it contains the hostname, version, and IPv4. Build it from
  `None`; assert `—` placeholders.
- **Pilot — open/close:** `TailtopApp(auto_poll=False)`, feed a status via
  `app._on_status(status)`, `press("A")`, assert `isinstance(app.screen, AboutScreen)`;
  `press("escape")`, assert it closed.
- **Widget — `DevicePortrait`:** mounts with the real asset path; with a bogus path
  shows the placeholder. (Headless `run_test` exercises `textual-image`'s fallback
  renderer — assert structure/text, not pixels.)

## 13. Files Touched

**New**
- `tailtop/tailtop/widgets/device_image.py` — `DevicePortrait`
- `tailtop/tailtop/assets/device.jpg` — downscaled side-view photo
- `tailtop/tests/test_about.py`

**Modified**
- `tailtop/tailtop/screens.py` — add `AboutScreen` + `DEVICE_CAPTION`
- `tailtop/tailtop/app.py` — `A` binding, `action_about`, `ASSETS`/`DEVICE_ASSET`,
  palette entry, help toast
- `tailtop/pyproject.toml` — `textual-image` dependency + wheel `artifacts`

## 14. Open Questions

None blocking. A classier "hand-drawn Pi" fallback for non-truecolor terminals is
deferred to a future iteration; the `DevicePortrait` boundary makes it additive.
