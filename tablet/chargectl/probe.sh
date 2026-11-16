#!/system/bin/sh
# Liest die Lade-Knoten und testet battery_charging_enabled (nur kurz, danach zurückgesetzt).
B=/sys/class/power_supply/battery
show() {
  echo "--- $1"
  for f in capacity status charge_type current_now voltage_now battery_charging_enabled charging_enabled input_suspend battery_maintain charge_control_limit charge_control_limit_max recharge_soc health temp cycle_count charge_full; do
    [ -e "$B/$f" ] && echo "$f=$(cat $B/$f 2>&1)"
  done
  for f in online present type current_max; do
    [ -e /sys/class/power_supply/usb/$f ] && echo "usb.$f=$(cat /sys/class/power_supply/usb/$f 2>&1)"
  done
}
show "Ausgangszustand"
if [ "$1" = "test" ]; then
  trap 'echo 1 > $B/battery_charging_enabled' EXIT INT TERM   # bei Abbruch Laden wieder an
  echo 0 > $B/battery_charging_enabled
  sleep 8
  show "battery_charging_enabled=0"
  echo 1 > $B/battery_charging_enabled
  sleep 5
  show "zurückgesetzt"
fi
