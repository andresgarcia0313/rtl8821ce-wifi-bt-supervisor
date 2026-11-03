<!-- lang: es-CO -->
# 0003 - Parámetros de rtw88 y ahorro de energía de la wifi, según el código del kernel 7.0

Idioma: español de Colombia (es-CO). Fecha: 2026-11-03. Estado: aceptada.

## Contexto

El equipo tenía, desde diciembre de 2025, `rtw88_core disable_lps_deep=y` y `rtw88_pci disable_msi=y disable_aspm=y` (issue 235 de `lwfinger/rtw88`, por errores PCIe RxErr). La wifi daba 24 a 41 ms a internet, contra 17 ms del cable del celular. Se revisó el código de rtw88 en el kernel 7.0 para saber qué hace cada parámetro.

## Hallazgos en el código

- `disable_aspm` (`pci.c`, `rtw_pci_aspm_set` y `rtw_pci_clkreq_set`): con Y, el driver nunca enciende la lógica L1 y CLKREQ del propio chip. `lspci` sigue mostrando `ASPM L0s L1 Enabled`, porque eso es del lado del host. El parámetro sí actúa: el chip no entra en L1 por su cuenta.
- `disable_msi`: usa interrupciones INTx en vez de MSI. Se conserva, porque fue la corrección de los RxErr y no hay datos para quitarla.
- `disable_lps_deep` (`main.c` y `ps.c`): solo anula el modo profundo de LPS. LPS solo se activa si mac80211 tiene el ahorro de energía encendido (`ps_enabled`). Sin ahorro de energía, este parámetro no cambia nada.
- **Ahorro de energía:** NetworkManager tenía `wifi.powersave=2` (apagado), pero `iw` mostraba `Power save: on`. TLP lo activaba en perfil batería (`WIFI_PWR_ON_BAT=on`) en cada cambio de fuente. En rtw88 eso enciende LPS: la tarjeta duerme entre balizas.

## Decisión

- `/etc/tlp.d/91-wifi-sin-ahorro.conf` con `WIFI_PWR_ON_AC=off` y `WIFI_PWR_ON_BAT=off`, y comentar la línea de `/etc/tlp.conf` que lo fijaba, porque ese archivo le gana a `tlp.d`.
- Se conservan los parámetros de modprobe.

## Medido (60 pings cada 0,5 s y iperf3 de 10 s contra otro equipo de la red local)

| | Antes | Después |
|---|---|---|
| Router, promedio / desviación / máximo | 4,47 / 1,65 / 12,3 ms | 4,30 / 0,97 / 8,5 ms |
| Internet, promedio / máximo / pérdida | 17,3 / 94,7 ms / 1,7 % | 15,7 / 36,4 ms / 0 % |
| iperf3 subida / bajada | 145 / 164 Mbit/s | 141 / 149 Mbit/s |

## Consecuencias

- Menos pérdida y menos picos de latencia; el rendimiento no cambia, porque está limitado por el aire (1x1, 80 MHz, MCS 9).
- La tarjeta gasta un poco más de energía. En un servidor eso no importa, salvo que esté en batería, y entonces el problema es otro: el cargador.
