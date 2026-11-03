#!/usr/bin/env bash
# respaldar.sh - Copia en /root/respaldo-radio-<fecha>.tgz lo que el controlador reemplaza o toca:
# supervisores de reserva (RESERVA="a.service ..."), modprobe, conexiones y ajustes de NetworkManager,
# TLP, el propio controlador y los parametros vivos. Corre como root. Imprime la ruta. Lo usa restaurar.sh.
set -euo pipefail
umask 077  # el respaldo incluye secretos (claves wifi, tokens): nunca existe legible por otros
ts=$(date +%Y%m%d-%H%M%S)
dir=$(mktemp -d /root/.respaldo-radio-XXXXXX)
trap 'rm -rf -- "${dir:?}"' EXIT
archivos=(
  /etc/modprobe.d /etc/NetworkManager/system-connections /etc/NetworkManager/conf.d /etc/tlp.conf /etc/tlp.d
  /etc/udev/rules.d /etc/systemd/system/controlador-radio.service /etc/controlador-radio
)
for unidad in ${RESERVA:-}; do
  archivos+=("/etc/systemd/system/$unidad" "/etc/systemd/system/$unidad.d" "/etc/systemd/system/${unidad%.service}.timer")
  exe=$(systemctl show -p ExecStart --value "$unidad" 2>/dev/null | grep -o 'path=[^ ;]*' | head -1 | cut -d= -f2)
  [[ -n "$exe" && "$exe" != /usr/bin/* ]] && archivos+=("$exe")
done
for f in "${archivos[@]}"; do
  [[ -e "$f" ]] && cp -a --parents -- "$f" "$dir/" || echo "no existe (se omite): $f" >&2
done
{
  echo "# Estado vivo al $ts"
  for p in /sys/module/rtw88*/parameters/* /sys/module/btusb/parameters/*; do
    printf '%s=%s\n' "$p" "$(cat "$p" 2>/dev/null)"
  done
  rfkill -o ID,TYPE,DEVICE,SOFT,HARD
  lsmod | awk '$1 ~ /^(rtw88|bt|bluetooth|mac80211|cfg80211)/'
  for unidad in ${RESERVA:-}; do systemctl is-enabled "$unidad" "${unidad%.service}.timer" 2>&1; done
  iw dev 2>/dev/null | grep -E "Interface|power" ; nmcli -t device
} > "$dir/estado-vivo.txt" 2>&1
out=/root/respaldo-radio-$ts.tgz
tar -C "$dir" -czf "$out" .
chmod 600 "$out"
echo "$out"
