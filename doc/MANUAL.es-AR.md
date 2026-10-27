# Manual de usuario de ping-messenger

Este MANUAL también está disponible en:\
[en-GB](MANUAL.en-GB.md), [en-US](MANUAL.md), es-AR, [es-ES](MANUAL.es-ES.md)

## Contenido

 1. [Qué hace ping-messenger](#1-qué-hace-ping-messenger)
 2. [Antes de empezar](#2-antes-de-empezar)
 3. [Inicio rápido](#3-inicio-rápido)
 4. [El receptor: PingMessageReceive.py](#4-el-receptor-pingmessagereceivepy)
 5. [El emisor: PingMessageSend.py](#5-el-emisor-pingmessagesendpy)
 6. [Tareas habituales](#6-tareas-habituales)
 7. [Ajuste de la transferencia](#7-ajuste-de-la-transferencia)
 8. [Solución de problemas](#8-solución-de-problemas)
 9. [Limitaciones y seguridad](#9-limitaciones-y-seguridad)

## 1. Qué hace ping-messenger

ping-messenger lleva un mensaje de texto o un archivo de una computadora (el **emisor**) a otra (el **receptor**) usando únicamente paquetes `ping`. Desde el punto de vista de la red, el emisor simplemente le está haciendo ping al receptor muchas veces.

 - En el emisor ejecutás `PingMessageSend.py`. No necesita root.
 - En el receptor ejecutás `PingMessageReceive.py`. Necesita root.

El receptor tiene que iniciarse primero, o al menos antes de que el emisor termine, pero no importa si arranca cuando el emisor ya está enviando: el emisor repite el archivo en **rondas** hasta que el receptor confirma que lo tiene.

## 2. Antes de empezar

Verificá estos puntos en las dos computadoras:

| Verificación | Emisor | Receptor |
|---|---|---|
| Python 3.13 o posterior (`python3 --version`) | Sí | Sí |
| `ping` de `iputils-ping` (`ping -V` muestra `ping from iputils ...`) | Sí | No |
| Usuario root, o la capacidad `CAP_NET_RAW` | No | Sí |
| Conectividad IPv4 entre las dos computadoras | Sí | Sí |
| Ningún firewall que descarte las solicitudes y respuestas de eco ICMP | Sí | Sí |

En Debian, como `root`:

```bash
apt-get update
apt-get install -y python3 iputils-ping
install -m 755 PingMessageSend.py PingMessageReceive.py /usr/local/bin/
```

También podés ejecutar los scripts desde cualquier carpeta sin instalarlos, por ejemplo `./PingMessageSend.py ...`.

Una prueba rápida: desde el emisor, `ping -c 3 <receiver IP>` tiene que recibir respuestas antes de que pruebes ping-messenger.

## 3. Inicio rápido

1. **Receptor** (como `root`):

   ```bash
   PingMessageReceive.py -o /root/received
   ```

   Muestra algo como:

   ```text
   [2026/10/27@10:45:12.345] Listening for ICMP echo requests, files will be saved to "/root/received"
   [2026/10/27@10:45:12.346] Acknowledgements enabled: /proc/sys/net/ipv4/icmp_echo_ignore_all set to 1 while the receiver runs
   ```

2. **Emisor**:

   ```bash
   echo "Hello from ping-messenger" > hello.txt
   PingMessageSend.py -f hello.txt -t 192.168.1.20
   ```

   Muestra algo como:

   ```text
   File:       hello.txt (26 bytes)
   Target:     192.168.1.20 (192.168.1.20)
   Session:    0x3f2a
   Payload:    36 bytes (uncompressed), 6 data frames
   Round:      7 pings (header every 32 data frames)
   Rounds:     unlimited, until the receiver acknowledges
   Round 1: ping 7/7 (100.0%), replies: 7
   Pings sent: 7, replies: 7, elapsed: 0.3 s
   The receiver acknowledged the file. Transfer complete.
   ```

3. **Receptor** otra vez: el archivo está en `/root/received/hello.txt`, y el registro muestra:

   ```text
   [2026/10/27@10:45:20.101] 192.168.1.10 0x3f2a: new transfer detected
   [2026/10/27@10:45:20.102] 192.168.1.10 0x3f2a: header received (36 bytes, uncompressed, 6 data frames)
   [2026/10/27@10:45:20.150] 192.168.1.10 0x3f2a: 1/6 data frames (10%)
   ...
   [2026/10/27@10:45:20.390] 192.168.1.10 0x3f2a: file saved to "/root/received/hello.txt" (26 bytes)
   ```

4. Presioná `Ctrl+C` en el receptor cuando no esperes más archivos.

Los números de arriba son un ejemplo: la sesión, los tamaños y los tiempos cambian con cada archivo.

## 4. El receptor: PingMessageReceive.py

```text
PingMessageReceive.py [-o OUTPUT_DIR] [--no-ack] [--once]
```

| Opción | Por defecto | Qué hace |
|---|---|---|
| `-o`, `--output-dir` | Carpeta actual | Carpeta donde se guardan los archivos recibidos. Se crea si no existe. |
| `--no-ack` | Desactivado | No responder los pings ni enviar confirmaciones. El sistema operativo sigue respondiendo los pings como siempre. El emisor nunca va a saber que el archivo llegó, así que usá `-r` en el emisor. |
| `--once` | Desactivado | Salir después de guardar el primer archivo. Con las confirmaciones activadas, sigue respondiendo durante 5 segundos más para que el emisor reciba la confirmación. |
| `-h`, `--help` | | Mostrar la ayuda y salir. |

### Qué hace el receptor

 - Escucha cada ping que llega a la computadora y busca adentro datos de ping-messenger. Los pings normales se ignoran (pero igual se responden; mirá más abajo).
 - Puede recibir varios archivos al mismo tiempo, del mismo emisor o de emisores distintos. Cada transferencia se identifica por la dirección IP del emisor y un número de **sesión** (que aparece como `0x3f2a` en el registro). Enviar el mismo archivo otra vez produce la misma sesión.
 - Registra el progreso cada 10% del archivo.
 - Cuando llegaron todos los pedazos, verifica el archivo entero con una suma de verificación CRC-32. Si la verificación falla, descarta los pedazos y reconstruye el archivo a partir de la ronda siguiente.
 - Las transferencias que pasan 10 minutos en silencio se olvidan.

### Dónde se guardan los archivos

 - Cada archivo se guarda en la carpeta de salida con el nombre que tenía en el emisor.
 - Nunca se sobrescribe un archivo existente: si `hello.txt` ya existe, el nuevo se guarda como `hello.txt.1`, después `hello.txt.2`, y así sucesivamente.
 - Las barras del nombre se reemplazan por `_`, así que nunca se puede escribir un archivo fuera de la carpeta de salida. Un archivo sin un nombre utilizable se guarda como `received.bin`.

### Las confirmaciones y las respuestas a los pings

Por defecto, el receptor responde él mismo los pings en lugar del sistema operativo. Así es como mete la confirmación dentro de las respuestas:

 - Al arrancar, pone `/proc/sys/net/ipv4/icmp_echo_ignore_all` en `1` (el kernel deja de responder los pings) y recuerda el valor anterior.
 - Mientras se ejecuta, responde cada ping dirigido a la computadora, así que la computadora sigue respondiendo al ping como antes. Si la computadora ya ignoraba los pings antes, sólo responde los pings de ping-messenger.
 - Los pings enviados a direcciones de broadcast o multicast no se responden.
 - Cuando se detiene (`Ctrl+C`, `--once`, `SIGTERM` o `SIGHUP`), restaura el valor anterior y registra `... restored to 0`.

Si no puede cambiar ese ajuste (por ejemplo en algunos contenedores, donde `/proc/sys` es de sólo lectura), registra una advertencia y continúa con las confirmaciones desactivadas, como si se hubiera indicado `--no-ack`.

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | Se indicó `--once` y se recibió un archivo. |
| `1` | Error (por ejemplo, no se está ejecutando como root). |
| `129` / `143` | Detenido por `SIGHUP` / `SIGTERM`. |
| `130` | Detenido con `Ctrl+C`. |

## 5. El emisor: PingMessageSend.py

```text
PingMessageSend.py -f FILE -t TARGET [-r ROUNDS] [-i INTERVAL] [-W TIMEOUT] [-H HEADER_EVERY] [--no-compress]
```

| Opción | Por defecto | Qué hace |
|---|---|---|
| `-f`, `--file` | Obligatorio | Archivo a enviar. De texto o binario. |
| `-t`, `--target` | Obligatorio | Dirección IPv4 o nombre de host de la computadora que ejecuta `PingMessageReceive.py`. |
| `-r`, `--rounds` | `0` | Cantidad máxima de veces que se envía el archivo entero. `0` significa "repetir hasta que el receptor confirme". |
| `-i`, `--interval` | `0.01` | Segundos de espera entre un ping y el siguiente. |
| `-W`, `--timeout` | `1` | Segundos de espera para la respuesta de cada ping. |
| `-H`, `--header-every` | `32` | Repetir la cabecera (tamaño del archivo y suma de verificación) cada N pedazos del archivo. |
| `--no-compress` | Desactivado | No comprimir el archivo antes de enviarlo. |
| `-h`, `--help` | | Mostrar la ayuda y salir. |

### Qué muestra el emisor

 - **File**: el archivo y su tamaño.
 - **Target**: el destino tal como lo escribiste y la dirección IP a la que se resuelve.
 - **Session**: el número de sesión. El receptor muestra el mismo número en su registro.
 - **Payload**: los bytes que realmente van a viajar (nombre + contenido, comprimidos si eso los achicó) y la cantidad de tramas de datos (una por ping, de 7 bytes cada una).
 - **Round**: la cantidad de pings de una ronda (tramas de datos más tramas de cabecera).
 - **Rounds**: el límite de rondas.
 - Una línea de progreso con la ronda actual, el ping y la cantidad de respuestas recibidas. En una terminal, se actualiza sobre la misma línea.
 - Un resumen final con los pings enviados, las respuestas y el tiempo que tardó, seguido de si el receptor confirmó el archivo.

### Cuándo se detiene

 - Cuando una respuesta trae la confirmación del receptor: `The receiver acknowledged the file. Transfer complete.`
 - Cuando se enviaron las rondas indicadas con `-r` sin ninguna confirmación: `All the rounds were sent without an acknowledgement from the receiver.` Esto no significa que el archivo se haya perdido; sólo significa que el emisor no recibió una confirmación (por ejemplo, porque el receptor se ejecuta con `--no-ack`).
 - Cuando `ping` falla 10 veces seguidas con un error real (no un simple "sin respuesta"), se detiene con un error.
 - Cuando presionás `Ctrl+C`.

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | Terminó: confirmado, o se enviaron todas las rondas. Fijate en la última línea para saber cuál de los dos casos fue. |
| `1` | Error (archivo no encontrado, el destino no se puede resolver, `ping` no está instalado o falla...). |
| `130` | Detenido con `Ctrl+C`. |

## 6. Tareas habituales

### Enviar un mensaje de texto corto

```bash
echo "The backup finished at 03:00" > message.txt
PingMessageSend.py -f message.txt -t 192.168.1.20
```

En el receptor, leelo con `cat /root/received/message.txt`.

### Recibir exactamente un archivo y salir

```bash
PingMessageReceive.py -o /root/received --once
```

Útil en scripts: cuando el comando termina, el archivo ya está guardado.

### Enviar sin confirmaciones

Cuando el receptor no puede responder los pings (se ejecuta con `--no-ack`, o en un contenedor donde no puede cambiar `/proc/sys`), limitá la cantidad de rondas para que el emisor no se ejecute para siempre:

```bash
PingMessageSend.py -f message.txt -t 192.168.1.20 -r 3
```

Más rondas dan más oportunidades de recuperar los pings perdidos.

### Enviar un archivo binario

Funciona con cualquier archivo, por ejemplo `PingMessageSend.py -f photo.jpg -t 192.168.1.20`. Los archivos que ya están comprimidos (JPEG, ZIP...) se envían sin comprimir automáticamente, porque comprimirlos otra vez no los achicaría.

## 7. Ajuste de la transferencia

 - **Velocidad**: cada ping lleva 7 bytes. Una ronda necesita unos `payload / 7` pings más una cabecera cada 32 pings. Si bajás `-i` (por ejemplo `-i 0`), envía más rápido, pero puede perder más pings en redes lentas o cargadas; los pings perdidos se recuperan en la ronda siguiente.
 - **Enlaces lentos**: si las respuestas llegan tarde, subí `-W` (por ejemplo `-W 3`). Un ping sin respuesta no es un error: la solicitud puede haber llegado igual al receptor.
 - **Receptores que arrancan tarde**: la cabecera se repite cada 32 tramas de datos para que un receptor que arranca en la mitad de una ronda conozca enseguida el tamaño del archivo. Bajá `-H` para repetirla más seguido (más pings por ronda) o subilo para enviar menos pings.
 - **Compresión**: está activada por defecto y sólo se usa cuando achica la carga útil. `--no-compress` sólo sirve para comparar tamaños.
 - **Tamaño máximo**: la carga útil (después de la compresión) puede llegar a 117.440.512 bytes (unos 112 MiB), pero en la práctica ping-messenger está pensado para archivos mucho más chicos.

## 8. Solución de problemas

| Mensaje o síntoma | Causa y solución |
|---|---|
| `Error: a raw ICMP socket needs root privileges (or CAP_NET_RAW)` | Ejecutá `PingMessageReceive.py` como `root`. |
| `Error: the "ping" command was not found (install the iputils-ping package)` | Ejecutá `apt-get install -y iputils-ping` en el emisor. |
| `Error: unable to resolve "..." to an IPv4 address` | El nombre del destino no se resuelve a IPv4. Usá la dirección IP. |
| `Error: the file is too big` | La carga útil supera el límite del protocolo (unos 112 MiB). |
| El emisor muestra `replies: 0` | Los pings o sus respuestas están bloqueados. Verificá `ping <receiver IP>` y los firewalls. |
| El emisor nunca termina | El receptor no confirma (no se está ejecutando, se ejecuta con `--no-ack`, o no pudo cambiar `/proc/sys`). Usá `-r` en el emisor. |
| El receptor registra `Warning: unable to disable the kernel echo replies ... acknowledgements disabled` | `/proc/sys` es de sólo lectura (algo habitual en contenedores). Usá `-r` en el emisor. |
| El receptor registra `CRC-32 mismatch` | Algunos datos llegaron corruptos. El archivo se reconstruye automáticamente a partir de la ronda siguiente. |
| El receptor registra `the header changed (another file is using this session)` | Dos archivos distintos usaron el mismo número de sesión desde el mismo emisor. El nuevo reemplaza al anterior. |
| Después de matar al receptor con `kill -9`, la computadora ya no responde los pings | Restaurá el ajuste a mano: `sysctl -w net.ipv4.icmp_echo_ignore_all=0`. |

## 9. Limitaciones y seguridad

 - **Sin cifrado y sin autenticación**: los datos viajan en claro dentro de los pings y cualquiera puede enviarle archivos a un receptor en ejecución. Cifrá los archivos sensibles antes de enviarlos, y no dejes un receptor ejecutándose sin supervisión en una red que no sea de confianza.
 - **Sólo IPv4**.
 - **Uso de memoria**: los archivos recibidos se mantienen en memoria hasta que están completos y después se guardan; un archivo descomprimido puede ocupar hasta 1 GiB.
 - **Comportamiento del ping**: mientras el receptor se ejecuta, es él quien responde los pings de toda la computadora en lugar del sistema operativo.
 - **Detectabilidad**: los pings parecen tráfico normal de `ping -p`, pero el patrón de datos cambia con cada ping, algo que un monitor de red puede notar.
