# Lifelog: a private, local WiFi-sensing time-tracker

Design + implementation plan for a passive "where does my time go" system built on
the device fleet (Raspberry Pis, Orange Pis, ESP32s) and the Tailscale mesh.

> **Thesis:** WiFi sensing answers **where** you are and **how active** you are.
> The **labels** ("gaming", "cooking", "sleeping") come from fusing that with
> **device/appliance context**. Everything stays local — reported over Tailscale
> (WireGuard) to a collector you own. No cloud, no account, no vendor.

---

## 1. Layered model

The system is three signal layers fused into one timeline:

| Layer | Question it answers | Source | Reliability |
|-------|--------------------|--------|-------------|
| **L1 Location** | Which room? | 1 WiFi sensor / room (CSI or RSSI motion) | room-level: high |
| **L2 Activity** | Still / moving / how vigorously? | CSI motion variance, breathing | medium–high |
| **L3 Context** | Doing *what*? | network device state, smart plugs, door/PIR sensors | very high |

Rule of thumb: **lean on L3 wherever it exists** (PlayStation power state beats
guessing "gaming" from a body). Use L1/L2 to fill the gaps and to catch activities
that have no device (sleeping, toilet, pacing).

---

## 2. Architecture

```
   EDGE (sensor nodes)                 FUSION (one "brain" node)        UI
 ┌─────────────────────┐
 │ ESP32-CSI  (bedroom)│─CSI→feat─┐
 ├─────────────────────┤          │   ┌──────────────────────────┐   ┌────────────┐
 │ Pi/Nexmon-CSI (room)│─feat─────┼──►│ MQTT broker (mosquitto)  │   │ tailtop    │
 ├─────────────────────┤          │   │        │                 │   │ "Lifelog"  │
 │ Pi RSSI scanner     │─feat─────┤   │        ▼                 │   │  mode      │
 ├─────────────────────┤          │   │ fusion service (python)  │──►│ (Textual)  │
 │ Pi + reed/PIR/plug  │─context──┤   │  • localization engine   │   └────────────┘
 └─────────────────────┘          │   │  • activity state machine│   ┌────────────┐
   network probes:                │   │  • timeline writer       │   │ web dash   │
 ┌─────────────────────┐          │   │        │                 │   │ (TS Serve) │
 │ PlayStation / TV /PC│─context──┘   │        ▼                 │   └────────────┘
 │ state (tailnet/LAN) │              │ SQLite timeline + rollups│
 └─────────────────────┘              └──────────────────────────┘
            \________________ all links ride Tailscale ________________/
```

### Design rules
- **Extract features at the edge.** Never ship raw CSI across the network — it's
  huge and intimate. Each node turns raw frames into compact events
  (`{motion: 0.42, breathing_bpm: 14, rssi_fp: [...]}`) and publishes *those*.
- **MQTT for transport.** One `mosquitto` broker on the brain node; every sensor
  connects to it over its Tailscale IP. Pub/sub + retained "last state" fits a
  many-sensors topology better than HTTP polling.
- **SQLite first.** A personal-scale timeline fits in SQLite; upgrade to
  TimescaleDB only if/when rollups get slow.
- **Rule-based before ML.** Start with an explainable state machine. Collect
  labeled data via the UI, *then* train a classifier on your own ground truth.

---

## 3. Sensor node types

| Node | Hardware | Role | Notes |
|------|----------|------|-------|
| **Breathing/sleep** | ESP32 (CSI) or Pi 4 + Nexmon-CSI | bed presence + breaths/min | needs subject ~still; perfect for bedroom |
| **Room presence** | any Pi/Orange Pi with monitor-mode WiFi | motion + RSSI fingerprint | one per tracked room |
| **RSSI-only** | any node, no CSI | coarse occupancy + device counting | fallback when chipset can't CSI |
| **Context/GPIO** | Pi with GPIO | reed switch (fridge), PIR (kitchen zone), smart-plug poller | the "ground truth" anchors |

> A **fleet capability probe** (a small read-only script that reports each node's
> CSI/monitor-mode support, cameras, serial devices, GPIO, and Tailscale status)
> tells you which nodes can do CSI vs. RSSI-only. **Run it first** — it decides
> which node plays which role above.

---

## 4. Data model (SQLite)

```sql
-- raw-ish, high frequency, short retention (TTL e.g. 7d)
sensor_event(ts, node_id, kind, features_json)

-- fused state, ~1 Hz or on-change: the spine
state_sample(ts, room, activity, motion, confidence)

-- contiguous blocks derived from state_sample: what you actually query
segment(id, start_ts, end_ts, room, activity, duration_s, attrs_json)

-- nightly rollups
daily_summary(date, totals_json, sleep_start, sleep_end,
              sleep_quality, sedentary_min, anomalies_json)
```

"Where did my time go today?" = `SELECT activity, SUM(duration_s) FROM segment
WHERE date(start_ts)=? GROUP BY activity`.

---

## 5. Signal-processing chains

**Presence / motion (per node, ~10 Hz):**
```
CSI/RSSI frames → amplitude per subcarrier → sliding-window variance
  → normalize → motion ∈ [0,1] → threshold → occupied? + intensity
```

**Breathing (per node, needs stillness):**
```
CSI → pick stable subcarriers → phase sanitization (remove CFO/SFO drift)
  → bandpass 0.1–0.5 Hz → 30–60 s window → FFT → peak in 0.1–0.5 Hz
  → breaths/min + peak-prominence = confidence
```
The breathing peak survives because it's *periodic* — integrating over a minute
concentrates it at one frequency while noise spreads across all. (This is why
breathing is detectable even though absolute localization isn't: it's a
*temporal/periodic* measurement, not a *spatial* one.)

