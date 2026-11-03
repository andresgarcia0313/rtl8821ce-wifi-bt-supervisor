<!-- lang: es-CO -->
# Supervisor de wifi Realtek RTL8821CE (rtw88) y su Bluetooth USB en Linux

Idioma: español de Colombia (es-CO). Hay un resumen en inglés justo abajo.

Caso real: un portátil HP 14 (wifi y Bluetooth en una tarjeta combo Realtek RTL8821CE) que trabaja 24/7 como plano de control de un clúster k3s, solo por wifi. Su guardián anterior, un script que reiniciaba la tarjeta ante cualquier falta de red, hizo en un mes 321 reconexiones, 218 recargas del módulo y 331 resets PCI. Este supervisor mide por capas, diagnostica la causa y aplica solo el remedio que sirve, con tope por hora. Además vigila el Bluetooth, que en ese equipo sostiene un canal de rescate, y el cable USB del celular que sirve de salida de respaldo.

## Summary in English

**Hardware:** Realtek RTL8821CE `[10ec:c821]` (PCIe, 1x1 802.11ac, in-kernel `rtw88_8821ce`), Bluetooth 4.2 `0bda:b00a` on USB (`btusb` + `btrtl`), kernel `7.0.0-38-generic`, Ubuntu 26.04.1 LTS, NetworkManager, TLP, Secure Boot on (kernel lockdown `integrity`).

**What we learned (from the kernel 7.0 source, not folklore):**

- `rtw88_pci disable_aspm=Y` really works, but only on the chip side. It stops the driver from turning on the chip's own L1/CLKREQ logic, while `lspci` still shows `ASPM L0s L1 Enabled` on the host side. `disable_lps_deep=Y` only matters when the card is in power save.
- The real latency lever was **Wi-Fi power save**. NetworkManager had `wifi.powersave=2`, but TLP (`WIFI_PWR_ON_BAT=on`) turned it back on, because the laptop runs on battery profile. In `rtw88`, power save means LPS: the card sleeps between beacons. With power save off, packet loss to the internet went from 1.7 % to 0 %, worst-case RTT from 95 ms to 36 ms, and router jitter (mdev) from 1.65 ms to 0.97 ms. Throughput did not change. Note that `/etc/tlp.conf` overrides `/etc/tlp.d`.
- With Secure Boot, debugfs is read-only for files with mode 0444 and closed for the rest. The chip probe reads MAC registers by MMIO (`rtw88/mac_0`): a chip that fell off the PCI bus reads `0xffffffff`. The soft firmware restart (`fw_crash`) is not available, so the ladder goes from reassociate to module reload and then to PCI reset.
- On command timeouts, `btusb` already resets Realtek Bluetooth by itself (`btusb_rtl_reset` → `usb_queue_reset_device`). Our Bluetooth ladder is power on, then rfkill, then rebinding `btusb`. `authorized=0/1` and `usbreset` are off by default: on a sibling machine, cutting the USB port of the radio needed a reboot to recover.
- A USB-tethered phone with metric 700 (Wi-Fi has 600) is a real fallback. The cluster runs over Tailscale (`node-ip`, `flannel-iface tailscale0`, NFS over the tailnet), so with Wi-Fi down for 103 s the nodes stayed `Ready` and Tailscale kept a direct path (5 to 8 ms). Re-enumerating the phone's USB port makes Android switch tethering off, and only the phone can turn it back on.

## El escenario

| Componente | Valor |
|---|---|
| Equipo | Portátil HP 14 (Intel), batería y cargador; plano de control de k3s |
| Wifi | Realtek RTL8821CE `[10ec:c821]`, PCIe x1, driver `rtw88_8821ce` del kernel, 1x1, 802.11ac |
| Bluetooth | Realtek `0bda:b00a` por USB, BT 4.2 con LE, `btusb` + `btrtl`; servidor NAP del canal de rescate |
| Firmware | `rtw8821c_fw.bin` (WL 24.11) y `rtl_bt/rtl8821c_fw.bin`, paquete `linux-firmware` 20260319 |
| Sistema | Ubuntu 26.04.1 LTS, kernel `7.0.0-38-generic`, NetworkManager 1.54, TLP, Secure Boot activo |
| Respaldo | Celular por cable USB (`rndis_host`), métrica 700 |

## Fuentes de código usadas

El supervisor no reemplaza ningún driver: se apoya en el código libre que el equipo ya usa y que se leyó para decidir cada remedio.

- **rtw88 del kernel 7.0** (Realtek, licencia BSD/GPL), el driver en uso, sin DKMS (módulos compilados fuera del kernel). Nació en el repositorio de Larry Finger (`lwfinger/rtw88`), de cuyo issue 235 salen las opciones `disable_aspm` y `disable_msi`. Se leyeron `pci.c` (ASPM y CLKREQ), `main.c` (`rtw_fw_recovery`, `disable_lps_deep`), `ps.c` (LPS), `fw.c` y `mac80211.c`.
- **btusb y btrtl del kernel 7.0**: reinicio USB automático de Realtek ante comandos sin respuesta y volcado del firmware.
- **El guardián anterior del equipo** (bash): su escalera reconectar, recargar módulo y reset PCI se conserva, ahora detrás de un diagnóstico y un tope. Su sonda corregida (`ping -I`) queda de reserva.
- **El supervisor de wifi Intel 9560** del mismo autor (`intel-9560-wifi-supervisor`): arquitectura, bitácora, evidencia y protecciones.

