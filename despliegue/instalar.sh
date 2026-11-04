#!/usr/bin/env bash
# instalar.sh [actuar|observar] - Instala el controlador. Corre como root desde la carpeta del paquete
# desempacado (la que contiene src/ y despliegue/). Antes de tocar nada hace un respaldo nuevo; si la
# prueba de humo falla, no cambia ningun servicio. Lo deshace despliegue/restaurar.sh.
# Variables: EQUIPO=<nombre> usa despliegue/equipos/<nombre>.toml la primera vez (si no, config.toml);
#            RESERVA="a.service b.service" deja esos supervisores anteriores de reserva.
set -euo pipefail
MODO=${1:-actuar}
[[ "$MODO" == observar || "$MODO" == actuar ]] || { echo "modo invalido: $MODO" >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo "requiere root" >&2; exit 1; }
cd "$(dirname "$0")/.."
log() { echo "$(date '+%T') $*"; }

log "1. respaldo previo"
RESERVA="${RESERVA:-}" bash despliegue/respaldar.sh

log "2. codigo en /opt/controlador-radio (prueba de humo antes de activarlo)"
nuevo=$(mktemp -d /opt/.controlador-radio-XXXXXX)
trap 'rm -rf -- "${nuevo:?}" 2>/dev/null' EXIT   # si algo falla antes de activarlo, no queda basura
cp -r src/radio_rtw88 "$nuevo/"
cp README.md "$nuevo/"
python3 -I -c "import sys; sys.path.insert(0, '$nuevo'); import radio_rtw88.demonio, radio_rtw88.__main__"
python3 -I -m compileall -q "$nuevo/radio_rtw88"
rm -rf -- /opt/controlador-radio.anterior
[[ -d /opt/controlador-radio ]] && mv /opt/controlador-radio /opt/controlador-radio.anterior
mv "$nuevo" /opt/controlador-radio && trap - EXIT
chmod -R go-w /opt/controlador-radio
install -m 0755 despliegue/controlador-radio /usr/local/bin/controlador-radio
install -m 0755 despliegue/respaldar.sh /usr/local/sbin/controlador-radio-respaldar
install -m 0755 despliegue/restaurar.sh /usr/local/sbin/controlador-radio-restaurar

log "3. configuracion (la existente se conserva) y unidades"
install -d -m 0755 /etc/controlador-radio
base=despliegue/config.toml
[[ -n "${EQUIPO:-}" && -f "despliegue/equipos/$EQUIPO.toml" ]] && base="despliegue/equipos/$EQUIPO.toml"
[[ -f /etc/controlador-radio/config.toml ]] || install -m 0644 "$base" /etc/controlador-radio/config.toml
sed -i "s/^modo = .*/modo = \"$MODO\"/" /etc/controlador-radio/config.toml
install -m 0644 despliegue/controlador-radio.service despliegue/controlador-radio-caido.service /etc/systemd/system/
install -m 0644 despliegue/81-bluetooth-sin-suspension.rules /etc/udev/rules.d/
udevadm control --reload 2>/dev/null || true
for unidad in ${RESERVA:-}; do
  install -D -m 0644 despliegue/reserva.conf "/etc/systemd/system/$unidad.d/reserva.conf"
  echo "$unidad" >> /etc/controlador-radio/reserva.lista
done
[[ -f /etc/controlador-radio/reserva.lista ]] && sort -u -o /etc/controlador-radio/reserva.lista /etc/controlador-radio/reserva.lista
if [[ -d /etc/tlp.d ]]; then  # sin ahorro de energia en la wifi (docs/adr/0003)
  install -m 0644 despliegue/91-wifi-sin-ahorro.conf /etc/tlp.d/
  grep -qsE '^WIFI_PWR_ON_(AC|BAT)=' /etc/tlp.conf && echo "AVISO: /etc/tlp.conf fija WIFI_PWR_ON_*, que le gana a /etc/tlp.d: comentala" >&2
fi
chmod -R go-rwx /var/lib/controlador-radio 2>/dev/null || true

log "4. relevo: el controlador arranca; los anteriores quedan de reserva"
systemctl daemon-reload
systemctl enable controlador-radio.service
systemctl reset-failed controlador-radio.service 2>/dev/null || true  # instalar es un arranque intencional
systemctl restart controlador-radio.service
sleep 8
systemctl is-active controlador-radio.service
for unidad in ${RESERVA:-}; do  # un bucle permanente que ya corria se relanza para que evalue su condicion
  [[ "$MODO" == actuar ]] && systemctl is-active --quiet "$unidad" && systemctl restart "$unidad" || true
done
controlador-radio diagnostico
log "instalado en modo $MODO"