**Localization (fusion):**
```
per-room {motion, breathing-present, rssi_fp} → argmax room by motion/breath energy
  → (optional) RSSI fingerprint kNN for sub-room zones (fridge vs stove)
```

**Activity (fusion state machine, rule-first):**
```
inputs: current_room, motion, device_context, time_of_day, segment_history
rules (examples):
  room=bedroom ∧ motion<low ∧ breathing✓ ∧ night        → SLEEPING
  room=living  ∧ playstation.power=on                    → GAMING
  room=office  ∧ pc.active ∧ active_app∈{ide,docs}       → WORKING
  room=kitchen ∧ (fridge.open ∨ plug.kettle=on ∨ motion) → COOKING
  room=bathroom                                          → BATHROOM
  fallback                                               → IDLE/PRESENT(room)
```

---

## 6. Context collectors (L3 — the high-value unlock)

- **Networked devices** (PlayStation, smart TV, work PC): detect powered-on /
  active via tailnet/LAN presence (ARP, `tailscale status`, ping, or device APIs).
- **Smart plugs** (Tasmota/Shelly): poll local HTTP for on/off → appliance truth.
- **Door/PIR via GPIO**: `$2` reed switch on the fridge = a reliable "cooking"
  anchor that pure CSI can't match; PIR for a kitchen sub-zone.
- **Phone** (optional): screen-on time / app usage exporter, or just WiFi presence.

---

## 7. Analytics (once the timeline exists)

- Daily routine / circadian map (real schedule vs. perceived)
- Sleep: bedtime, duration, latency, restlessness (motion + breathing irregularity)
- Sedentary ratio (sitting vs. moving hours)
- Focus blocks vs. distraction (desk uptime vs. kitchen/phone breaks)
- "Doomscroll" detector (phone-active-in-bed after midnight)
- Meal rhythm (kitchen-visit clustering)
- Bathroom frequency (longitudinal health signal)
- Room-transition graph
- Anomaly detection: today vs. 30-day baseline

---

## 8. Phased build plan

| Phase | Deliverable | Proves |
|-------|-------------|--------|
| **0 Inventory** | run capability probe across fleet | which node = which role |
| **1 Presence MVP** | 1 sensor agent + MQTT + SQLite + tailtop panel showing *current room + dwell* | end-to-end pipeline, no ML |
| **2 Context fusion** ✅ | device/plug collectors + rule-based activity labels | gaming/working/watching — fastest value |
| **3 Sleep + breathing** | bedside CSI node → breaths/min → sleep detection + sleep card | the "wow" feature |
| **4 Localization refine** | RSSI fingerprinting + reed/PIR anchors for sub-room zones | fridge-vs-stove granularity |
| **5 Analytics + ML** | daily rollups, baselines, anomaly alerts; classifier trained on self-labeled data | long-term insight |

Each phase is independently demoable and builds on the last.

---

## 9. Risks & decisions

- **Don't network raw CSI** — edge feature extraction (bandwidth + privacy).
- **Time sync** — breathing FFT is per-node (local clock fine); fusion needs only
  ~1 s sync → NTP/chrony on all nodes.
- **Drift/calibration** — fingerprints decay; anchor with L3 device truth and
  periodic recalibration; auto-label from ground-truth sensors.
- **Multi-person** — WiFi sensing assumes ~1 person/zone; degrade gracefully
  (presence stays, breathing/activity get low confidence).
- **Privacy is a feature** — all local, Tailscale-only, optional at-rest encryption.

---

## 9a. Re-use: RuView as the edge sensing layer

[RuView](https://github.com/ruvnet/RuView) (MIT) already solves the hard bottom
layer — ESP32-S3/C6 CSI firmware + DSP/ML for breathing, presence, motion (and
heart-rate/pose/fall), published over MQTT (HA auto-discovery). It is *RF-only*:
it has no device-context fusion, no time-tracking timeline, no activity labeling,
no Tailscale transport. That's exactly lifelog's scope, so the two compose:

```
RuView nodes (ESP32 CSI → DSP/ML → MQTT)        lifelog (this repo)
  L1 presence / L2 breathing+motion   ──MQTT──►  RuViewBridge → SensorEvents
                                                  + L3 device context (Phase 2)
                                                  → fusion → timeline → sleep/report
```

- **Re-use:** ESP32 firmware, breathing/presence DSP, MQTT semantic states,
  per-room calibration (RuView's MicroLoRA adaptation), HA-discovery topic convention.
- **Keep ours:** device/appliance context fusion, the time-tracking timeline,
  activity labeling, sleep *analytics*, Tailscale transport, tailtop UI.
- **This deletes the "real sensor agent" phase** — `RuViewBridge`
  (`collectors/ruview.py`) is the drop-in. Our `breathing.py` stays as a
  zero-dependency fallback. Validate RuView's heart-rate/pose claims before use.

## 10. Stack choices

- **Sensor agent / fusion:** Python (numpy/scipy for the DSP; matches the existing
  `tailtop` Textual codebase). Go is an option for the agent if single-binary
  robustness on Pi matters more than DSP convenience.
- **Transport:** MQTT (`mosquitto`).
- **Store:** SQLite → TimescaleDB if needed.
- **UI:** new `tailtop` "Lifelog" mode (Textual); optional web dashboard via
  `tailscale serve`.

---

## Next step

Phase 1 scaffold: a `lifelog/` package with (a) a sensor agent that publishes a
motion/presence feature event to MQTT, (b) a fusion service that writes
`state_sample`/`segment` to SQLite, and (c) a minimal `tailtop` panel reading the
timeline. Stub the interfaces so real CSI/RSSI capture drops in behind them.
