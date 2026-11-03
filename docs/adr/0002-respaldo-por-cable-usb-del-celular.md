<!-- lang: es-CO -->
# 0002 - Respaldo de internet por el cable USB del celular

Idioma: español de Colombia (es-CO). Fecha: 2026-11-03. Estado: aceptada.

## Contexto

El celular quedó conectado por cable USB con anclaje (`rndis_host`). NetworkManager le dio métrica 100 y se volvió la salida principal. El clúster usa Tailscale para todo: `node-ip`, `flannel-iface tailscale0` y los volúmenes NFS por el nombre del tailnet. El servicio que ya había (red escalonada) pasaba la wifi a la red del celular cuando faltaba internet, lo que saca al equipo de la red local.

## Decisión

- El cable es respaldo por ruteo: métrica 700 contra 600 de la wifi, con la verificación de conectividad de NetworkManager (la salida sin internet recibe +20000).
- `80-anclaje-usb-respaldo.conf` fija la métrica por driver (`rndis_host`, `cdc_ether`, `cdc_ncm`, `ipheth`) y el perfil del cable se ata al driver, no a la MAC. Android cambia la MAC en cada anclaje, y el enlace Bluetooth también se llama `enx<mac>`.
- Con el cable útil, el supervisor no mueve la wifi ni sube el Bluetooth del celular. Sin cable y con el router ausente, mantiene el comportamiento anterior: wifi del celular a los 180 s.
- El vigía del cable avisa una vez si el cable sigue conectado pero sin dirección.

## Medido

- Wifi sin internet y red local intacta: tráfico al cable a los 25 s y de vuelta ~27 s después.
- Wifi desconectada 103 s: sin corte; Tailscale siguió directo con los demás nodos a 5-8 ms, a través del celular; los nodos siguieron `Ready`.
- Reinicio lógico del puerto USB del celular (`authorized` 0/1): la interfaz volvió con su perfil y métrica, pero Android apagó el anclaje y ya no hubo DHCP. Solo se reactiva desde el celular.

## Alternativas descartadas

- **Sumar wifi y cable (ECMP).** Medido en otro equipo de la casa: peor que la wifi sola, porque el enlace lento frena todo.
- **Pasar la wifi a la red del celular.** Corta la red local y no protege más que el cable.

## Consecuencias

- Si el celular está conectado a la wifi de la casa, sale con la misma IP pública: el cable protege contra fallas del radio del servidor, no contra caídas del proveedor. Para eso el celular tendría que salir por datos móviles.
- Tras reiniciar el equipo o el puerto USB, hay que reactivar el anclaje en el celular.