## Lo que se descubrió

1. **El guardián anterior trataba toda falta de red igual.** En octubre de 2026 escaló a reset PCI 331 veces; la interfaz llegó a `phy247` de tanto recrearse. Muchas caídas se curaban solas segundos después, o eran del router.
2. **La sonda sin `-I` es ciega con el cable.** Con el celular conectado, un `ping` sin `-I` sale por el cable (o llega al router a través del celular) y da la red por buena con la wifi caída.
3. **TLP le ganaba a NetworkManager.** En perfil batería, TLP activaba `power_save` de la wifi. En `rtw88` eso es LPS. Ver `docs/adr/0003-parametros-rtw88-y-ahorro-de-energia.md`.
4. **El portátil estaba en batería sin saberlo.** Mientras se medía se encontró el cargador desconectado: un servidor así se apaga en pocas horas. Desde ahora cada evento anota cargador y batería.
5. **El cable es buen respaldo para el clúster.** El clúster va por Tailscale, así que sobrevive a la caída de la wifi por el cable. Ver `docs/adr/0002-respaldo-por-cable-usb-del-celular.md`.
6. **Android apaga el anclaje si el puerto USB se reinicia.** La interfaz reaparece, pero ya no hay DHCP. El vigía del cable avisa una vez; solo se reactiva desde el celular.
7. **Reparar el Bluetooth corta el canal de rescate unos segundos.** Por eso una sola lectura mala nunca dispara un remedio. El enlace vuelve en el siguiente ciclo del cliente, cada 5 min.
8. **El patrón de las caídas de la wifi.** De 479 caídas en un mes, 442 empezaron con la tarjeta asociada y con IP, pero sin respuesta ni del router; en la lectura siguiente ya estaba desasociada: el enlace queda mudo y mac80211 lo suelta por balizas perdidas. Se concentran en la tarde y la noche (15 h, 19-20 h), cuando la red de la casa tiene más uso. El equipo estaba con cargador, así que el ahorro de energía no las explica. La mediana duró 78 s y 78 se curaron solas. Por eso cada evento guarda ahora los contadores de la estación (balizas perdidas, envíos fallidos, reintentos, señal): con ellos se podrá separar el radio del punto de acceso.
9. **El journal guardaba menos de un día.** Un `size.conf` viejo (100 MB) se leía después del ajuste de 1 GB y 90 días y lo anulaba, porque los archivos de `journald.conf.d` se aplican en orden alfabético. En un nodo de k3s, 100 MB son unas horas.

## La solución

Un servicio de systemd en Python 3.12+, solo con la biblioteca estándar, en espacio de usuario. Lo que toca el hardware va en procesos hijos con tiempo límite. El porqué está en `docs/adr/0001-supervisor-en-espacio-de-usuario.md`.

| Causa diagnosticada | Remedio, del más suave al más fuerte |
|---|---|
| `desasociado` | reasociar, reiniciar firmware (solo sin lockdown), recargar módulo |
| `zombi` (asociado sin tráfico) | reasociar, reiniciar firmware, recargar módulo, reset PCI |
| `firmware` (chip mudo o crash) | reiniciar firmware, recargar módulo, reset PCI |
| `sin_interfaz` | reset PCI, recargar módulo (sin esperar confirmación) |
| `ap_ausente` | solo reasociar, cada 60 s |
| `proveedor` | nada sobre el hardware |
| Bluetooth sin respuesta HCI (confirmado) | encender, rfkill, religar `btusb`; opcional: `authorized`, `usbreset` |

Protecciones: tope de 4 acciones de hardware por hora guardado en disco; tras una falla del proveedor, 10 min solo reasociar; watchdog de systemd de 300 s; `MemoryMax=150M`, `CPUQuota=30%` y 8 capacidades; cada vuelta en try/except con un respaldo mínimo; cerrojo `flock`. Los supervisores anteriores quedan de reserva con `ExecCondition`: actúan solo si este no está activo o está en `observar`. No arma pánicos ni reinicios automáticos del equipo.

**Registro para encontrar la causa.** `/var/lib/controlador-radio/eventos.jsonl`: una línea JSON por evento con causa, medida por capa (incluida la banda), escenario (carga, memoria, presión de disco, BSSID, frecuencia, salida a internet, cable, cargador, batería) y segundos. La evidencia queda en `eventos/<fecha>-<motivo>/` (kernel filtrado, NetworkManager, `phy_info` y `coex_info` de rtw88, PCI, Bluetooth, USB, volcados del firmware).

## Resultados medidos en el equipo real (2026-11-03)

