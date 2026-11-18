#!/system/bin/sh
# hardening: Angriffsfläche verkleinern, solange SELinux permissive läuft.
LOG=/data/adb/hardening.log
log() { echo "$(date '+%F %T') $*" >> $LOG; }
[ -f $LOG ] && [ "$(wc -c < $LOG)" -gt 32768 ] && tail -n 100 $LOG > $LOG.tmp && mv $LOG.tmp $LOG

# Firewall: keine neuen eingehenden Verbindungen über irgendeine Schnittstelle außer lo.
# Das Tablet verbindet sich nur selbst nach außen (Hub, spacedesk); USB/adb reverse läuft über lo.
# Erlaubt bleiben: Antworten (ESTABLISHED/RELATED), mDNS (Suche nach dem Hub), IPv6-NDP/RA (sonst
# kein IPv6 im WLAN). DHCP läuft über Packet-Sockets und ist von iptables nicht betroffen.
setup_chain() {
  ipt=$1
  $ipt -w -N deck_in 2>/dev/null
  $ipt -w -F deck_in
  $ipt -w -A deck_in -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  $ipt -w -A deck_in -p udp --dport 5353 -j RETURN
  if [ $ipt = ip6tables ]; then
    for t in router-solicitation router-advertisement neighbour-solicitation neighbour-advertisement redirect; do
      $ipt -w -A deck_in -p ipv6-icmp --icmpv6-type $t -j RETURN
    done
  fi
  $ipt -w -A deck_in -j DROP
}
# Launcher (Web-Kachel mit fremden Seiten) im WLAN: kein Zugriff aufs Heimnetz außer dem Hub.
# Nur die App-UID des Launchers ist betroffen (Chromium WebView lädt im App-Prozess); DNS löst netd unter
# eigener UID auf. localhost (USB/adb reverse) bleibt erlaubt. REJECT statt DROP: schnelles Scheitern.
# - IPv4: private, Link-Local-, CGNAT-, Multicast-Netze und 0.0.0.0/8 (= das Tablet selbst) gesperrt;
#   zu den Hub-Adressen (vom Hub per USB) nur TCP 8767 und die Ports weiterer PC-Dienste aus den Kacheln
#   (z. B. MoBro 42169).
# - IPv6: komplett gesperrt außer ::1 - globale IPv6-Adressen von PC/Router/NAS wären sonst offen.
#   Chromium weicht per Happy Eyeballs sofort auf IPv4 aus.
HUB_WLAN_PORT=8767
PKG=app.tabletdeck.launcher
STATE=/data/adb/hardening.state
launcher_uid() { stat -c %u /data/data/$PKG 2>/dev/null; }
hub_ips() {   # aus den App-Einstellungen (wlan_hosts), nur IPv4-Ziffernfolgen
  sed -n 's/.*name="wlan_hosts">\([0-9.,]*\)<.*/\1/p' /data/data/$PKG/shared_prefs/deck.xml 2>/dev/null | tr ',' ' '
}
service_ports() {   # Ports weiterer PC-Dienste (z. B. MoBro), nur Ziffern
  sed -n 's/.*name="wlan_service_ports">\([0-9,]*\)<.*/\1/p' /data/data/$PKG/shared_prefs/deck.xml 2>/dev/null | tr ',' ' '
}
drop_jumps() {   # Sprünge für eine UID entfernen
  [ -n "$1" ] || return
  for ipt in iptables ip6tables; do
    while $ipt -w -D OUTPUT -m owner --uid-owner "$1" -j deck_out 2>/dev/null; do :; done
  done
}
setup_out() {
  for ipt in iptables ip6tables; do
    $ipt -w -N deck_out 2>/dev/null
    $ipt -w -F deck_out
  done
  iptables -w -A deck_out -d 127.0.0.0/8 -j RETURN
  for ip in $(hub_ips); do
    for port in $HUB_WLAN_PORT $(service_ports); do
      iptables -w -A deck_out -d $ip -p tcp --dport $port -j RETURN
    done
  done
  for net in 0.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 224.0.0.0/4; do
    iptables -w -A deck_out -d $net -j REJECT
  done
  ip6tables -w -A deck_out -d ::1/128 -j RETURN
  ip6tables -w -A deck_out -j REJECT
}
ensure_jump() {   # Sprung an Position 1 von INPUT (vor den Chains von netd); netd kann INPUT neu aufbauen
  for ipt in iptables ip6tables; do
    $ipt -w -L deck_in -n >/dev/null 2>&1 || setup_chain $ipt
    if ! $ipt -w -C INPUT ! -i lo -j deck_in 2>/dev/null; then
      $ipt -w -I INPUT 1 ! -i lo -j deck_in && log "$ipt: Firewall-Sprung gesetzt"
    fi
  done
  # Launcher-Sperre ins LAN. Neu aufbauen, wenn sich UID (Neuinstallation) oder Hub-Adressen ändern.
  uid=$(launcher_uid)
  old=$(cat $STATE 2>/dev/null)
  old_uid=${old%% *}
  if [ -z "$uid" ]; then   # Launcher deinstalliert: Sprung nicht an einer später neu vergebenen UID lassen
    drop_jumps "$old_uid"
    rm -f $STATE
    return
  fi
  want="$uid $(hub_ips) / $(service_ports)"
  if [ "$want" != "$old" ] || ! iptables -w -L deck_out -n >/dev/null 2>&1; then
    [ "$old_uid" != "$uid" ] && drop_jumps "$old_uid"
    setup_out && echo "$want" > $STATE && log "Launcher-UID $uid: Heimnetz gesperrt, Hub: $(hub_ips)"
  fi
  for ipt in iptables ip6tables; do
    if ! $ipt -w -C OUTPUT -m owner --uid-owner $uid -j deck_out 2>/dev/null; then
      $ipt -w -I OUTPUT 1 -m owner --uid-owner $uid -j deck_out && log "$ipt: Launcher-Sperre gesetzt"
    fi
  done
}

