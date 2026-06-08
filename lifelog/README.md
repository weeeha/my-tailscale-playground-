# wifi-life-log

A private, **local** WiFi-sensing time-tracker for a Tailscale device fleet —
*"where does my time go?"* answered by your own Raspberry Pis / Orange Pis /
ESP32s, with nothing leaving the machine.

> WiFi sensing tells you **where** you are and **how active** you are; the
> **labels** ("gaming", "cooking", "sleeping") come from fusing that with the
> **devices already on your network**. Everything rides Tailscale (WireGuard) to
> a collector you own — no cloud, no account, no vendor.

📖 **Docs:** [concept & findings](docs/concept.md) · [full system design](docs/design.md)

---

## Status

Phases 0–3 + a RuView bridge are built. The whole pipeline runs **end-to-end
today on any machine, no hardware**, using a simulated day of sensor events:

```
sensor agent → bus → fusion (localization + rule state machine) → SQLite timeline → report/TUI
   (simulated)  (LocalBus)                                                           ▲ you are here
```

Real CSI/RSSI capture drops in behind the `bus` / agent interfaces (or via the
RuView bridge) without touching fusion, store, rules, or UI.

| Phase | Deliverable | State |
|---|---|---|
| 1 Presence MVP | room + dwell timeline | ✅ |
| 2 Context fusion | device/plug collectors → activity labels | ✅ |
| 3 Sleep + breathing | breathing DSP + sleep card | ✅ |
| RuView bridge | adopt RuView CSI sensing as the edge layer | ✅ |
| 4 Localization refine | RSSI fingerprint + reed/PIR sub-room zones | ⬜ |
| 5 Analytics + ML | rollups, baselines, anomaly alerts, classifier | ⬜ |

## Try it

```sh
python -m lifelog demo                 # simulate a day, fuse it, print the timeline
python -m lifelog demo --db my.db      # ...and keep the SQLite file
python -m lifelog report --db my.db    # re-print a stored day
python -m lifelog tui --db my.db       # interactive timeline (needs: pip install '.[tui]')
```

## Connect real signals

**Device context (L3)** — point `lifelog/collectors/defaults.py` at your real
PlayStation / PC / smart plug / tailnet peer, then:

```sh
python -m lifelog collect --once          # probe your devices once, print state
python -m lifelog collect --db live.db    # poll live → context timeline
```

| Collector | Signal | How |
|-----------|--------|-----|
| `NetworkDeviceCollector` | console/PC powered on | TCP-connect or ping reachability |
| `HttpPlugCollector` | appliance on/off | Tasmota / Shelly local HTTP |
| `TailscaleOnlineCollector` | tailnet device up | `tailscale status --json` |

**WiFi sensing (L1/L2) via [RuView](https://github.com/ruvnet/RuView)** — adopt a
mature ESP32-CSI platform instead of building capture yourself; `RuViewBridge`
translates its MQTT breathing/presence/motion into lifelog events:

```sh
python -m lifelog ingest-ruview --db live.db --host <ruview-broker>
```

RuView handles L1/L2 (RF presence + vitals); lifelog adds L3 device context and
the timeline. `translate()` parses both per-entity and JSON `edge_vitals`
payloads defensively — verify against RuView ADR-115 and set your node→room map.
Validate heart-rate / pose claims on your own hardware before depending on them.

## Layout

| File | Role |
|------|------|
| `config.py` | activities, rooms, node→room map, thresholds |
| `model.py` | `SensorEvent` / `StateSample` / `Segment` |
| `store.py` | SQLite timeline (schema, writes, day queries) |
| `bus.py` | `LocalBus` + `MqttBus` (real fleet, optional) |
| `rules.py` | localization + the rule-based activity state machine |
| `fusion.py` | events → fused state → segments |
| `breathing.py` | respiration-rate DSP + bedside `BreathingAgent` |
| `sleep.py` | sleep-session detection + analytics card |
| `simulator.py` | scripted believable day; stands in for real sensors |
| `collectors/` | L3 device context + the RuView bridge |
| `report.py` / `tui.py` | text timeline + optional Textual view |

## What's deliberately stubbed

- **Sensor capture** — `simulator.py` emits the event stream real ESP32-CSI /
  Nexmon-CSI / RSSI agents (or RuView) produce. The event *shape* is final.
- **Transport** — `LocalBus` short-circuits through SQLite; swap in `MqttBus` for
  the real tailnet with no fusion changes.
- **Activity model** — rule-based on purpose (explainable, and it generates the
  labels you later train an ML classifier on).

## Develop

```sh
pip install -e '.[dev]'
pytest        # 33 tests: pipeline, collectors, breathing DSP, sleep, RuView bridge
```
