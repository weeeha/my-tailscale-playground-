# tailtop — Icon Language

A small, fixed vocabulary of glyphs the app uses to communicate state. The
goal is **one visual grammar across every scale** — the same family reads
whether it's the global pill at the top of the shell or a per-peer column in
Cockpit's device list. The eye learns it once.

Colors below are **semantic slots**, not hex. Each theme (Studio, Mission
Control, Brutalist) maps them to its own palette in `themes/*.tcss`.

---

## 1. Global Status Pill

Lives in the top-left of the app shell (`widgets/status_bar.py`). Answers the
first question the user opens tailtop to answer: *am I connected?*

Render shape — half-block caps + 24-bit background block approximate a
rounded pill in modern terminals:

```
▐ ● Connected ▌
```

Legacy fallback (no truecolor / no half-block support):

```
[ ● Connected ]
```

The seven canonical states:

| Glyph | Label          | Color slot   | Meaning                              |
|-------|----------------|--------------|--------------------------------------|
| `●`   | Connected      | `ok`         | Direct path to tailnet, all good     |
| `◐`   | Relayed        | `warn`       | Online via DERP — working, slower    |
| `✷`*  | Connecting…    | `pending`    | Handshaking with control plane       |
| `↗`   | Exit node      | `info`       | Routing through an exit node         |
| `⚠`   | Sign in        | `attention`  | Key expired / reauth required        |
| `○`   | Disconnected   | `muted`      | `tailscaled` stopped intentionally   |
| `✕`   | Offline        | `error`      | No internet path to control plane    |

*Connecting* is the only animated state — see `Loaders` below.

Optional secondary line when connected: append peer count after a middle dot:

```
▐ ● Connected · 12 peers ▌
```

Gives the pill a heartbeat without adding chrome.

---

## 2. Peer Status Glyphs

Same glyph family as the pill, used in lists/tables (Cockpit device list,
Observatory grid). Single-glyph form, no label, no pill background — they
share an x-height so a column of peers scans cleanly.

| Glyph | Peer state                                 |
|-------|--------------------------------------------|
| `●`   | Online, direct path                        |
| `◐`   | Online, relayed via DERP                   |
| `◌`   | Idle / no recent traffic                   |
| `○`   | Offline / unreachable                      |
| `⚠`   | Key expired / needs reauth                 |

Latency adjunct (optional second column) — signal-strength bars:

```
▁ ▂ ▃ ▄ ▅      ← rising = better
```

Example row:

```
●  ▅   nick-laptop      100.64.2.13     2ms     ─
◐  ▂   ams-relay        100.64.7.4      87ms    DERP fra
○      old-phone        100.64.3.9      —       expired 14d ago
```

---

## 3. Loaders (Animated)

### 3.1 Primary — Braille spinner (round)

The canonical "working" indicator. Smooth at 80ms/frame because Braille
packs 8 dots into a 2×4 grid — sub-character motion without width jitter.
Width-stable across frames (always 1 cell), so safe in tables.

```
⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏
```

Use for: pulling `tailscale status`, ping-in-flight, command execution,
generic data refresh.

### 3.2 Variant — Braille spinner (bold)

Heavier 8-frame spin. Reads "doing more work." Use sparingly — when the
operation is meaningfully heavier than a refresh (e.g. running `netcheck`,
bringing the tailnet up).

```
⣾ ⣽ ⣻ ⢿ ⡿ ⣟ ⣯ ⣷
```

### 3.3 Connecting (pill) — sparkle pulse

For the global pill's `Connecting…` state only. Shimmering matches the
"reaching out into the network" feel; pairs with amber color slot.

```
✶ ✷ ✸ ✹ ✺ ✹ ✸ ✷    (~120ms/frame)
```

---

## 4. Reserved / Future Use

Saved for later — known-good glyphs without a committed home yet. Reach
for these first before introducing new ones; consistency beats novelty.

### 4.1 Dotted progress bar

```
▰▰▰▰▱▱▱▱
```

Likely fit: discrete-step progress where the count matters more than the
percentage (e.g. "syncing 4/8 routes", onboarding step indicator).

### 4.2 Square progress bar

```
[■■■■■□□□□] 50%
```

Likely fit: bounded operations with a known total where a percentage adds
clarity (e.g. file transfer via Taildrop, bulk action progress).

### 4.3 Other reserve glyphs

Held in reserve without a use case yet — document the intent here before
using, so we don't drift the language.

- `◜ ◝ ◞ ◟` — arc rotation (potential alt loader, lighter feel than Braille)
- `✦ ✧` — diamond twinkle (potential "new"/"unseen" marker)
- `↔ ⇄ ↮ ⇎` — connection states (potential subnet/route relationship glyphs)
- `▁ ▂ ▃ ▄ ▅ ▆ ▇ █` — width-grow (potential inline meter for live values)

---

## 5. Rules of the Language

1. **One family, all scales.** A glyph used for global state means the same
   thing at the peer scale. Don't introduce a new glyph if an existing one
   already carries the meaning.
2. **Motion = meaning.** Animate only when something is actually happening.
   Steady states get steady glyphs. Avoid decorative animation; it teaches
   the user to ignore motion.
3. **Width-stable frames.** Spinners must occupy the same cell width every
   frame. No mixing single-width and emoji glyphs in the same animation.
4. **Color is theme-owned.** Reference the semantic slot
   (`ok`, `warn`, `pending`, `info`, `attention`, `muted`, `error`), never
   a hex. Themes resolve it.
5. **Fallback gracefully.** Pill, half-block caps, and 24-bit background
   are aspirational. Always provide a `[ glyph label ]` fallback for
   terminals without truecolor support.
6. **Reserve before reuse.** Before adding any new glyph to the codebase,
   check section 4. If it's not in this doc, it doesn't ship.

---

## 6. Implementation Pointers

- Pill rendering — `tailtop/tailtop/widgets/status_bar.py`
- Peer glyphs — `tailtop/tailtop/widgets/device_list.py`, `device_card.py`
- Loaders — Textual has a built-in `LoadingIndicator`; for the Braille
  spinner specifically, drive frames from the global poller tick so all
  spinners in the UI stay phase-aligned.
- Color slots — define once in each theme's `.tcss` file; widgets reference
  CSS classes, never literal colors.
