"""Static configuration: activities, rooms, the node→room map, and thresholds.

In a real deployment this would be a config file per tailnet; for the Phase 1
scaffold the defaults below describe a plausible one-person home so the simulator
and the fusion engine agree on the same world.
"""

from __future__ import annotations

# --- activity labels --------------------------------------------------------
SLEEPING = "SLEEPING"
WORKING = "WORKING"
GAMING = "GAMING"
WATCHING = "WATCHING"
COOKING = "COOKING"
BATHROOM = "BATHROOM"
IDLE = "IDLE"          # present in a room, no specific activity inferred
AWAY = "AWAY"          # no node sees anyone

ACTIVITIES = [SLEEPING, WORKING, GAMING, WATCHING, COOKING, BATHROOM, IDLE, AWAY]

# one-letter glyphs for the text/TUI timeline ribbon
GLYPH = {
    SLEEPING: "z",
    WORKING: "W",
    GAMING: "G",
    WATCHING: "T",
    COOKING: "C",
    BATHROOM: "B",
    IDLE: ".",
    AWAY: " ",
}

# --- the fleet: which sensor node covers which room -------------------------
# node_id -> room. The probe script (scripts/fleet-capability-probe.sh) tells
# you which physical node can play which role; this is just the logical map.
NODES = {
    "esp32-bedroom": "bedroom",
    "pi-bathroom": "bathroom",
    "pi-kitchen": "kitchen",
    "pi-office": "office",
    "pi-living": "living",
}
ROOMS = sorted(set(NODES.values()))

# --- L3 context keys (device / appliance ground truth) ----------------------
CTX_PLAYSTATION = "playstation"   # power/network state of the console
CTX_TV = "tv"                     # streaming stick / smart TV active
CTX_PC_ACTIVE = "pc_active"       # work machine active (+ foreground app)
CTX_FRIDGE_OPEN = "fridge_open"   # $2 reed switch on the fridge door
CTX_KETTLE_ON = "kettle_on"       # smart plug on a kitchen appliance

# --- thresholds -------------------------------------------------------------
MOTION_OCCUPIED = 0.12   # >= this ⇒ a node considers its room occupied
MOTION_ACTIVE = 0.45     # >= this ⇒ vigorous motion (e.g. cooking, cleaning)
STALE_S = 90.0           # a sensor reading older than this no longer counts
NIGHT_START_H = 22       # hours [NIGHT_START, NIGHT_END) count as "night"
NIGHT_END_H = 6
