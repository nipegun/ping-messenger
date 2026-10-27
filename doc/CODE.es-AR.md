# Documentación del código de ping-messenger

Este CODE también está disponible en:\
[en-GB](CODE.en-GB.md), [en-US](CODE.md), es-AR, [es-ES](CODE.es-ES.md)

Referencia técnica del código fuente, pensada para leerse de forma quirúrgica: saltá directamente a la sección que necesitás. Los números de línea se refieren a la versión actual de los scripts.

## Índice

 1. [Arquitectura y decisiones de diseño](#1-arquitectura-y-decisiones-de-diseño)
 2. [Mapa de módulos](#2-mapa-de-módulos)
 3. [Índice de símbolos clave](#3-índice-de-símbolos-clave)
 4. [Flujos principales](#4-flujos-principales)
 5. [Puntos de entrada](#5-puntos-de-entrada)
 6. [Análisis de impacto](#6-análisis-de-impacto)
 7. [Puntos de extensión](#7-puntos-de-extensión)
 8. [Protocolo de comunicación](#8-protocolo-de-comunicación)

## 1. Arquitectura y decisiones de diseño

ping-messenger son dos scripts independientes de Python 3.13 sin dependencias fuera de la biblioteca estándar:

 - `PingMessageSend.py` convierte un archivo en una secuencia de tramas de 16 bytes y envía una trama por cada solicitud de eco ICMP.
 - `PingMessageReceive.py` captura las solicitudes de eco con un socket raw, reconstruye el archivo y confirma su recepción dentro de las respuestas de eco.

Los motivos detrás de la estructura:

 - **Dos scripts de un único archivo, sin módulo compartido.** Cada script se puede copiar por separado a un equipo y ejecutarse. El precio es que el código del protocolo (constantes, `fCrc16`, `fBuildFrame`, `fParseFrame`, `fFindFrames`, `fGetChunkCount`) está duplicado en los dos archivos y **tiene que mantenerse idéntico**. El comentario `Protocol constants (must be identical in ...)` marca el bloque duplicado.
 - **El emisor usa el comando `ping` del sistema, no un socket raw.** Así el emisor no necesita privilegios de root y su tráfico es tráfico normal de `ping -p`. El precio es el tamaño de la carga útil: `ping -p` de iputils acepta como máximo 16 bytes de patrón, así que la trama mide exactamente 16 bytes (`cFrameSize`). Se lanza un proceso por trama (`ping -c 1`), lo que además hace que cada ping sea independiente y permite que el emisor lea la respuesta de cada uno.
 - **La trama se describe y se verifica a sí misma.** Un byte mágico (`0xA7`) y un CRC-16 permiten que el receptor encuentre tramas en cualquier desplazamiento de cualquier carga útil de ping y descarte los datos ajenos o corruptos. `ping` escribe una marca de tiempo antes del patrón, así que el desplazamiento de la trama no es fijo; los dos lados recorren todos los desplazamientos (`fFindFrames`).
 - **Entrega en carrusel en lugar de pedidos de retransmisión.** El único canal de vuelta es la respuesta de eco, así que el emisor no pregunta qué tramas se perdieron: repite el archivo entero en rondas. El receptor guarda las tramas por número de secuencia, ignora los duplicados y puede sumarse en cualquier momento. La trama de cabecera (tamaño y CRC-32 del archivo) se repite cada `--header-every` tramas de datos para que un receptor que llega tarde conozca pronto el tamaño.
 - **Identificador de sesión derivado del contenido.** `fGetSessionId` pliega el CRC-32 de la carga útil en 16 bits, así que enviar el mismo archivo otra vez produce la misma sesión y una transferencia interrumpida continúa donde se detuvo. El receptor usa `(source IP, session)` como clave de su estado, así que se pueden recibir varios emisores y archivos al mismo tiempo.
 - **Confirmación dentro de la respuesta de eco.** Para meter datos en la respuesta, el receptor tiene que construir las respuestas él mismo: pone `net.ipv4.icmp_echo_ignore_all` en `1` mientras se ejecuta, responde cada solicitud de eco dirigida a una dirección local unicast (para que el equipo siga respondiendo al ping) y restaura el valor original en un bloque `finally`. `SIGTERM` y `SIGHUP` se convierten en `SystemExit` para que la restauración también se ejecute con esas señales. Si el equipo ya ignoraba los pings, sólo se responden los pings del protocolo.
 - **Detección del ACK analizando la salida de `ping`.** Cuando los datos de una respuesta difieren de lo enviado, `ping` de iputils imprime `wrong data byte ...` seguido de un volcado hexadecimal de los datos recibidos. El emisor ejecuta `ping` con `LC_ALL=C` y reconstruye los bytes a partir de ese volcado (`fExtractReplyDump`). Esto ata el ACK al formato de salida de iputils; sin él, la transferencia sigue funcionando, limitada por `--rounds`.
 - **Integridad en dos niveles.** CRC-16/CCITT-FALSE por trama (para descartar tramas corruptas) y CRC-32 sobre toda la carga útil (para descartar un archivo corrupto y reconstruirlo en la ronda siguiente).
 - **Compresión sólo cuando ayuda.** La carga útil se comprime con zlib nivel 9 y la versión comprimida se usa sólo si es más chica; un indicador de la cabecera se lo avisa al receptor.
 - **Receptor defensivo.** Los nombres de archivo que vienen de la red se sanean (`fSanitizeFileName`), los archivos se abren con el modo `xb` para que nunca se sobrescriba nada (`fSaveFile`), la descompresión está limitada a 1 GiB (`cMaxDecompressedSize`) y las sesiones silenciosas se purgan después de 10 minutos.
 - **Fechas.** El receptor registra en UTC con el formato de visualización del proyecto, `2026/10/29@13:59:59.723` (`fGetDisplayDate`).

## 2. Mapa de módulos

| Módulo | Ruta | Responsabilidad | Depende de | Usado por |
|---|---|---|---|---|
| PingMessageSend | `PingMessageSend.py` | Construir la carga útil a partir de un archivo, dividirla en tramas, enviar una trama por cada `ping`, detectar el ACK en las respuestas, informar el progreso. | Biblioteca estándar de Python (`argparse`, `binascii`, `os`, `re`, `shutil`, `socket`, `struct`, `subprocess`, `sys`, `time`, `zlib`); el comando `ping` de iputils. | El usuario (línea de comandos). Se comunica con `PingMessageReceive.py` por ICMP. |
| PingMessageReceive | `PingMessageReceive.py` | Capturar solicitudes de eco con un socket raw, reensamblar y verificar archivos, guardarlos, responder los pings y enviar el ACK. | Biblioteca estándar de Python (`argparse`, `binascii`, `datetime`, `ipaddress`, `os`, `signal`, `socket`, `struct`, `sys`, `time`, `zlib`); root o `CAP_NET_RAW`; `/proc/sys/net/ipv4/icmp_echo_ignore_all`. | El usuario (línea de comandos). Recibe de `PingMessageSend.py` por ICMP. |
| Protocolo (duplicado) | Constantes y `fCrc16`, `fGetChunkCount`, `fBuildFrame`, `fParseFrame`, `fFindFrames` en los dos scripts | Formato de la trama, suma de verificación de la trama, búsqueda de tramas. | `binascii`, `struct`. | Los dos scripts. |

## 3. Índice de símbolos clave

### PingMessageSend.py

| Símbolo | Archivo:línea | Qué hace |
|---|---|---|
| Constantes del protocolo | `PingMessageSend.py:29` | `cMagic`, tipos de trama, `cFrameSize`, `cChunkSize`, `cMaxChunks`, `cMaxBlobSize`, `cMaxNameLength`, `cFlagCompressed`. |
| Valores por defecto del emisor | `PingMessageSend.py:41` | `cDefaultHeaderEvery`, `cDefaultInterval`, `cDefaultTimeout`, `cMaxConsecutiveErrors`. |
| `fCrc16` | `PingMessageSend.py:47` | CRC-16/CCITT-FALSE de una cadena de bytes. |
| `fGetChunkCount` | `PingMessageSend.py:52` | Cantidad de tramas de datos de 7 bytes para un tamaño de carga útil. |
| `fGetFramesPerRound` | `PingMessageSend.py:56` | Tramas de datos más tramas de cabecera repetidas en una ronda. |
| `fGetSessionId` | `PingMessageSend.py:60` | Identificador de sesión de 16 bits derivado del CRC-32 de la carga útil. |
| `fBuildFrame` | `PingMessageSend.py:66` | Arma una trama de 16 bytes y le agrega su CRC-16. |
| `fBuildHeaderFrame` | `PingMessageSend.py:72` | Trama de cabecera: tamaño de la carga útil, CRC-32 de la carga útil, indicadores. |
| `fBuildDataFrame` | `PingMessageSend.py:78` | Trama de datos: secuencia de 24 bits y un fragmento de 7 bytes. |
| `fParseFrame` | `PingMessageSend.py:84` | Valida una trama de 16 bytes y devuelve sus campos, o `None`. |
| `fFindFrames` | `PingMessageSend.py:110` | Encuentra todas las tramas válidas en cualquier desplazamiento de una cadena de bytes. |
| `fBuildBlob` | `PingMessageSend.py:123` | Lee el archivo y construye la carga útil (nombre + contenido, comprimida si así es más chica). |
| `fIterRoundFrames` | `PingMessageSend.py:146` | Generador de las tramas de una ronda. |
| `fPing` | `PingMessageSend.py:157` | Ejecuta un `ping -n -c 1 -W T -p HEX` y devuelve el código de salida, stdout y stderr. |
| `fExtractReplyDump` | `PingMessageSend.py:178` | Reconstruye los bytes de la respuesta a partir del volcado `wrong data byte` de `ping` de iputils. |
| `fIsAckReply` | `PingMessageSend.py:197` | Verdadero si la respuesta contiene la trama ACK de la sesión y del CRC de la carga útil. |
| `fResolveTarget` | `PingMessageSend.py:205` | Resuelve el destino a una dirección IPv4. |
| `fPrintProgress` | `PingMessageSend.py:213` | Línea de progreso (sobre la misma línea en una terminal). |
| `fParseArguments` | `PingMessageSend.py:222` | Opciones de línea de comandos y su validación. |
| `fMain` | `PingMessageSend.py:247` | Bucle principal: rondas, pings, detección del ACK, resumen. |
| Bloque `__main__` | `PingMessageSend.py:311` | Códigos de salida e informe de errores. |

### PingMessageReceive.py

| Símbolo | Archivo:línea | Qué hace |
|---|---|---|
| Constantes del protocolo | `PingMessageReceive.py:34` | Los mismos valores que en el emisor (sin `cMaxNameLength`). |
| Ajustes del receptor | `PingMessageReceive.py:45` | Tipos ICMP, `cIpPktInfo`, `cEchoIgnorePath`, tiempos de espera, `cOnceLingerSeconds`, `cMaxDecompressedSize`, `cDefaultFileName`. |
| `fGetDisplayDate` | `PingMessageReceive.py:57` | Fecha UTC actual en el formato de visualización del proyecto. |
| `fLog` | `PingMessageReceive.py:63` | Imprime una línea de registro con la fecha. |
| `fCrc16` | `PingMessageReceive.py:67` | Igual que en el emisor. |
| `fGetChunkCount` | `PingMessageReceive.py:72` | Igual que en el emisor. |
| `fBuildFrame` | `PingMessageReceive.py:76` | Igual que en el emisor. |
| `fBuildAckFrame` | `PingMessageReceive.py:82` | Trama ACK que lleva el CRC-32 de la carga útil. |
| `fParseFrame` | `PingMessageReceive.py:88` | Igual que en el emisor. |
| `fFindFrames` | `PingMessageReceive.py:114` | Igual que en el emisor. |
| `fIcmpChecksum` | `PingMessageReceive.py:127` | Suma de verificación de Internet (RFC 1071). |
| `fBuildEchoReply` | `PingMessageReceive.py:138` | Construye un mensaje ICMP de respuesta de eco. |
| `fBuildAckPayload` | `PingMessageReceive.py:144` | Datos de la respuesta: los bytes de la solicitud anteriores a la primera trama y, a continuación, la trama ACK repetida. |
| `fNewSession` | `PingMessageReceive.py:153` | Diccionario de estado vacío de una transferencia. |
| `fSanitizeFileName` | `PingMessageReceive.py:166` | Hace que un nombre recibido por la red sea seguro para usarlo dentro de la carpeta de salida. |
| `fDecodeBlob` | `PingMessageReceive.py:174` | Descomprime (con un límite) y separa la carga útil en nombre y contenido. |
| `fSaveFile` | `PingMessageReceive.py:192` | Guarda sin sobrescribir (sufijos `.1`, `.2`, ...). |
| `fLogProgress` | `PingMessageReceive.py:207` | Registra el progreso de una transferencia cada 10%. |
| `fCompleteSession` | `PingMessageReceive.py:217` | Une los fragmentos, verifica el CRC-32, decodifica y guarda el archivo. |
| `fProcessFrame` | `PingMessageReceive.py:239` | Actualiza la sesión con una trama de cabecera o de datos; devuelve la trama ACK y la ruta del archivo guardado. |
| `fReceivePacket` | `PingMessageReceive.py:285` | `recvmsg` sobre el socket raw, más las direcciones de `IP_PKTINFO`. |
| `fGetReplySource` | `PingMessageReceive.py:297` | Dirección de origen de la respuesta y si la solicitud era unicast. |
| `fSendEchoReply` | `PingMessageReceive.py:308` | Envía la respuesta desde la dirección a la que se le hizo ping (`IP_PKTINFO`), con `sendto` como alternativa. |
| `fHandlePacket` | `PingMessageReceive.py:324` | Procesa un paquete IP: valida el ICMP, busca tramas, responde. |
| `fPurgeSessions` | `PingMessageReceive.py:357` | Olvida las sesiones que pasaron más de `cSessionTimeout` en silencio. |
| `fReadEchoIgnore` / `fWriteEchoIgnore` | `PingMessageReceive.py:365` / `PingMessageReceive.py:370` | Leen y escriben `icmp_echo_ignore_all`. |
| `fHandleSignal` | `PingMessageReceive.py:375` | Convierte `SIGTERM`/`SIGHUP` en `SystemExit`. |
| `fParseArguments` | `PingMessageReceive.py:380` | Opciones de línea de comandos. |
| `fMain` | `PingMessageReceive.py:390` | Configuración del socket, cambio de echo-ignore, bucle de recepción, restauración. |
| Bloque `__main__` | `PingMessageReceive.py:458` | Manejadores de señales, códigos de salida e informe de errores. |

## 4. Flujos principales

### 4.1 Envío de un archivo

```text
__main__                                   PingMessageSend.py:311
└─ fMain                                   PingMessageSend.py:247
   ├─ fParseArguments                      PingMessageSend.py:222
   ├─ shutil.which('ping')
   ├─ fResolveTarget                       PingMessageSend.py:205
   ├─ fBuildBlob                           PingMessageSend.py:123   (zlib.compress, sólo si el resultado es más chico)
   ├─ zlib.crc32 → fGetSessionId           PingMessageSend.py:60
   ├─ fGetChunkCount / fGetFramesPerRound  PingMessageSend.py:52 / :56
   └─ for each round, until ACK or --rounds:
      └─ fIterRoundFrames                  PingMessageSend.py:146
         ├─ fBuildHeaderFrame / fBuildDataFrame → fBuildFrame → fCrc16
         ├─ fPing                          PingMessageSend.py:157   (ping -n -c 1 -W T -p HEX, LC_ALL=C)
         ├─ fIsAckReply                    PingMessageSend.py:197
         │  └─ fExtractReplyDump → fFindFrames → fParseFrame
         ├─ fPrintProgress                 PingMessageSend.py:213
         └─ time.sleep(--interval)
```

Los códigos de salida `0` (respuesta) y `1` (sin respuesta) de `ping` son normales; cualquier otro código cuenta como error, y `cMaxConsecutiveErrors` errores seguidos abortan la transferencia.

### 4.2 Recepción de un archivo

```text
__main__                                   PingMessageReceive.py:458   (SIGTERM/SIGHUP → fHandleSignal)
└─ fMain                                   PingMessageReceive.py:390
   ├─ fParseArguments                      PingMessageReceive.py:380
   ├─ socket(AF_INET, SOCK_RAW, IPPROTO_ICMP) + IP_PKTINFO
   ├─ fReadEchoIgnore / fWriteEchoIgnore('1')   (salvo con --no-ack)
   ├─ loop:
   │  ├─ fReceivePacket                    PingMessageReceive.py:285
   │  ├─ fHandlePacket                     PingMessageReceive.py:324
   │  │  ├─ fIcmpChecksum                  (sólo solicitudes de eco con una suma de verificación válida)
   │  │  ├─ fFindFrames → fParseFrame      (primera trama de cabecera o de datos de la carga útil)
   │  │  ├─ fProcessFrame                  PingMessageReceive.py:239
   │  │  │  ├─ fNewSession                 (primera trama de un (source IP, session))
   │  │  │  ├─ header: store size, CRC-32, flags, total; restart if they changed
   │  │  │  ├─ data: store the chunk by sequence; fLogProgress
   │  │  │  └─ all chunks present → fCompleteSession
   │  │  │     └─ CRC-32 check → fDecodeBlob → fSaveFile → fSanitizeFileName
   │  │  ├─ fBuildAckPayload               (si la sesión está completada)
   │  │  ├─ fGetReplySource
   │  │  └─ fSendEchoReply → fBuildEchoReply → fIcmpChecksum
   │  └─ fPurgeSessions                    (cada cPurgeInterval segundos)
   └─ finally: fWriteEchoIgnore(original value), socket close
```

### 4.3 Confirmación

1. La trama de datos que completa el archivo llega a `fProcessFrame`, que guarda el archivo y devuelve `fBuildAckFrame(session, CRC-32)`.
2. `fHandlePacket` reemplaza los datos de la respuesta por `fBuildAckPayload`: conserva los bytes anteriores al desplazamiento de la trama (la marca de tiempo de `ping`, para que el tiempo de ida y vuelta se siga calculando) y rellena el resto con la trama ACK repetida.
3. Cada trama posterior de una sesión completada también recibe una respuesta con ACK (`dSession['completed']`), así que el ACK se repite hasta que el emisor se detiene.
4. En el emisor, `ping` ve datos distintos e imprime el volcado `wrong data byte`; `fIsAckReply` encuentra la trama ACK con la misma sesión y el mismo CRC-32, y el bucle principal se detiene.

### 4.4 Inicio y cierre del receptor

 - Inicio: abrir el socket raw (falla sin root) → leer `icmp_echo_ignore_all` → escribir `1` → recordar el valor original. Si el valor original era `1`, sólo se responden los pings del protocolo (`vAnswerAllPings = False`). Si la escritura falla, las confirmaciones se desactivan.
 - `--once`: después del primer archivo guardado, seguir respondiendo durante `cOnceLingerSeconds` (5 s) si las confirmaciones están activadas, y después salir del bucle.
 - Cierre (`Ctrl+C`, `SystemExit` provocado por una señal, `--once`, una excepción): el `finally` de `fMain` vuelve a escribir el valor original y cierra el socket.

## 5. Puntos de entrada

| Comando | Manejador | Archivo |
|---|---|---|
| `PingMessageSend.py -f FILE -t TARGET [-r ROUNDS] [-i INTERVAL] [-W TIMEOUT] [-H HEADER_EVERY] [--no-compress]` | `fMain` (`fParseArguments` para las opciones) | `PingMessageSend.py` |
| `PingMessageReceive.py [-o OUTPUT_DIR] [--no-ack] [--once]` | `fMain` (`fParseArguments` para las opciones) | `PingMessageReceive.py` |

Opciones del emisor (`fParseArguments`, `PingMessageSend.py:222`):

| Opción | Atributo | Por defecto | Validación |
|---|---|---|---|
| `-f`, `--file` | `file` | obligatorio | tiene que ser un archivo existente |
| `-t`, `--target` | `target` | obligatorio | lo resuelve `fResolveTarget` |
| `-r`, `--rounds` | `rounds` | `0` (sin límite) | `>= 0` |
| `-i`, `--interval` | `interval` | `cDefaultInterval` (0.01) | `>= 0` |
| `-W`, `--timeout` | `timeout` | `cDefaultTimeout` (1.0) | `> 0` |
| `-H`, `--header-every` | `header_every` | `cDefaultHeaderEvery` (32) | `>= 1` |
| `--no-compress` | `no_compress` | `False` | |

Opciones del receptor (`fParseArguments`, `PingMessageReceive.py:380`):

| Opción | Atributo | Por defecto |
|---|---|---|
| `-o`, `--output-dir` | `output_dir` | `.` |
| `--no-ack` | `no_ack` | `False` |
| `--once` | `once` | `False` |

Códigos de salida: emisor `0` (terminado, con o sin ACK), `1` (error), `130` (`Ctrl+C`); receptor `0` (`--once`), `1` (error), `130` (`Ctrl+C`), `129`/`143` (`SIGHUP`/`SIGTERM`).

## 6. Análisis de impacto

| Componente | Qué se ve afectado si cambia |
|---|---|
| Constantes del protocolo (`cMagic`, `cType*`, `cFrameSize`, `cChunkSize`, `cMaxChunks`, `cFlagCompressed`) | Los dos scripts tienen que cambiar juntos; las versiones anteriores dejan de ser compatibles. `cFrameSize` no puede superar 16 (límite de `ping -p`). `cChunkSize` está atado a la estructura del cuerpo de datos (10 bytes = 3 de secuencia + 7 de fragmento) y a `cMaxBlobSize`. |
| `fBuildFrame`, `fParseFrame`, `fCrc16` | El formato en la red. Cualquier cambio rompe la compatibilidad; tienen que ser idénticas en los dos scripts. `fParseFrame` devuelve `None` para los tipos desconocidos, así que las versiones anteriores ignoran los tipos nuevos. |
| `fFindFrames` | La usan el receptor en cada solicitud de eco y el emisor en cada volcado de respuesta. Una implementación más lenta enlentece a los dos; una más estricta puede perder tramas en desplazamientos inusuales. |
| `fGetSessionId` | Sólo en el emisor. Cambiarla cambia la sesión de todos los archivos; las reanudaciones desde un emisor anterior no se reconocen (por lo demás, es inofensivo). |
| Estructura de la carga útil (`fBuildBlob` ↔ `fDecodeBlob`) | Byte de longitud del nombre, nombre, contenido, zlib opcional. Los dos extremos tienen que coincidir; `cMaxNameLength` (255) está ligado a la longitud de 1 byte. |
| `fPing` / `fExtractReplyDump` | La detección del ACK depende de la salida de `ping` de iputils y de `LC_ALL=C`. Otra implementación de `ping` u otro formato rompe la detección del ACK (las transferencias siguen funcionando con `--rounds`). |
| `fBuildAckPayload` | Tiene que conservar los bytes anteriores a la trama (la marca de tiempo) para que `ping` acepte la respuesta y calcule el RTT, y tiene que ubicar el ACK donde `ping` vuelca los datos. |
| Manejo de `icmp_echo_ignore_all` en `fMain` (receptor) | Cambia cómo responde a los pings todo el equipo. La restauración está en `finally`; un `SIGKILL` deja el valor en `1`. |
| Lógica de respuesta de `fHandlePacket` (`pAnswerAllPings`, `fGetReplySource`) | Decide qué pings responde el equipo mientras el receptor se ejecuta (sólo unicast, todos o sólo los pings del protocolo). |
| `fSanitizeFileName`, `fSaveFile`, `cMaxDecompressedSize` | Frontera de seguridad del receptor: path traversal, sobrescritura y bombas de descompresión. |
| `fCompleteSession` | Ante un CRC-32 que no coincide o un error de decodificación, borra los fragmentos y espera a la ronda siguiente; cambiarla cambia el comportamiento de recuperación. |
| `cSessionTimeout`, `cPurgeInterval` | Memoria usada por las transferencias abandonadas y durante cuánto tiempo se puede reanudar una transferencia pausada. |

## 7. Puntos de extensión

### Agregar una opción de línea de comandos

1. Agregala en `fParseArguments` del script, con su validación.
2. Usá `vArgs.<attribute>` en `fMain` o pasala hacia abajo como parámetro.
3. Actualizá las tablas de opciones de la [sección 5](#5-puntos-de-entrada), el MANUAL y el README (en todos los idiomas).

### Agregar un tipo de trama

1. Definí `cType<Name>` con el mismo valor en los dos scripts.
2. Agregá la estructura de su cuerpo a `fParseFrame` en los dos scripts (si no, devuelve `None` y la trama se ignora).
3. Receptor: manejalo en `fHandlePacket` (que hoy sólo procesa `cTypeHeader` y `cTypeData` de las solicitudes) o en `fProcessFrame`. Emisor: construilo con `fBuildFrame` y, si viaja en las respuestas, detectalo como lo hace `fIsAckReply`.
4. Documentá la estructura en la [sección 8](#8-protocolo-de-comunicación).

### Agregar un indicador de carga útil (por ejemplo, cifrado)

1. Definí `cFlag<Name>` con el mismo valor en los dos scripts.
2. Activalo en `fBuildBlob` (emisor) y respetalo en `fDecodeBlob` (receptor).
3. Los receptores anteriores ignoran los indicadores desconocidos y guardarían los datos transformados tal cual; si eso no es aceptable, cambiá `cMagic` para que las versiones anteriores ignoren las tramas nuevas.

### Cambiar los límites de la carga útil

`cMaxChunks` está acotado por el número de secuencia de 24 bits, y la cabecera lleva el tamaño en 32 bits. Subir los límites requiere cambiar la estructura del cuerpo de datos o del de cabecera en los dos scripts (consultá la [sección 6](#6-análisis-de-impacto)).

## 8. Protocolo de comunicación

### 8.1 Trama (16 bytes, big endian)

| Desplazamiento | Tamaño | Campo |
|---|---|---|
| 0 | 1 | Byte mágico `0xA7` (`cMagic`) |
| 1 | 1 | Tipo: `0x01` cabecera, `0x02` datos, `0x03` ACK |
| 2 | 2 | Identificador de sesión |
| 4 | 10 | Cuerpo (depende del tipo) |
| 14 | 2 | CRC-16/CCITT-FALSE (polinomio `0x1021`, valor inicial `0xFFFF`) de los bytes 0 a 13 |

### 8.2 Cuerpos (10 bytes)

| Tipo | Estructura |
|---|---|
| Cabecera (`0x01`) | tamaño de la carga útil (4) \| CRC-32 de la carga útil (4) \| indicadores (1, bit `0x01` = zlib) \| reservado (1, `0`) |
| Datos (`0x02`) | secuencia (3) \| fragmento (7, el último rellenado con `0x00`) |
| ACK (`0x03`) | CRC-32 de la carga útil (4) \| reservado (6, `0`) |

### 8.3 Carga útil

Antes de la compresión opcional: `name length (1) | name (UTF-8, up to 255 bytes) | file content`. La carga útil se comprime con zlib nivel 9 sólo si el resultado es más chico, y en ese caso se activa el indicador `0x01` de la cabecera. El CRC-32 de la cabecera y del ACK se calcula sobre la carga útil tal como se transmite (después de la compresión).

Límites: `cMaxChunks = 2^24` tramas de datos de 7 bytes, así que `cMaxBlobSize = 117440512` bytes de carga útil. El receptor limita la carga útil descomprimida a 1 GiB.

### 8.4 Identificador de sesión

`session = ((crc32 >> 16) XOR crc32) AND 0xFFFF`, donde `crc32` es el CRC-32 de la carga útil. El receptor usa `(source IPv4 address, session)` como clave de su estado.

### 8.5 Ronda

```text
header, data 0 ... data 31, header, data 32 ... data 63, header, ...
```

La trama de cabecera se envía antes de cada trama de datos cuya secuencia es múltiplo de `--header-every` (32 por defecto). Tramas por ronda = `chunks + ceil(chunks / header_every)`.

### 8.6 Ubicación dentro de la carga útil ICMP

 - Solicitud: `ping -p <32 hex digits>` llena los datos ICMP con la trama de 16 bytes repetida; `ping` sobrescribe los primeros bytes con su marca de tiempo, así que la primera trama completa no está en un desplazamiento fijo. El receptor usa la primera trama válida de cabecera o de datos que encuentra `fFindFrames`.
 - Respuesta sin ACK: los mismos datos que la solicitud (como respondería el kernel).
 - Respuesta con ACK: los bytes de la solicitud anteriores al desplazamiento de la primera trama, seguidos de la trama ACK repetida hasta la longitud original.
 - En el emisor, `ping` de iputils detecta que los datos de la respuesta difieren y los imprime como líneas `#<offset>\t<hex bytes>`, que `fExtractReplyDump` vuelve a convertir en bytes.
