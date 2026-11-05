#!/usr/bin/env bash
# restaurar.sh - Deja el equipo como antes del controlador: lo detiene y desinstala, y quita la condicion
# de reserva de los supervisores anteriores (/etc/controlador-radio/reserva.lista), que vuelven a actuar
# solos. No toca la wifi ni reinicia nada. Los respaldos /root/respaldo-radio-*.tgz quedan para revisar.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "requiere root" >&2; exit 1; }
systemctl disable --now controlador-radio.service 2>/dev/null || true
# el punto de acceso fijado queda en el perfil de NetworkManager: sin el controlador nadie lo soltaria
grep -qs '^fijar_bssid = true' /etc/controlador-radio/config.toml && /usr/local/bin/controlador-radio soltar-bssid || true
rm -f /etc/systemd/system/controlador-radio.service /etc/systemd/system/controlador-radio-caido.service \
  /etc/udev/rules.d/81-bluetooth-sin-suspension.rules /usr/local/bin/controlador-radio \
  /usr/lib/systemd/system-sleep/controlador-radio-despertar
lista=/etc/controlador-radio/reserva.lista
if [[ -f "$lista" ]]; then
  while read -r unidad; do
    [[ -n "$unidad" ]] && rm -f "/etc/systemd/system/$unidad.d/reserva.conf"
  done < "$lista"
fi
nft delete table inet radio_prioridad 2>/dev/null || true
systemctl daemon-reload
if [[ -f "$lista" ]]; then
  while read -r unidad; do
    [[ -z "$unidad" ]] && continue
    t="${unidad%.service}.timer"
    if systemctl cat "$t" >/dev/null 2>&1; then systemctl start "$t"; else systemctl start "$unidad"; fi
    echo "$unidad: $(systemctl is-active "$unidad") / timer $(systemctl is-active "$t" 2>/dev/null)"
  done < "$lista"
fi
echo "restaurado; /opt/controlador-radio y /etc/controlador-radio quedan como referencia"