for ipt in iptables ip6tables; do setup_chain $ipt; done
ensure_jump

# Lenovo-Fabriktests, die als root laufen und nicht gebraucht werden. init.qcom.rc startet sie erst
# "on property:sys.boot_completed=1" (nach diesem Skript) - deshalb darauf warten.
#   ptt_wlan = ptt_socket_app (Qualcomm-WLAN-Test, root im init-Kontext, TCP 127.0.0.1:1528)
#   ftmd_bt  = ftmdaemon (Bluetooth-Fabriktest, root). Beide sind oneshot und bleiben danach aus.
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 2; done
sleep 5
for svc in ptt_wlan ftmd_bt; do
  if [ "$(getprop init.svc.$svc)" = running ]; then stop $svc; fi
  log "$svc: $(getprop init.svc.$svc)"
done

# Schlafen/Ausschalten auf Wunsch des PCs im WLAN-Betrieb: Der Launcher (ohne eigene Rechte) legt die
# Anfrage in seinem privaten Ordner ab - nur er selbst und root können dort schreiben.
power_request() {
  f=/data/data/$PKG/files/power_request
  [ -f $f ] || return
  req=$(head -c 16 $f)
  age=$(( $(date +%s) - $(stat -c %Y $f 2>/dev/null || echo 0) ))
  rm -f $f
  # Nur frische Anfragen (z. B. nach Modul-Pause oder Neuinstallation nicht beim Start ausschalten)
  # negatives Alter: Uhr nach Neustart ohne Netz noch falsch (1970er) - ebenfalls verwerfen
  if [ $age -gt 60 ] || [ $age -lt -5 ]; then log "Anfrage '$req' verworfen (Alter ${age}s)"; return; fi
  case $req in
    sleep)    log "PC: schlafen";  input keyevent KEYCODE_SLEEP ;;
    shutdown) log "PC: aus";       sync; svc power shutdown ;;
    wake)     log "PC: wecken";    input keyevent KEYCODE_WAKEUP ;;
  esac
}

# Alle 2 s Anfrage prüfen, alle 10 s die Firewall-Sprünge (netd-Neustart, neue Hub-Adresse)
n=0
while true; do
  power_request
  [ $((n % 5)) = 0 ] && ensure_jump
  n=$((n + 1))
  sleep 2
done
