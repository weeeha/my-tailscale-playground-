#!/bin/sh
# fleet_collect.sh — print one JSON object of this Pi's vitals.
# Read-only, side-effect-free, dependency-free POSIX sh. Portable across
# Broadcom (vcgencmd present) and Allwinner (thermal via /sys only).
set -u

j() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }   # json-escape a string

MODEL=$(tr -d '\000' < /proc/device-tree/model 2>/dev/null || echo "")
SERIAL=$(awk -F': ' '/Serial/{print $2}' /proc/cpuinfo 2>/dev/null | tail -1)
CORES=$(nproc 2>/dev/null || echo 0)
MEM_TOTAL_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
MEM_AVAIL_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
MEM_TOTAL_MB=$((MEM_TOTAL_KB / 1024))
[ "$MEM_TOTAL_KB" -gt 0 ] && MEM_PCT=$(awk "BEGIN{printf \"%.1f\", (1-($MEM_AVAIL_KB/$MEM_TOTAL_KB))*100}") || MEM_PCT=0
OS=$(. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-}")
KERNEL=$(uname -r)
LOAD1=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)
UPTIME=$(awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || echo 0)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
HOST=$(hostname 2>/dev/null || cat /proc/sys/kernel/hostname 2>/dev/null || echo "unknown")

# CPU %: sample /proc/stat twice 200ms apart.
read -r _ a b c idle1 rest < /proc/stat; t1=$((a+b+c+idle1)); sleep 0.2
read -r _ a b c idle2 rest < /proc/stat; t2=$((a+b+c+idle2))
DT=$((t2-t1)); DI=$((idle2-idle1))
[ "$DT" -gt 0 ] && CPU_PCT=$(awk "BEGIN{printf \"%.1f\", (1-($DI/$DT))*100}") || CPU_PCT=0

# Disk (root).
DISK=$(df -kP / 2>/dev/null | awk 'NR==2{printf "%d %d %d", $2,$3,$4}')
DTOTAL=$(printf '%s' "$DISK" | awk '{print $1}'); DUSED=$(printf '%s' "$DISK" | awk '{print $2}'); DAVAIL=$(printf '%s' "$DISK" | awk '{print $3}')
[ "${DTOTAL:-0}" -gt 0 ] && DUSED_PCT=$(awk "BEGIN{printf \"%.1f\", ($DUSED/$DTOTAL)*100}") || DUSED_PCT=0
DFREE_GB=$(awk "BEGIN{printf \"%.1f\", ${DAVAIL:-0}/1048576}")
DTOTAL_GB=$(awk "BEGIN{printf \"%.1f\", ${DTOTAL:-0}/1048576}")

# Thermal: /sys universal; vcgencmd throttle flags on Broadcom only.
TEMP_MC=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "")
[ -n "$TEMP_MC" ] && TEMP_C=$(awk "BEGIN{printf \"%.1f\", $TEMP_MC/1000}") || TEMP_C=null
if command -v vcgencmd >/dev/null 2>&1; then
  VCG=true
  TH=$(vcgencmd get_throttled 2>/dev/null | sed 's/.*=//')
  THR=$(( ${TH:-0} & 0x4 ? 1 : 0 )); UV=$(( ${TH:-0} & 0x1 ? 1 : 0 ))
  [ "$THR" = 1 ] && THROTTLED=true || THROTTLED=false
  [ "$UV" = 1 ] && UNDERV=true || UNDERV=false
else
  VCG=false; THROTTLED=false; UNDERV=false
fi

# Displays (HDMI kiosks) via DRM connector status.
DISP=""
for c in /sys/class/drm/*/status; do
  [ -f "$c" ] || continue
  s=$(cat "$c"); name=$(basename "$(dirname "$c")" | sed 's/^card[0-9]*-//')
  [ "$s" = "connected" ] && DISP="$DISP{\"connector\":\"$(j "$name")\",\"status\":\"connected\"},"
done
DISP="[${DISP%,}]"

USB_COUNT=$(lsusb 2>/dev/null | wc -l | tr -d ' '); USB_COUNT=${USB_COUNT:-0}

# Battery (UPS HAT) if present.
BAT='{"present":false}'
for b in /sys/class/power_supply/*/capacity; do
  [ -f "$b" ] && BAT="{\"present\":true,\"pct\":$(cat "$b")}" && break
done

# App health, by hostname class (lowercase for case-insensitive matching).
APP_NAME=""; APP_RUNNING=null; APP_LAST=""
HOST_LC=$(printf '%s' "$HOST" | tr '[:upper:]' '[:lower:]')
case "$HOST_LC" in
  *clock*) APP_NAME="superclock"; pgrep -f superclock >/dev/null 2>&1 && APP_RUNNING=true || APP_RUNNING=false ;;
  *eink*|*ink*) APP_NAME="epaper"; pgrep -f 'eink\|epaper\|render' >/dev/null 2>&1 && APP_RUNNING=true || APP_RUNNING=false
    f=$(ls -t "$HOME"/*.png "$HOME"/last_frame* 2>/dev/null | head -1)
    [ -n "$f" ] && APP_LAST=$(date -u -r "$f" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "") ;;
  *dashboard*|*plant*|*orangepi*) APP_NAME="dashboard"; pgrep -f 'server.py' >/dev/null 2>&1 && APP_RUNNING=true || APP_RUNNING=false ;;
esac

cat <<EOF
{"schema":1,"host":"$(j "$HOST")","collected_at":"$NOW",
"config":{"model":"$(j "$MODEL")","serial":"$(j "$SERIAL")","cpu_cores":$CORES,"mem_total_mb":$MEM_TOTAL_MB,"os":"$(j "$OS")","kernel":"$(j "$KERNEL")","disk_total_gb":$DTOTAL_GB},
"thermal":{"soc_temp_c":$TEMP_C,"vcgencmd_present":$VCG,"throttled_now":$THROTTLED,"under_voltage_now":$UNDERV},
"health":{"load1":$LOAD1,"cpu_pct":$CPU_PCT,"mem_pct":$MEM_PCT,"disk_used_pct":$DUSED_PCT,"disk_free_gb":$DFREE_GB,"uptime_s":$UPTIME},
"side_things":{"displays":$DISP,"usb":[],"usb_count":$USB_COUNT,"battery":$BAT},
"app":{"name":"$(j "$APP_NAME")","running":$APP_RUNNING,"last_render":"$(j "$APP_LAST")"}}
EOF
