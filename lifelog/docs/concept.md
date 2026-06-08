# Concept & Findings — wifi-life-log

**One line:** turn an existing Tailscale fleet of cheap devices (Raspberry Pis,
Orange Pis, ESP32s) into a *private, local* life-tracker — "where does my time
go?", answered by your own hardware, with nothing leaving the machine.

---

## 1. The vision

A fleet of always-on, privately-networked devices can sense the home through the
WiFi signals already filling it — presence, motion, breathing, no cameras, no
wearables — and fuse that with the devices already on the network to produce an
honest picture of daily life. Everything rides Tailscale (WireGuard) to a
collector **you own**, so it never touches a cloud. That privacy posture is the
differentiator over any commercial life-tracker.

---

## 2. Findings — what WiFi sensing can *really* do

### Two hardware limits cap everything
1. **Antennas (MIMO):** commodity Pi/ESP32 chips have **one** antenna → no
   angle-of-arrival → **no precise localization** from a single device.
2. **Bandwidth → range resolution:** 20 MHz ≈ 15 m, 80 MHz ≈ 3.75 m → a single
   link can't range a person to sub-meter. You compensate with **many cheap
   links** and by reading *change over time*, not absolute position.

### Capability vs. reality (Pi / ESP32-class hardware)
| Capability | Feasible? | Realistic precision |
|---|---|---|
| Presence / occupancy | ✅ easy, robust | room occupied y/n, count ±1 |
| Motion / activity zone | ✅ easy | "movement in living room" |
| Room-level location | ✅ | *which room* (1 sensor/room) |
| **Breathing rate** | ✅ **sweet spot** | ±1 breath/min when subject is **still** |
| Coarse gestures (trained, fixed spot) | ⚠️ demo-able | ~85–90%; doesn't transfer |
| Tile-level location (<1 m) | ⚠️ hard | ~1–2 m only with dense grid + fingerprinting |
| Heart **rate** | ⚠️ marginal | possible in ideal stillness; fragile |
| Heart **waveform**, fine gestures, pose-through-wall | ❌ | use 60 GHz mmWave for hearts |

### Why breathing works even though localization doesn't
They're **different measurements**. Localization resolves *position in space*
(needs antennas + bandwidth — we're weak). Breathing detects a tiny *periodic
change over time* (needs phase sensitivity + integration time — we're strong).
WiFi phase completes a full cycle every ~3 cm of chest travel, so 5–10 mm of
breathing is a clean phase swing; recording ~60 s and taking an FFT concentrates
that rhythm into **one sharp spectral peak** while noise spreads across the band.
The catch: it only works when the body is otherwise **still** (sleeping, sitting).

> **Diligence flags:** heart-rate-from-WiFi and through-wall pose are over-hyped —
> validate empirically before depending on them. For reliable hearts, use mmWave.

---

## 3. The concept — three fused layers

| Layer | Question | Source | Reliability |
|---|---|---|---|
| **L1 Location** | which room? | 1 WiFi sensor / room | room-level: high |
| **L2 Activity** | still / moving / breathing? | CSI motion + breathing DSP | medium–high |
| **L3 Context** | doing *what*? | network device state, smart plugs, door/PIR | very high |

**The reframe that makes it work:** WiFi gives *where* + *how active*; the
**labels** ("gaming", "cooking", "sleeping") come mostly from **device context**.
"Gaming" isn't inferred from your body — it's that the **PlayStation is powered
on**. The fleet/tailnet makes this L3 layer the superpower.

### What's realistically trackable
Time per room (the spine) · sleep (in-bed + still + breathing) · bathroom
visits · gaming/TV/working (device state) · cooking (kitchen + a $2 fridge reed
switch or smart plug). **Patterns minable:** circadian routine, sleep analytics
(duration, awakenings, restlessness), sedentary ratio, focus vs. distraction,
doomscroll-in-bed, meal rhythm, bathroom frequency, anomaly vs. baseline.

---

## 4. Architecture (summary — full version in [`design.md`](design.md))

```
EDGE (sensor nodes)                  FUSION ("brain" node)            UI
  ESP32-CSI / Pi-Nexmon  ─feat─┐
  Pi RSSI scanner        ─feat─┼─MQTT─►  fusion service              report / TUI
  Pi + reed/PIR/plug     ─ctx──┤          • localization engine
  network device probes  ─ctx──┘          • activity state machine
                                          • SQLite timeline + rollups
        \________________ all links ride Tailscale ________________/
```

Design rules that held up: **extract features at the edge** (never ship raw CSI);
**rule-based state machine before ML** (explainable, and it generates the labels
you later train on); **lean on L3 device context**; **privacy is a feature**.

---

## 5. Re-use — RuView

[RuView](https://github.com/ruvnet/RuView) (MIT) already solves the hard bottom
layer: ESP32-S3/C6 CSI firmware + DSP for breathing/presence/motion over MQTT.
It is **RF-only** — no device-context fusion, no time-tracking, no activity
labeling, no Tailscale — so the two compose:

- **Re-use:** ESP32 firmware, breathing/presence DSP, MQTT semantic states,
  per-room calibration, HA-discovery topic convention.
- **Keep here:** L3 device-context fusion, the timeline, activity labeling,
  sleep analytics, Tailscale transport, the CLI.
- **Net:** RuView **deletes the "build our own sensor agent" phase** —
  `RuViewBridge` bridges its MQTT into this pipeline; our breathing DSP stays as
  a zero-dependency fallback. Validate RuView's heart-rate/pose claims first.

---

## 6. What's built (Phases 0–3 + RuView)

| Phase | Deliverable | State |
|---|---|---|
| 1 Presence MVP | room + dwell timeline | ✅ |
| 2 Context fusion | device/plug collectors → activity labels | ✅ |
| 3 Sleep + breathing | breathing DSP + sleep card | ✅ |
| RuView bridge | adopt RuView as the edge layer | ✅ |
| 4 Localization refine | RSSI fingerprint + reed/PIR sub-room zones | ⬜ |
| 5 Analytics + ML | rollups, baselines, anomaly alerts, self-trained classifier | ⬜ |
| — Hardware | flash RuView ESP32-S3 nodes; bedside breathing node | ⬜ |

The breathing DSP recovers known rates exactly and rejects the empty bed (40/40
seed sweep); a sleep card reports asleep/efficiency/awakenings/restlessness/avg
bpm; the rule engine labels gaming/working/cooking from device context.

---

## 7. Open decisions & risks

- **Hardware:** a few ESP32-S3 (RuView CSI, ~$9 each) + optional 60 GHz mmWave for
  reliable hearts.
- **Multi-person:** WiFi sensing assumes ~1 person/zone; degrade gracefully.
- **Drift/calibration:** fingerprints decay → anchor with device-truth, recalibrate.
- **Privacy:** intimate data — keep local, consider at-rest encryption.
