#!/system/bin/sh
# Beim Entfernen des Moduls normales Laden wiederherstellen.
echo 1 > /sys/class/power_supply/battery/battery_charging_enabled
