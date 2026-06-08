# Concept & Findings — Private WiFi Sensing on a Device Fleet

**One line:** turn an existing Tailscale fleet of cheap devices (Raspberry Pis,
Orange Pis, ESP32s) into a *private, local* spatial-sensing + life-tracking
system — "where does my time go?", answered by your own hardware, with nothing
leaving the machine.

*Status: concept validated; three sub-projects built and tested **in the fork
branch (PR #6)** — not yet extracted to their own repos. June 2026.*

---

## 1. The vision

A fleet of always-on, privately-networked devices can sense the home through the
WiFi signals already filling it — detecting presence, motion, and breathing with
no cameras and no wearables — and fuse that with the devices already on the
network to produce an honest, private picture of daily life. Because everything
rides Tailscale (WireGuard) to a collector *you* own, it never touches a cloud.
That privacy posture is the differentiator over any commercial life-tracker.

---

## 2. Ideas explored (and the verdicts)

| Idea | Verdict | Notes |
|------|---------|-------|
| **WiFi presence radar** — is anyone in the room? | ✅ **Lead idea** | Robust at room level; the showpiece is breathing sensing |
| **Time-tracking life-log** — where does my time go? | ✅ **Chosen project** | Presence + device-context fusion → a daily timeline |
| **3D-printer / device control over the tailnet** | ✅ Strong, separate | Print-from-anywhere, camera failure-detection, "physical notifications" gag |
| **Security-camera mesh** | ✅ Viable | Frigate-style local recording; fuse with WiFi to cut false alerts |
| **Ambient physical fleet dashboard** | 🟡 Nice add-on | e-ink/LED matrix showing fleet + occupancy |
| **Distributed compute / render farm** | 🟡 Quietly useful | Less flashy; idle-node worker pool |

The **WiFi life-tracker** became the focus: most novel, leans hardest on the
fleet, and has the longest interesting roadmap.

---

## 3. Findings — what WiFi sensing can *really* do

### Two hardware limits cap everything
1. **Antennas (MIMO):** commodity Pi/ESP32 chips have **one** antenna → essentially
   no angle-of-arrival → **no precise localization** from a single device.
2. **Bandwidth → range resolution (`c/2B`):** 20 MHz ≈ 7.5 m, 80 MHz ≈ 1.9 m → a
   single link still can't range a person to sub-meter. You compensate with **many
   cheap links** and by reading *change over time*, not absolute position.

### Capability vs. reality (on Pi / ESP32-class hardware)
| Capability | Feasible? | Realistic precision |
|---|---|---|
| Presence / occupancy | ✅ easy, robust | room occupied y/n, rough count ±1 |
| Motion / activity zone | ✅ easy | "movement in living room" |
| Room-level location | ✅ | *which room* (1 sensor/room) |
| **Breathing rate** | ✅ **sweet spot** | ±1 breath/min when subject is **still** |
| Coarse gestures (trained, fixed spot) | ⚠️ demo-able | ~85–90% on a small set; doesn't transfer |
| Tile-level location (<1 m) | ⚠️ hard | ~1–2 m only with dense grid + fingerprinting |
| Heart **rate** | ⚠️ marginal | possible in ideal stillness; fragile |
| Heart **waveform**, fine gestures, pose-through-wall | ❌ | use mmWave radar for hearts |

### The key insight: localization vs. breathing are *different measurements*
- **Localization** = resolve absolute **position in space** → needs antennas +
  bandwidth (we're weak here).
- **Breathing** = detect a tiny **periodic change over time** → needs phase
  sensitivity + integration time (we're strong here).

WiFi *phase* completes a full cycle every ~3 cm of chest travel (5 GHz, round
trip), so 5–10 mm of breathing is a large, clean phase swing. Recording ~60 s
and taking an FFT concentrates that rhythm into **one sharp spectral peak** while
noise spreads across the band — which is why a mm-scale motion is recoverable
even though absolute position isn't. The catch: it only works when the rest of
the body is **still** (sleeping, sitting).

### What "the data" actually is
Per packet from a CSI-capable node: a **CSI matrix** of complex values
(amplitude + phase) per subcarrier × antenna, plus RSSI/timestamp. ESP32 ≈ 64
values (1 antenna, 20 MHz); Pi 4 + Nexmon-CSI ≈ 256 subcarriers at 80 MHz.
Everything downstream (presence, breathing, gesture) is DSP on the **time series**
of that matrix.

> **Diligence flags:** heart-rate-from-WiFi and through-wall pose are the
> over-hyped claims — validate empirically before depending on them. For reliable
> hearts, use a **60 GHz mmWave** module.

---

## 4. The chosen project — "Lifelog"

A passive, private time-tracker that answers *where does my time go* by fusing
three layers:

| Layer | Question | Source | Reliability |
|---|---|---|---|
| **L1 Location** | which room? | 1 WiFi sensor / room | room-level: high |
| **L2 Activity** | still / moving / breathing? | CSI motion + breathing DSP | medium–high |
| **L3 Context** | doing *what*? | network device state, smart plugs, door/PIR | very high |

**The reframe that makes it work:** WiFi tells you *where* + *how active*; the
**labels** ("gaming", "cooking", "sleeping") come mostly from **device context**.
"Gaming" isn't inferred from your body — it's that the **PlayStation is powered
on** (a near-100% signal). The fleet/tailnet makes this L3 layer the superpower.

**What CSI is actually for:** follow that logic and L3 device-context plus a $2
PIR/reed switch already deliver most of L1 (*which room*) and nearly all the
activity labels. CSI's *unique* contribution is the one thing cheap sensors can't
do — **breathing/sleep**. So treat WiFi-CSI not as the foundation but as **one
premium bedroom sensor**: buy it for sleep, use cheap sensors elsewhere.

**Who it's for:** WiFi sensing assumes ~1 person per zone, so the honest target is
a **single-occupant home** (or per-room-single-occupant). Multi-person households
degrade to presence-only — design for that, don't pretend otherwise.

### What's realistically trackable
- **Time per room** (the spine) · **sleep** (in-bed + still + breathing) ·
  **bathroom** visits/duration · **gaming/TV/working** (device state) ·
  **cooking** (kitchen + a $2 fridge reed switch or smart plug)
- **Patterns minable:** routine/circadian map, sleep analytics (duration,
  awakenings, restlessness), sedentary ratio, focus vs. distraction,
  doomscroll-in-bed, meal rhythm, bathroom frequency, anomaly vs. baseline.
- **"Near the fridge" reality:** WiFi gives you the *kitchen*; a cheap sensor
  (reed switch / plug / PIR) beats trying to fingerprint sub-room zones with CSI.

---

## 5. Architecture (summary)

```
EDGE (sensor nodes)                  FUSION ("brain" node)            UI
  ESP32-CSI / Pi-Nexmon  ─feat─┐
  Pi RSSI scanner        ─feat─┼─MQTT─►  fusion service              report / TUI
  Pi + reed/PIR/plug     ─ctx──┤          • localization engine      (tailtop-style)
  network device probes  ─ctx──┘          • activity state machine
                                          • SQLite timeline + rollups
        \________________ all links ride Tailscale ________________/
```

**Design rules that held up in implementation:**
- **Extract features at the edge** — never ship raw CSI over the network
  (bandwidth + privacy).
- **MQTT** transport; **SQLite** timeline (upgrade later only if needed).
- **Rule-based state machine before ML** — explainable now, and it *generates the
  labels* you later train a classifier on.
- **Lean on L3 device context** wherever it exists.
- **Privacy is a feature** — 100% local, Tailscale-only.

---

## 6. Re-use finding — RuView

[RuView](https://github.com/ruvnet/RuView) (MIT) is a mature WiFi-CSI platform
that already solves the hard bottom layer: ESP32-S3/C6 firmware + DSP/ML for
breathing/presence/motion (and heart-rate/pose/fall), published over MQTT. It is
**RF-only** — no device-context fusion, no time-tracking, no activity labeling,
no Tailscale. So the two **compose perfectly**:

- **Re-use from RuView:** ESP32 firmware, breathing/presence DSP, MQTT semantic
  states, per-room calibration, HA-discovery topic convention.
- **Keep ours:** L3 device-context fusion, the time-tracking timeline, activity
  labeling, sleep *analytics*, Tailscale transport, the CLI/TUI.
- **Net effect:** RuView **deletes the "build our own sensor agent" phase**. We
  bridge its MQTT output into our pipeline (`RuViewBridge`) and keep our own
  breathing DSP as a zero-dependency fallback.
- **Validate before depending:** RuView's heart-rate / pose-through-wall claims.

---

## 7. What's been built

Three **separate, runnable** sub-projects, each stub-first so they run on any
machine with no hardware. All three currently live in the **fork branch (PR #6)** —
none has been extracted yet, so `weeeha/wifi-life-log` is still empty:

| Project | Type | What it does | Tests |
|---|---|---|---|
| **`lifelog/`** | service + CLI | Full pipeline (agent→bus→fusion→SQLite→report); Phase 1 presence, Phase 2 device-context collectors, Phase 3 breathing DSP + sleep analytics, RuView bridge | 33 ✅ |
| **`tailtop/`** | TUI | "htop for your tailnet" — live, interactive cockpit (3 modes) | existing |
| **`tailsnap/`** | CLI | print-and-exit tailnet readouts: status table, health line, topology tree, traffic bars | 12 ✅ |
| `scripts/fleet-capability-probe.sh` | tool | per-node inventory (CSI/monitor-mode, camera, serial, GPIO, Tailscale) | — |

**`lifelog` highlights:** breathing DSP recovers known rates to **within ±1 bpm**
and rejects the empty bed (a 5-rate parametrized test — *not yet swept across many
seeds or validated on real CSI*); a sleep card reports asleep/efficiency/
awakenings/restlessness/avg-bpm; rule engine labels gaming/working/cooking from
device context; `RuViewBridge` turns RuView MQTT vitals into our events
(verified on simulated input: RuView bedroom vitals → fusion `SLEEPING`).

---

## 8. Repo structure & decisions

- The work lives in a **fork of `tailscale/tailscale`** used as a scratchpad — a
  poor permanent home for original projects (carries the whole Go codebase, CI,
  license).
- **Decision:** extract the projects into their own repos. `lifelog` is the
  strongest candidate (distinct domain, longest roadmap, zero coupling);
  `tailtop`/`tailsnap` are tailnet-tool siblings.
- Targets created: **`weeeha/wifi-life-log`** (lifelog), **`weeeha/tailtop`**.
  Extraction is history-preserving via `git subtree split`
  (`scripts/extract-subprojects.sh`).
- **Status:** the extract script now splits `lifelog/`, `tailtop/`, and `tailsnap/`,
  and lifelog's docs travel via `lifelog/docs/`. `lifelog` and `tailsnap` are now
  licensed **MIT** (were BSD-3 by inheritance from tailscale). Still to do: create
  the `tailsnap` repo and run the script locally to populate the target repos.

---

## 9. Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 0 Inventory | capability probe across fleet | ✅ shipped |
| 1 Presence MVP | room + dwell timeline | ✅ |
| 2 Context fusion | device/plug collectors → activity labels | ✅ |
| 3 Sleep + breathing | breathing DSP + sleep card | ✅ |
| RuView bridge | adopt RuView as the edge layer | ✅ |
| 4 Localization refine | RSSI fingerprint + reed/PIR sub-room zones | ⬜ |
| 5 Analytics + ML | daily rollups, baselines, anomaly alerts, self-trained classifier | ⬜ |
| — Validate | breathing/sleep vs. a chest-strap or pulse-ox over several nights | ⬜ |
| — Hardware | flash RuView ESP32-S3 nodes; bedside breathing node | ⬜ |

> ✅ = software-complete and passing tests **against the simulator**; none is yet
> validated on real CSI hardware.

---

## 10. Open decisions & risks

- **Hardware buy:** a few ESP32-S3 (RuView CSI, ~$9 each) + optional 60 GHz mmWave
  for reliable hearts.
- **Multi-person:** WiFi sensing assumes ~1 person/zone; degrade gracefully.
- **Drift/calibration:** fingerprints decay → anchor with device-truth, recalibrate.
- **`tailsnap` home:** own repo, fold into the `tailtop` repo (siblings), or keep
  in the playground — undecided.
- **Privacy/security:** intimate, **health-adjacent** data — keep it local, mind
  who else is on the tailnet, and add at-rest encryption (a requirement, not a "maybe").

---

*Companion docs: `notes/lifelog-wifi-sensing-design.md` (full system design),
`lifelog/README.md`, `tailsnap/README.md`, `tailtop/README.md`.*
