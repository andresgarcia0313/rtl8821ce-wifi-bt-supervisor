<!-- lang: es-CO -->
# 0004 - Manejo de errores en cada función, ajustes vigilados e itinerancia mínima

Idioma: español de Colombia (es-CO). Fecha: 2026-11-04. Estado: aceptada.

## Contexto

- Los errores se atrapaban por capas: `SistemaReal` nunca lanza, cada paso de `con_respaldo` va en try/except y cada vuelta del demonio también. Un error al leer una salida inesperada dentro de una sonda subía hasta la vuelta y terminaba en el respaldo mínimo, que es reasociar. La sonda no tenía un plan B propio.
- NetworkManager 1.54 programa el escaneo de fondo de wpa_supplicant (`bgscan simple:30:-65:300`) cuando el perfil recuerda más de un BSSID (`seen-bssids`). El perfil de la casa recuerda 3, aunque la red emite un solo punto de acceso. Cada escaneo saca a la tarjeta del canal, y de ahí salen picos de ~450 ms cada ~310 s.
- El Bluetooth tenía `power/control=auto` con `btusb enable_autosuspend=Y`: el kernel lo suspende tras 2 s sin uso. Es una causa conocida de que el Bluetooth Realtek deje de responder.
- El ahorro de energía de la wifi lo volvió a encender TLP una vez (ADR 0003). Nada lo vigilaba.
- Los monitores de otros proyectos (ChromeOS shill, Android, OpenWrt watchcat) prueban el enlace con ARP al router, confirman varias veces antes de actuar y no dependen de un solo destino.

## Decisión

1. **`intentos.resiste(alternativa)`** en cada función pública que habla con el sistema o lee una salida externa (sondas, bluetooth, acciones, red, perfiles, escenario, ajustes, itinerancia). La alternativa recibe los mismos argumentos y da la respuesta útil para el propósito de la función:
   - sonda del chip: vivo;
   - prueba del Bluetooth: no se sabe (`None`);
   - enlace: el `operstate` de la interfaz;
   - medida completa: una medida mínima;
   - remedio: no lo logró.

   Ninguna alternativa lleva a tocar el hardware a ciegas. Si la alternativa también falla, el error sube a la capa de arriba, que tiene su propio respaldo. Las funciones puras (diagnóstico, cálculos) no llevan el decorador: un error ahí es un fallo de programación y lo atrapa la vuelta. Una prueba con `ast` falla si una función pública de esos módulos queda sin su alternativa.
2. **ARP al router** (`arping`) además del ping: un router ocupado puede ignorar ICMP y aun así el enlace funciona.
3. **`ajustes.Ajustes`**, cada 5 min: ahorro de energía de la wifi apagado y `power/control=on` en el Bluetooth USB. Si alguno se desvió, lo corrige y lo anota; en `observar` solo lo anota. La regla udev `81-bluetooth-sin-suspension.rules` lo deja puesto desde el arranque.
4. **`itinerancia.Itinerancia`** (`fijar_bssid`, apagado por defecto): fija el BSSID en el perfil y así NetworkManager deja de programar el escaneo de fondo. Condiciones para fijarlo:
   - la wifi lleva 10 min sana;
   - el SSID tiene un solo punto de acceso visible;
   - el cable de respaldo es útil.

   Si la wifi no vuelve con el punto de acceso fijado, se deja como estaba. Si el punto fijado deja de verse, se suelta antes del remedio de esa misma vuelta.
5. **`OnFailure=controlador-radio-caido.service`**: manda un aviso cuando systemd deja de reiniciar el demonio.

## Alternativas descartadas

- **try/except literal en cada función, incluidas las puras.** Esconde errores de programación y repite el respaldo que ya da la capa de arriba.
- **Cambiar `bgscan` por D-Bus en wpa_supplicant.** NetworkManager lo reescribe en cada conexión, y es una interfaz interna.
- **Borrar `seen-bssids`.** Exige reiniciar NetworkManager y el perfil vuelve a aprender BSSID.
- **Fijar el BSSID a mano.** Si el router cambia, el servidor queda sin wifi. Esa fue la razón para no aplicarlo el 2026-11-03.

## Consecuencias

- **Costo de la fijación:** aplicarla reconecta la wifi unos segundos, una vez. Por eso exige el cable útil.
- **Si hay varios puntos de acceso:** con una red de varios puntos de acceso (malla), la fijación no se aplica y la itinerancia queda como estaba.
- **Dependencia nueva:** `arping` (paquete `iputils-arping`). Sin él, `arp` devuelve falso y manda el ping, como antes.