| Prueba | Resultado |
|---|---|
| Wifi sin internet, red local intacta | tráfico al cable a los 25 s; de vuelta a la wifi ~27 s después de quitar el bloqueo |
| Wifi desconectada 103 s | salida por el cable sin corte, Tailscale directo a 5-8 ms, 3 nodos `Ready` |
| Reasociar / recargar módulo / reset PCI (a mano) | 8,8 s / 10,8 s / 11,8 s, sin perder Tailscale |
| Desasociación real, el demonio repara | wifi de vuelta en 28 s (reasociar) |
| Tarjeta quitada del bus PCI, el demonio repara | wifi de vuelta en 22 s (reset PCI) |
| Bluetooth: encender / rfkill / religar `btusb` | responde en 0 / 4,2 / 6,3 s; el NAP vuelve en el siguiente ciclo del cliente |

| Wifi, antes y después de quitar el ahorro de energía | Antes | Después |
|---|---|---|
| Router: promedio / desviación / máximo | 4,47 / 1,65 / 12,3 ms | 4,30 / 0,97 / 8,5 ms |
| Internet: promedio / máximo / pérdida | 17,3 / 94,7 ms / 1,7 % | 15,7 / 36,4 ms / 0 % |
| iperf3 en la red local, subida / bajada | 145 / 164 Mbit/s | 141 / 149 Mbit/s (igual, dentro del ruido) |

**Intermitencia medida en hora pico (10 min, ping cada 0,2 s, sin cambiar nada):** router con 0,17 % de pérdida, p50 de 4,0 ms, p99 de 66 ms y máximo de 421 ms; internet con 1,1 % de pérdida, p50 de 13,5 ms y p99 de 70 ms. Cero balizas perdidas y ningún corte de más de 1,5 s; el Bluetooth respondió siempre en menos de 10 ms. Los picos más grandes (~450 ms) coinciden con el escaneo de fondo de wpa_supplicant (`bgscan simple:30:-65:300`, uno cada ~310 s): 12 de 31 picos de más de 50 ms. El resto es contención del aire en la red. Fijar el BSSID en el perfil apaga ese escaneo, pero no se aplicó: si el punto de acceso cambia, el servidor se queda sin wifi, y dos picos de medio segundo cada 5 minutos no lo justifican.

**Frente a lo que el equipo da en Windows:** 802.11ac a 5 GHz con 80 MHz y VHT MCS 9 (433 Mbit/s de enlace) se logra, y es el techo del hardware 1x1 (no tiene 160 MHz). La red de la casa solo emite esa SSID en 5 GHz, así que no hay salto entre bandas. Bluetooth 4.2 con LE funciona (roles central y periférico). A2DP es posible (PipeWire activo), pero está apagado a propósito: el Bluetooth del equipo es el canal de rescate, y el audio competiría con el NAP.

## Instalar y adaptar

Requisitos: Linux con NetworkManager, Python 3.12+, `iw`, BlueZ (`bluetoothctl`, `hcitool`). Todo como root.

1. Ajusta `despliegue/config.toml`: interfaz, perfil wifi, PCI, módulo, puerta de enlace, perfil wifi del celular, `bt_usb` (vendedor:producto) y `bt_reponer` (unidades que reponen tu NAP).
2. Estrena en modo observar: `sudo RESERVA="guardian-viejo.service" bash despliegue/instalar.sh observar`. Revisa `journalctl -u controlador-radio -f` y `controlador-radio eventos`.
3. Prueba los remedios con el cable de respaldo conectado: `controlador-radio probar reasociar|recargar-modulo|reset-pci|bt-encender|bt-rfkill|bt-religar`.
4. Pasa a actuar: `sudo bash despliegue/instalar.sh actuar`.
5. Para un servidor en portátil con TLP: el instalador pone `/etc/tlp.d/91-wifi-sin-ahorro.conf`; si `/etc/tlp.conf` fija `WIFI_PWR_ON_*`, coméntala.
6. Deshacer: `sudo controlador-radio-restaurar` (los anteriores vuelven a actuar; respaldos en `/root/respaldo-radio-*.tgz`).

Respaldo por cable (opcional): `despliegue/80-anclaje-usb-respaldo.conf` en `/etc/NetworkManager/conf.d/` deja cualquier anclaje USB con métrica 700, aunque Android cambie la MAC.

```
controlador-radio diagnostico      # mide cada capa y dice la causa, sin tocar nada
controlador-radio estado           # contadores, última medida y Bluetooth
controlador-radio eventos 20       # bitácora: por qué falló, en qué escenario, evidencia
controlador-radio bt estado|reparar
```

## Calidad

`bash scripts/calidad.sh`: formato y estilo con ruff, tipos estrictos con mypy, pruebas con pytest (con un sistema falso, nunca tocan el hardware) y sintaxis de los guiones. Corre igual en GitHub Actions.

## Licencia

MIT. Ver `LICENSE`.

## Control de cambios

| Versión | Fecha | Cambio |
|---|---|---|
| 2.0.0 | 2026-11-03 | Adaptado a rtw88 y Bluetooth Realtek USB: sonda del chip por MMIO, escalera del Bluetooth, respaldo por cable, vigía del cable, ajuste de TLP |
