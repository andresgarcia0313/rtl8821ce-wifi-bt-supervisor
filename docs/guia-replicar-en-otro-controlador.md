<!-- lang: es-CO -->
# Guía para replicar el supervisor de radio en otro equipo

Idioma: español de Colombia (es-CO). Versión 1.0, 2026-11-04. Autor: Andrés García.

Esta guía reúne las funciones y características del supervisor de wifi y Bluetooth (versión 2.1.0) y los pasos para hacer lo mismo con otro adaptador, por ejemplo un Intel con iwlwifi o un Mediatek con mt76. El supervisor es un programa en espacio de usuario: no modifica el driver del kernel, sino que lo vigila, lo ajusta y lo repara.

## 1. Qué hace y para qué

| Función | Para qué sirve | Dónde está |
|---|---|---|
| Diagnóstico por capas: interfaz, chip, asociación, punto de acceso visible, router, internet | Reparar solo donde está la falla; si el router o el proveedor fallan, no se toca la tarjeta | `sondas.py`, `diagnostico.py` |
| Remedios escalonados: reasociar, reiniciar firmware, recargar módulo, reiniciar el bus PCI (bus de conexión de componentes de la placa) | Usar siempre el remedio más suave que funcione | `acciones.py`, `politica.py` |
| Tope de acciones de hardware por hora, guardado en disco | Evitar tormentas de reinicios | `politica.py`, `registro.py` |
| Confirmación antes de actuar (histéresis) | No reparar por una lectura suelta | `principal.py` |
| Bluetooth: prueba de vida con un comando estándar HCI (interfaz del controlador anfitrión) y escalera: encender, rfkill, religar btusb | Saber de verdad si el chip responde y repararlo sin reiniciar | `bluetooth.py`, `vigia_bt.py` |
| Espera creciente entre intentos del Bluetooth (hasta 12 h) y aviso una sola vez por episodio | No reparar en bucle ni repetir avisos | `vigia_bt.py` |
| Respaldo de internet por el cable USB (bus serie universal) del celular, reconocido por driver | Que el servidor siga en línea si la wifi cae, aunque cambie la MAC (dirección física de la interfaz) | `respaldo.py`, `escenario.py`, `80-anclaje-usb-respaldo.conf` |
| Escucha de los mensajes del kernel en vivo | Detectar el fallo de firmware al instante | `kmsg.py` |
| Bitácora de eventos con escenario y evidencia por episodio | Encontrar la causa de cada falla después | `eventos.py`, `episodios.py`, `evidencia.py` |
| Manejo de errores con alternativa en cada función que habla con el sistema | Que ningún error deje al supervisor ciego ni lo lleve a tocar el hardware a ciegas | `intentos.resiste` |
| Router probado por ping y por ARP (protocolo de resolución de direcciones) | No confundir un router ocupado con un cuelgue de la tarjeta | `sondas.router_responde` |
| Ajustes vigilados: ahorro de energía de la wifi apagado y Bluetooth sin suspensión USB | Que otro programa no deshaga los ajustes que evitan pérdidas | `ajustes.py`, `81-bluetooth-sin-suspension.rules` |
| Itinerancia mínima: punto de acceso fijado con liberación automática | Quitar el escaneo de fondo, que causaba picos de demora | `itinerancia.py` |
| Servicio de systemd con watchdog, límites de memoria y CPU (procesador), mínimas capacidades y aviso si se rinde | Que el supervisor nunca cargue el equipo y que alguien se entere si cae | `controlador-radio.service`, `controlador-radio-caido.service` |
| Modo observar | Estrenar cambios sin tocar nada | `config.py` |
| Supervisores anteriores de reserva (`ExecCondition`) | Que haya alguien vigilando si este supervisor no corre | `reserva.conf` |

## 2. Pasos para otro adaptador

