# lifelog

A private, **local** WiFi-sensing time-tracker for a Tailscale device fleet —
"where does my time go?" answered by your own Raspberry Pis / Orange Pis / ESP32s,
with nothing leaving the machine.

Full design: [`../notes/lifelog-wifi-sensing-design.md`](../notes/lifelog-wifi-sensing-design.md).

## Status: Phase 1 scaffold (stub-first, runnable)

The whole pipeline runs end-to-end **today, on any machine, no hardware**, using a
simulated day of sensor events:

```
sensor agent → bus → fusion (localization + rule state machine) → SQLite timeline → report/TUI
   (simulated)  (LocalBus)                                                           ▲ you are here
```

Real CSI/RSSI capture drops in behind the `bus` / agent interfaces later; the
fusion, store, rules, and UI don't change.

## Try it

```sh
cd lifelog
python -m lifelog demo                 # simulate a day, fuse it, print the timeline
python -m lifelog demo --db my.db      # ...and keep the SQLite file
python -m lifelog report --db my.db    # re-print a stored day
python -m lifelog tui --db my.db       # interactive timeline (needs: pip install 'lifelog[tui]')
```

## Layout

| File | Role |
|------|------|
| `config.py` | activities, rooms, node→room map, thresholds |
| `model.py` | `SensorEvent` / `StateSample` / `Segment` |
| `store.py` | SQLite timeline (schema, writes, day queries) |
| `bus.py` | `LocalBus` (Phase 1) + `MqttBus` (real fleet, optional) |
| `rules.py` | localization + the rule-based activity state machine |
| `fusion.py` | events → fused state → segments |
| `simulator.py` | scripted believable day; stands in for real sensors |
| `report.py` | plain-text timeline + 24h ribbon (no deps) |
| `tui.py` | optional Textual view (seed of a tailtop "Lifelog" mode) |

## What's deliberately stubbed

- **Sensor capture** — `simulator.py` emits the event stream that real
  ESP32-CSI / Nexmon-CSI / RSSI agents will produce. The event *shape* is final.
- **Transport** — `LocalBus` short-circuits through SQLite; swap in `MqttBus`
  for the real tailnet with no fusion changes.
- **Activity model** — rule-based on purpose (explainable, and it generates the
  labels you later train an ML classifier on).

## Tests

```sh
pip install -e '.[dev]'
pytest
```
