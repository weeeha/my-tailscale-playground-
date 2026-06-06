#!/bin/sh
# fleet-capability-probe.sh
#
# Capability inventory for a single fleet node (Raspberry Pi, Orange Pi, generic Linux).
# Reads ONLY local hardware/OS facts — it changes nothing and needs no network.
#
# Focus: the things that decide which "playground" projects a node can do —
#   * WiFi presence sensing (monitor mode + Channel State Information / CSI)
#   * camera projects (security mesh, print-failure detection)
#   * 3D printer / serial device control
#   * Tailscale fleet membership
#
# Usage (per device):
#   scp scripts/fleet-capability-probe.sh node:/tmp/ && ssh node 'sh /tmp/fleet-capability-probe.sh'
#
# Fan it across the whole tailnet at once:
#   for h in $(tailscale status --json | jq -r '.Peer[].DNSName | rtrimstr(".")'); do
#     echo "===== $h ====="; ssh "$h" 'sh -s' < scripts/fleet-capability-probe.sh
#   done
#
# Most checks read more when run as root (e.g. `iw list` monitor-mode flags). Prefer sudo.

set -u

say()  { printf '%s\n' "$*"; }
hdr()  { printf '\n== %s ==\n' "$*"; }
kv()   { printf '  %-22s %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- identity ----
hdr "Board / OS"
model="unknown"
[ -r /proc/device-tree/model ] && model="$(tr -d '\0' < /proc/device-tree/model)"
[ "$model" = "unknown" ] && [ -r /sys/firmware/devicetree/base/model ] &&
  model="$(tr -d '\0' < /sys/firmware/devicetree/base/model)"
kv "Model"    "$model"
kv "Hostname" "$(hostname 2>/dev/null || echo '?')"
kv "Kernel"   "$(uname -srm 2>/dev/null)"
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release 2>/dev/null
  kv "OS" "${PRETTY_NAME:-?}"
fi
kv "Arch"     "$(uname -m 2>/dev/null)"
# CPU model line works for both ARM SoCs and x86
cpu="$(awk -F': ' '/^model name|^Model|^Hardware/ {print $2; exit}' /proc/cpuinfo 2>/dev/null)"
kv "CPU"      "${cpu:-?}"
ncpu="$(nproc 2>/dev/null || echo '?')"
kv "Cores"    "$ncpu"
mem="$(awk '/MemTotal/ {printf "%.1f GiB", $2/1024/1024}' /proc/meminfo 2>/dev/null)"
kv "RAM"      "${mem:-?}"

# ----------------------------------------------------------------- wifi -------
hdr "WiFi — interfaces & chipset"
wifi_found=0
for d in /sys/class/net/*; do
  [ -e "$d/wireless" ] || [ -d "$d/phy80211" ] || continue
  wifi_found=1
  ifn="$(basename "$d")"
  drv="$(basename "$(readlink -f "$d/device/driver" 2>/dev/null)" 2>/dev/null)"
  kv "Interface" "$ifn  (driver: ${drv:-?})"
done
[ "$wifi_found" = 0 ] && kv "Interface" "none detected"

if have iw; then
  hdr "WiFi — monitor mode support  (needed for presence sensing)"
  # 'iw list' enumerates supported interface modes per phy; 'monitor' is the one we need.
  if iw list >/tmp/.iwlist 2>/dev/null && [ -s /tmp/.iwlist ]; then
    if grep -q '\* monitor' /tmp/.iwlist; then
      kv "Monitor mode" "SUPPORTED  (can sniff probe requests / RSSI)"
    else
      kv "Monitor mode" "NOT supported by this chipset/driver"
    fi
    # netdetect/scan + VHT info is a nice-to-have signal of a capable card
    grep -q 'VHT' /tmp/.iwlist && kv "5GHz / VHT" "yes"
    rm -f /tmp/.iwlist
  else
    kv "Monitor mode" "unknown (run as root: 'sudo iw list')"
  fi
else
  kv "iw tool" "not installed  (apt install iw)"
fi

hdr "WiFi — CSI capability  (the 'WiFi can see you' demo)"
# Broadcom chips on Pi/Pi-Zero/Pi3/Pi4 can do CSI via Nexmon; ESP32 does CSI natively.
csi="no known path on this node"
case "$model" in
  *Raspberry*)
    bcm="$(lsmod 2>/dev/null | awk '/^brcmfmac/ {print $1; exit}')"
    [ -n "$bcm" ] && csi="POSSIBLE — Broadcom brcmfmac present; needs Nexmon-CSI patched firmware"
    ;;
esac
# Generic: detect Intel iwlwifi (CSI via supported toolkits on some NICs) or Atheros
drvs="$(ls -1 /sys/class/net/*/device/driver 2>/dev/null | xargs -n1 readlink -f 2>/dev/null | xargs -n1 basename 2>/dev/null | sort -u)"
case "$drvs" in
  *ath9k*)   csi="POSSIBLE — ath9k present; Atheros CSI Tool is an option" ;;
  *iwlwifi*) csi="MAYBE — Intel iwlwifi; CSI extraction is NIC-model dependent" ;;
esac
kv "CSI" "$csi"

# ---------------------------------------------------------------- camera ------
hdr "Camera"
cam=0
for v in /dev/video*; do [ -e "$v" ] && { kv "V4L2 device" "$v"; cam=1; }; done
if have libcamera-hello || have rpicam-hello; then
  kv "libcamera" "present (Pi camera stack)"; cam=1
fi
if have vcgencmd; then
  det="$(vcgencmd get_camera 2>/dev/null)"
  [ -n "$det" ] && kv "vcgencmd" "$det"
fi
have v4l2-ctl && v4l2-ctl --list-devices >/tmp/.cams 2>/dev/null && [ -s /tmp/.cams ] && {
  kv "USB/CSI cams" "$(grep -c ':' /tmp/.cams) device node(s) — run 'v4l2-ctl --list-devices'"; rm -f /tmp/.cams; }
[ "$cam" = 0 ] && kv "Camera" "none detected"

# --------------------------------------------------------- printer / serial --
hdr "3D printer / serial devices"
ser=0
for s in /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/*; do
  [ -e "$s" ] || continue
  ser=1; kv "Serial" "$s"
done
[ "$ser" = 0 ] && kv "Serial" "no USB serial / printer adapters detected"
have lsusb && { hdr "USB devices"; lsusb 2>/dev/null | sed 's/^/  /'; }

# ----------------------------------------------------------- gpio / extras ----
hdr "GPIO / display headers"
[ -e /dev/gpiochip0 ] && kv "GPIO" "present (/dev/gpiochip*) — LED matrix / e-ink / sensors OK" \
                      || kv "GPIO" "not detected"
for b in /dev/i2c-* /dev/spidev*; do [ -e "$b" ] && kv "Bus" "$b"; done

# -------------------------------------------------------------- tailscale -----
hdr "Tailscale"
if have tailscale; then
  kv "CLI" "$(tailscale version 2>/dev/null | head -1)"
  st="$(tailscale status 2>/dev/null | head -1)"
  kv "Status" "${st:-not logged in}"
  ip="$(tailscale ip -4 2>/dev/null | head -1)"
  [ -n "$ip" ] && kv "Tailnet IP" "$ip"
else
  kv "CLI" "not installed on this node"
fi

hdr "Summary"
say "  Presence-sensing readiness depends on 'Monitor mode' + 'CSI' above."
say "  Camera + Serial sections tell you which nodes can host the printer/camera projects."
printf '\nDone: %s\n' "$(hostname 2>/dev/null)"