1. **Identificar el hardware y el driver:** `lspci -nnk`, `lsusb`, `modinfo <módulo>`, versión del kernel y del firmware, si hay Secure Boot (lockdown) y si la tarjeta es combo wifi y Bluetooth.
2. **Leer el código del driver en el kernel que corre:** parámetros del módulo, qué expone en debugfs y qué permite el lockdown, cómo se recupera solo el firmware y qué mensajes escribe cuando falla.
3. **Elegir la prueba de vida del chip:**
   - rtw88: leer registros mapeados en memoria, MMIO (memory-mapped input/output, `mac_0`; todo `ffffffff` = chip fuera del bus).
   - iwlwifi: temperatura del firmware.
   - Si no hay ninguna, `iw dev <interfaz> info`.
4. **Ajustar en `config.py`:** el módulo, la dirección PCI, la interfaz, el identificador (ID) USB del Bluetooth y la expresión de los mensajes de fallo del kernel en `kmsg.py`.
5. **Revisar qué remedios existen:** el reinicio del firmware solo vale si el driver lo ofrece y el lockdown lo deja. Si un paso no se puede probar sin riesgo, se deja apagado por defecto.
6. **Probar cada remedio a mano antes de automatizarlo** (`controlador-radio probar <remedio>`), siempre con el cable de respaldo ya probado y con restauración condicional programada.
7. **Medir antes de cambiar:** 10 minutos de ping cada 0,2 s al router y cada 0,5 s a internet, más los escaneos con `iw event -t`. Se repite después de cada cambio, a la misma hora del día.
8. **Estrenar en modo observar** y luego pasar a actuar.
9. **Pedir una revisión independiente** del código y corregir los hallazgos.
10. **Publicar una copia saneada,** commit por commit:
    - quitar la configuración del equipo y el plan privado;
    - poner una IP (dirección de red) de documentación en vez de la real;
    - buscar MAC con y sin dos puntos, interfaces `enx`, IP privadas, nombres de redes y de equipos en toda la historia;
    - usar `rsync --checksum`.

## 3. Lo que se aprendió y conviene revisar primero en cualquier equipo

- **Gestores de energía:** TLP (gestor de energía para portátiles con Linux) u otro gestor puede encender el ahorro de energía de la wifi en batería, y eso causó 1,7 % de paquetes perdidos. Hay que revisar `iw dev <interfaz> get power_save`, no solo lo que dice NetworkManager.
- **Escaneo de fondo:** NetworkManager programa escaneo de fondo cada 300 s si el perfil recuerda más de un BSSID (identificador del punto de acceso). Se revisa con `nmcli -g 802-11-wireless.seen-bssids connection show <perfil>`.
- **Suspensión del Bluetooth:** btusb deja el Bluetooth en `power/control=auto`.
- **Ping por la interfaz:** un ping sin `-I <interfaz>` sale por el cable y da por buena una wifi caída.
- **Puerto USB del Bluetooth:** cortarlo puede dejar el Bluetooth sin volver hasta reiniciar (pasó en otro equipo). Por eso `authorized` y `usbreset` quedan apagados por defecto.
- **Restauraciones automáticas:** deben ser condicionales. Una reconexión ciega cortó una wifi sana.
- **Journald:** revisar que guarde suficientes días; un archivo viejo de `journald.conf.d` anulaba la retención.

## 4. Errores frecuentes de otros proyectos que se evitan

Reiniciar la tarjeta ante cualquier falta de internet, vigilar con un solo destino, reparar en bucle, itinerancia agresiva, escaneos frecuentes, creer que los ajustes de energía lo curan todo y probar el plan B por primera vez el día de la falla real.

## 5. Resultados de referencia (el equipo de referencia, RTL8821CE en 5 GHz, 2026-11-04)

| | Antes | Después |
|---|---|---|
| Router: pérdida / p99 / máximo | 0,47 % / 69 ms / 777 ms | 0 % / 24 ms / 106 ms |
| Internet: pérdida / p99 / máximo | 1,33 % / 133 ms / 871 ms | 0,75 % / 40 ms / 54 ms |

Costo del supervisor: unos 12 MB de memoria y menos del 1 % de un núcleo, con una revisión cada 5 s.

## Control de cambios

| Versión | Fecha | Autor | Descripción del cambio |
|---|---|---|---|
| 1.0 | 2026-11-04 | Andrés García | Primera versión, a partir del supervisor 2.1.0 |
