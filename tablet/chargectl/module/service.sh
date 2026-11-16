#!/system/bin/sh
# chargectl: hält den Akku zwischen MIN und MAX Prozent (Hysterese).
# Läuft als Magisk-Dienst nach dem Start. Laden aus = battery_charging_enabled=0:
# Das Tablet läuft dann vom USB-Strom (reicht dieser nicht, entlädt sich der Akku trotzdem langsam).
B=/sys/class/power_supply/battery
SW=$B/battery_charging_enabled
CONF=/data/adb/chargectl.conf
LOG=/data/adb/chargectl.log
WL=chargectl

log() { echo "$(date '+%F %T') $*" >> $LOG; }
# nur ganze Zahlen >= 0 ohne führende Null (ash rechnet "0490" sonst oktal und bricht ab)
num() { case $1 in ''|*[!0-9]*|0?*) return 1;; esac; }

[ -f $LOG ] && [ "$(wc -c < $LOG)" -gt 65536 ] && tail -n 200 $LOG > $LOG.tmp && mv $LOG.tmp $LOG
[ -w $SW ] || { log "FEHLER: $SW nicht beschreibbar - Ende"; exit 1; }
log "chargectl gestartet"

set_charging() {
  [ "$(cat $SW)" = "$1" ] && return
  echo "$1" > $SW && log "cap=$cap temp=$temp -> charging=$1"
}

# Wach bleiben, solange tatsächlich geladen wird - sonst schläft die Schleife ein und es lädt
# bis 100 %. Ohne Stromquelle (status != Charging) kein Wakelock, damit der Akku nicht leerläuft.
locked=0
update_wakelock() {
  if [ "$(cat $SW)" = 1 ] && [ "$(cat $B/status 2>/dev/null)" = Charging ]; then want=1; else want=0; fi
  [ $want = $locked ] && return
  if [ $want = 1 ]; then echo $WL > /sys/power/wake_lock; else echo $WL > /sys/power/wake_unlock; fi
  locked=$want
}

hot=0
while true; do
  # Standardwerte, dann optionale Konfiguration (nur MIN/MAX/TEMP_MAX/INTERVAL werden übernommen)
  MIN=45; MAX=55; TEMP_MAX=450; INTERVAL=60
  if [ -f $CONF ]; then
    c_min=$(sed -n 's/^MIN=//p' $CONF); c_max=$(sed -n 's/^MAX=//p' $CONF)
    c_tmax=$(sed -n 's/^TEMP_MAX=//p' $CONF); c_int=$(sed -n 's/^INTERVAL=//p' $CONF)
    if num "$c_min" && num "$c_max" && [ "$c_min" -lt "$c_max" ] && [ "$c_max" -le 100 ]; then
      MIN=$c_min; MAX=$c_max
    fi
    num "$c_tmax" && TEMP_MAX=$c_tmax
    num "$c_int" && [ "$c_int" -ge 10 ] && INTERVAL=$c_int
  fi

  cap=$(cat $B/capacity 2>/dev/null)
  temp=$(cat $B/temp 2>/dev/null)
  num "$temp" || temp=0
  # Temperatur-Hysterese: ab TEMP_MAX aus, erst 3 °C darunter wieder frei
  if [ "$temp" -ge "$TEMP_MAX" ]; then hot=1; elif [ "$temp" -lt $((TEMP_MAX - 30)) ]; then hot=0; fi

  if [ $hot = 1 ]; then
    set_charging 0
  elif ! num "$cap"; then
    set_charging 1          # Ladestand unbekannt: lieber laden als leerlaufen
  elif [ "$cap" -ge "$MAX" ]; then
    set_charging 0
  elif [ "$cap" -le "$MIN" ]; then
    set_charging 1
  fi
  sleep 2   # Status braucht nach dem Umschalten einen Moment
  update_wakelock
  sleep $INTERVAL
done
