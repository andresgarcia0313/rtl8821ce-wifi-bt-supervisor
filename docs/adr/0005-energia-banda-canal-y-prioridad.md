<!-- lang: es-CO -->
# 0005 - Energía, elección de banda, canal congestionado y prioridad del tráfico

Idioma: español de Colombia (es-CO). Fecha: 2026-11-04. Estado: aceptada.

## Contexto

Andrés pidió cinco cosas:

- que las funciones de ahorro y de apagado estén disponibles y funcionen bien aunque no se usen;
- la máxima potencia permitida que cumpla el límite de exposición;
- preferir 5 GHz y pasar a 2,4 GHz solo cuando lejos del router rinda mejor;
- aguantar mejor un canal congestionado;
- prioridad para juegos y videollamadas.

Esto se midió en el el equipo de referencia (RTL8821CE con rtw88, Bluetooth 4.2):

| Capacidad | Resultado |
|---|---|
| Tope de potencia por SAR (límite de exposición) | Acepta 4 rangos |
| `iw set txpower` | Sin efecto |
| RTS/CTS | Acepta |
| NAPI en hilo | No la admite |
| Despertar por la red | No lo admite |
| Una sola antena | Sí |
| Comando HCI para que el Bluetooth evite canales | Responde con estado 0 |
| Señal de cada enlace Bluetooth | Relativa al rango ideal (Read RSSI) |
| Calidad del enlace Bluetooth | Siempre 0 |

La casa emite un SSID por banda: la red de 5 GHz en 5 GHz e la red de 2,4 GHz en 2,4 GHz.

## Decisión

1. **Perfiles de energía** (`perfil_energia = "auto"`):

   | Perfil | Cuándo | Ahorro de la wifi | Conexión rápida del Bluetooth |
   |---|---|---|---|
   | rendimiento | con cargador | apagado | sí |
   | equilibrado | en batería | se enciende tras 60 s con menos de 20 paquetes por segundo y se apaga en el acto por encima de 50 | no |
   | ahorro | batería bajo el 30 % | mismo esquema, pero despierta por encima de 200 paquetes por segundo | no |

   El reposo profundo sigue desactivado (ADR 0003). Con cargador, que es el caso del servidor, todo queda como medía el ADR 0003.
2. **Potencia:**
   - Siempre la máxima que permiten la regulación del país y la certificación del equipo. La certificación ya incluye el límite de exposición SAR.
   - Solo si el portátil pasa de 90 grados se pone un tope temporal de 15 dBm por SAR, y se quita al bajar de 78.
3. **Banda:**
   - Baja a 2,4 GHz solo si 5 GHz queda por debajo de -75 dBm durante 60 s y 2,4 GHz le gana al menos 6 dB en un escaneo fresco.
   - Vuelve a 5 GHz con -67 dBm o más, mirando cada 2 min. Entre un cambio y otro hay 5 min de permanencia mínima.
   - Los umbrales salen de Android e iwd.
   - En 2,4 GHz, el Bluetooth aparta los canales de la wifi (AFH, salto de frecuencia adaptativo, por comando HCI estándar).
4. **Canal:**
   - Cada minuto, 5 pings al router distinguen distancia, congestión o canal limpio.
   - Con congestión se enciende RTS/CTS (umbral de 500 bytes) y se apaga tras 10 min de canal limpio.
5. **Prioridad del tráfico:** marcas DSCP que cfg80211 lleva a las colas WMM.

   | Tráfico | Marca | Cola WMM |
   |---|---|---|
   | DNS, hora, ping, SSH interactivo y juegos | EF | voz |
   | Videollamadas y paquetes chicos de Tailscale | AF41 | video |
6. **Aviso instantáneo:**
   - `iw event` avisa de desconexiones, pérdida de balizas, paquetes sin confirmar y señal bajo -75 dBm.
   - Con todo sano la revisión es cada 20 a 30 s; con sospecha, cada 5 s.
7. **Respeto y regreso:**
   - Con la radio apagada a propósito (rfkill) no se repara nada.
   - Al despertar de una suspensión se revisa de inmediato. La señal llega por `set_wakeup_fd`, sin candados dentro del manejador.
   - Si el driver se recarga, se vuelven a aplicar el umbral, el tope, el RTS y el mapa del Bluetooth.

## Alternativas descartadas

- **Subir la potencia por encima del máximo:** el driver lo ignora y lo prohíbe la regulación.
- **Angostar el canal a 40 o 20 MHz:** NetworkManager no lo expone para un cliente.
- **NAPI en hilo y despertar por la red:** el chip no los admite.
- **MLO, AWDL, diversidad de antena y LE Coded:** el hardware no los tiene.
- **Marcar todo Tailscale como voz:** el tráfico pesado del clúster (NFS) se comería la cola de voz, que no agrega paquetes.

## Consecuencias

- **Ahorro en batería:** puede subir la demora de los primeros paquetes al despertar. El umbral de 50 paquetes por segundo lo acota.
- **Restaurar:** `restaurar.sh` deja la radio como la deja el driver (`controlador-radio restablecer-radio`).
- **Perfil de 2,4 GHz:** queda en NetworkManager con prioridad -1. Si se quita `conexion_2g`, el controlador no lo usa, pero NetworkManager sí puede usarlo si 5 GHz no está.
