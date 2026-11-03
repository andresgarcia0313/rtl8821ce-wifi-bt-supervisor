<!-- lang: es-CO -->
# 0001 - Supervisor en espacio de usuario sobre el driver rtw88 del kernel

Idioma: español de Colombia (es-CO). Fecha: 2026-11-03. Estado: aceptada.

## Contexto

La wifi Realtek RTL8821CE de un portátil que es plano de control de k3s se caía sin dejar rastro en el kernel. El guardián en bash que había reconectaba, recargaba el módulo y hacía reset PCI ante cualquier falta de red: en octubre de 2026 sumó 321, 218 y 331 acciones respectivamente. Se buscaba un controlador mejor, sin riesgo de congelar el equipo. Revisamos:

- **El driver.** El equipo usa `rtw88_8821ce` del propio kernel 7.0 (Realtek, BSD/GPL), sin DKMS. Es el mismo código que nació en `lwfinger/rtw88`: no hay un driver mejor fuera del kernel para este chip, y uno fuera del kernel se rompe en cada actualización.
- **El firmware.** `rtw8821c_fw.bin` (WL 24.11) viene en `linux-firmware`. Es un binario de Realtek: no se modifica.
- **El Bluetooth.** `btusb` + `btrtl` del kernel 7.0 ya reinician solos el adaptador por USB cuando un comando no responde (`btusb_rtl_reset`).

## Decisión

Un supervisor en Python, solo con la biblioteca estándar y como servicio de systemd. Mide por capas, diagnostica la causa y aplica remedios escalonados con respaldo y tope por hora. Usa las vías oficiales: `nmcli`, `modprobe`, `sysfs` de PCI y USB, `rfkill`, comandos HCI y lectura de debugfs (`mac_0`, que con lockdown sigue disponible por ser 0444).

## Alternativas descartadas

- **Parchear rtw88 (DKMS).** No hay un error del driver identificado que corregir, y un fallo en el kernel sí congela el equipo.
- **Seguir con el guardián en bash.** No distinguía causas ni tenía tope. Además quedó ciego con el cable del celular: su `ping` sin `-I` salía por el cable.
- **Watchdog de hardware y pánico por bloqueo.** El equipo no tiene `/dev/watchdog` y es el maestro del clúster: un pánico automático lo reiniciaría sin que nadie lo pidiera. Se deja fuera.

## Consecuencias

- Un error del supervisor solo lo afecta a él. systemd lo reinicia, y los supervisores anteriores quedan de reserva con `ExecCondition`.
- Con Secure Boot no existe el reinicio suave del firmware (`fw_crash` se bloquea), así que la escalera salta de reasociar a recargar el módulo. Medido: 10,8 s, y el reset PCI 11,8 s.
- La bitácora con escenario por evento deja datos para encontrar la raíz de las caídas. Hoy no se sabe si son del punto de acceso, del ahorro de energía o del chip.
