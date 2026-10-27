# Manual de usuario de ping-messenger

Este MANUAL también está disponible en:\
[en-GB](MANUAL.en-GB.md), [en-US](MANUAL.md), [es-AR](MANUAL.es-AR.md), es-ES

## Contenido

 1. [Qué hace ping-messenger](#1-qué-hace-ping-messenger)
 2. [Antes de empezar](#2-antes-de-empezar)
 3. [Inicio rápido](#3-inicio-rápido)
 4. [El receptor: PingMessageReceive.py](#4-el-receptor-pingmessagereceivepy)
 5. [El emisor: PingMessageSend.py](#5-el-emisor-pingmessagesendpy)
 6. [Tareas habituales](#6-tareas-habituales)
 7. [Ajuste de la transferencia](#7-ajuste-de-la-transferencia)
 8. [Resolución de problemas](#8-resolución-de-problemas)
 9. [Limitaciones y seguridad](#9-limitaciones-y-seguridad)

## 1. Qué hace ping-messenger

ping-messenger traslada un mensaje de texto o un archivo de un ordenador (el **emisor**) a otro (el **receptor**) usando únicamente paquetes `ping`. Desde el punto de vista de la red, el emisor simplemente está haciendo ping al receptor muchas veces.

 - En el emisor ejecutas `PingMessageSend.py`. No necesita root.
 - En el receptor ejecutas `PingMessageReceive.py`. Necesita root.

El receptor debe iniciarse primero, o al menos antes de que el emisor termine, pero no importa si arranca cuando el emisor ya está enviando: el emisor repite el archivo en **rondas** hasta que el receptor confirma que lo tiene.

## 2. Antes de empezar

Comprueba estos puntos en ambos ordenadores:

| Comprobación | Emisor | Receptor |
|---|---|---|
| Python 3.13 o posterior (`python3 --version`) | Sí | Sí |
| `ping` de `iputils-ping` (`ping -V` muestra `ping from iputils ...`) | Sí | No |
| Usuario root, o la capacidad `CAP_NET_RAW` | No | Sí |
| Conectividad IPv4 entre ambos ordenadores | Sí | Sí |
| Ningún cortafuegos que descarte las solicitudes y respuestas de eco ICMP | Sí | Sí |

En Debian, como `root`:

```bash
apt-get update
apt-get install -y python3 iputils-ping
install -m 755 PingMessageSend.py PingMessageReceive.py /usr/local/bin/
```

También puedes ejecutar los scripts desde cualquier carpeta sin instalarlos, por ejemplo `./PingMessageSend.py ...`.

Una prueba rápida: desde el emisor, `ping -c 3 <receiver IP>` debe obtener respuestas antes de que pruebes ping-messenger.

## 3. Inicio rápido

1. **Receptor** (como `root`):

   ```bash
   PingMessageReceive.py -o /root/received
   ```

   Muestra algo parecido a esto:

   ```text
   [2026/10/27@10:45:12.345] Listening for ICMP echo requests, files will be saved to "/root/received"
   [2026/10/27@10:45:12.346] Acknowledgements enabled: /proc/sys/net/ipv4/icmp_echo_ignore_all set to 1 while the receiver runs
   ```

2. **Emisor**:

   ```bash
   echo "Hello from ping-messenger" > hello.txt
   PingMessageSend.py -f hello.txt -t 192.168.1.20
   ```

   Muestra algo parecido a esto:

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

3. **Receptor** de nuevo: el archivo está en `/root/received/hello.txt`, y el registro muestra:

   ```text
   [2026/10/27@10:45:20.101] 192.168.1.10 0x3f2a: new transfer detected
   [2026/10/27@10:45:20.102] 192.168.1.10 0x3f2a: header received (36 bytes, uncompressed, 6 data frames)
   [2026/10/27@10:45:20.150] 192.168.1.10 0x3f2a: 1/6 data frames (10%)
   ...
   [2026/10/27@10:45:20.390] 192.168.1.10 0x3f2a: file saved to "/root/received/hello.txt" (26 bytes)
   ```

4. Pulsa `Ctrl+C` en el receptor cuando ya no esperes más archivos.

Los números anteriores son un ejemplo: la sesión, los tamaños y los tiempos cambian con cada archivo.

## 4. El receptor: PingMessageReceive.py

```text
PingMessageReceive.py [-o OUTPUT_DIR] [--no-ack] [--once]
```

| Opción | Valor por defecto | Qué hace |
|---|---|---|
| `-o`, `--output-dir` | Directorio actual | Carpeta donde se guardan los archivos recibidos. Se crea si no existe. |
| `--no-ack` | Desactivada | No responde a los pings ni envía confirmaciones. El sistema operativo sigue respondiendo a los pings como de costumbre. El emisor nunca sabrá que el archivo ha llegado, así que usa `-r` en el emisor. |
| `--once` | Desactivada | Sale después de guardar el primer archivo. Con las confirmaciones activadas, sigue respondiendo durante 5 segundos más para que el emisor reciba la confirmación. |
| `-h`, `--help` | | Muestra la ayuda y sale. |

### Qué hace el receptor

 - Escucha todos los pings que llegan al ordenador y busca en su interior datos de ping-messenger. Los pings normales se ignoran (aunque se siguen respondiendo, consulta más abajo).
 - Puede recibir varios archivos a la vez, del mismo emisor o de emisores distintos. Cada transferencia se identifica por la dirección IP del emisor y un número de **sesión** (que aparece como `0x3f2a` en el registro). Enviar de nuevo el mismo archivo produce la misma sesión.
 - Registra el progreso cada 10 % del archivo.
 - Cuando han llegado todos los trozos, comprueba el archivo completo con una suma de verificación CRC-32. Si la comprobación falla, descarta los trozos y reconstruye el archivo a partir de la siguiente ronda.
 - Las transferencias que permanecen en silencio durante 10 minutos se olvidan.

### Dónde se guardan los archivos

 - Cada archivo se guarda en la carpeta de salida con el nombre que tenía en el emisor.
 - Nunca se sobrescribe un archivo existente: si `hello.txt` ya existe, el nuevo se guarda como `hello.txt.1`, luego como `hello.txt.2`, y así sucesivamente.
 - Las barras del nombre se sustituyen por `_`, de modo que un archivo nunca puede escribirse fuera de la carpeta de salida. Un archivo sin un nombre utilizable se guarda como `received.bin`.

### Las confirmaciones y las respuestas a los pings

Por defecto, es el receptor quien responde a los pings en lugar del sistema operativo. Así es como mete la confirmación dentro de las respuestas:

 - Al arrancar, pone `/proc/sys/net/ipv4/icmp_echo_ignore_all` a `1` (el kernel deja de responder a los pings) y recuerda el valor anterior.
 - Mientras está en marcha, responde a todos los pings dirigidos al ordenador, así que el ordenador sigue respondiendo al ping como antes. Si el ordenador ya ignoraba los pings antes, sólo responde a los pings de ping-messenger.
 - Los pings enviados a direcciones de difusión (broadcast) o de multidifusión (multicast) no se responden.
 - Cuando se detiene (`Ctrl+C`, `--once`, `SIGTERM` o `SIGHUP`), restaura el valor anterior y registra `... restored to 0`.

Si no puede cambiar ese ajuste (por ejemplo, en algunos contenedores, donde `/proc/sys` es de sólo lectura), registra un aviso y continúa con las confirmaciones desactivadas, como si se hubiera indicado `--no-ack`.

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

| Opción | Valor por defecto | Qué hace |
|---|---|---|
| `-f`, `--file` | Obligatoria | Archivo que se envía. De texto o binario. |
| `-t`, `--target` | Obligatoria | Dirección IPv4 o nombre de host del ordenador que ejecuta `PingMessageReceive.py`. |
| `-r`, `--rounds` | `0` | Número máximo de veces que se envía el archivo completo. `0` significa "repetir hasta que el receptor confirme". |
| `-i`, `--interval` | `0.01` | Segundos de espera entre un ping y el siguiente. |
| `-W`, `--timeout` | `1` | Segundos de espera de la respuesta a cada ping. |
| `-H`, `--header-every` | `32` | Repite la cabecera (tamaño y suma de verificación del archivo) cada N trozos del archivo. |
| `--no-compress` | Desactivada | No comprime el archivo antes de enviarlo. |
| `-h`, `--help` | | Muestra la ayuda y sale. |

### Qué muestra el emisor

 - **File**: el archivo y su tamaño.
 - **Target**: el destino tal y como lo has escrito y la dirección IP a la que se resuelve.
 - **Session**: el número de sesión. El receptor muestra el mismo número en su registro.
 - **Payload**: los bytes que viajarán realmente (nombre + contenido, comprimido si así ocupaba menos) y el número de tramas de datos (una por ping, de 7 bytes cada una).
 - **Round**: el número de pings de una ronda (tramas de datos más tramas de cabecera).
 - **Rounds**: el límite de rondas.
 - Una línea de progreso con la ronda actual, el ping y el número de respuestas recibidas. En un terminal se actualiza en el mismo sitio.
 - Un resumen final con los pings enviados, las respuestas y el tiempo que ha tardado, seguido de si el receptor ha confirmado o no el archivo.

### Cuándo se detiene

 - Cuando una respuesta lleva la confirmación del receptor: `The receiver acknowledged the file. Transfer complete.`
 - Cuando se han enviado las rondas indicadas con `-r` sin recibir una confirmación: `All the rounds were sent without an acknowledgement from the receiver.` Esto no significa que el archivo se haya perdido; sólo significa que el emisor no ha recibido una confirmación (por ejemplo, porque el receptor se ejecuta con `--no-ack`).
 - Cuando `ping` falla 10 veces seguidas con un error real (no un simple "sin respuesta"), se detiene con un error.
 - Cuando pulsas `Ctrl+C`.

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | Terminado: confirmado, o se enviaron todas las rondas. Mira la última línea para saber cuál de los dos casos. |
| `1` | Error (archivo no encontrado, destino que no se puede resolver, `ping` ausente o fallando...). |
| `130` | Detenido con `Ctrl+C`. |

## 6. Tareas habituales

### Enviar un mensaje de texto corto

```bash
echo "The backup finished at 03:00" > message.txt
PingMessageSend.py -f message.txt -t 192.168.1.20
```

En el receptor, léelo con `cat /root/received/message.txt`.

### Recibir exactamente un archivo y salir

```bash
PingMessageReceive.py -o /root/received --once
```

Útil en scripts: cuando el comando termina, el archivo ya está guardado.

### Enviar sin confirmaciones

Cuando el receptor no puede responder a los pings (se ejecuta con `--no-ack`, o en un contenedor donde no puede cambiar `/proc/sys`), limita el número de rondas para que el emisor no se ejecute indefinidamente:

```bash
PingMessageSend.py -f message.txt -t 192.168.1.20 -r 3
```

Cuantas más rondas, más oportunidades de recuperar los pings perdidos.

### Enviar un archivo binario

Sirve cualquier archivo, por ejemplo `PingMessageSend.py -f photo.jpg -t 192.168.1.20`. Los archivos que ya están comprimidos (JPEG, ZIP...) se envían sin comprimir de forma automática, porque volver a comprimirlos no los haría más pequeños.

## 7. Ajuste de la transferencia

 - **Velocidad**: cada ping lleva 7 bytes. Una ronda necesita unos `payload / 7` pings más una cabecera cada 32 pings. Bajar `-i` (por ejemplo, `-i 0`) envía más rápido, pero puede perder más pings en redes lentas o saturadas; los pings perdidos se recuperan en la siguiente ronda.
 - **Enlaces lentos**: si las respuestas llegan tarde, sube `-W` (por ejemplo, `-W 3`). Un ping sin respuesta no es un error: puede que la solicitud sí haya llegado al receptor.
 - **Receptores que arrancan tarde**: la cabecera se repite cada 32 tramas de datos para que un receptor que arranca a mitad de una ronda conozca enseguida el tamaño del archivo. Baja `-H` para repetirla más a menudo (más pings por ronda) o súbelo para enviar menos pings.
 - **Compresión**: está activada por defecto y sólo se usa cuando hace más pequeña la carga útil. `--no-compress` sólo sirve para comparar tamaños.
 - **Tamaño máximo**: la carga útil (después de la compresión) puede llegar a 117.440.512 bytes (unos 112 MiB), pero en la práctica ping-messenger está pensado para archivos mucho más pequeños.

## 8. Resolución de problemas

| Mensaje o síntoma | Causa y solución |
|---|---|
| `Error: a raw ICMP socket needs root privileges (or CAP_NET_RAW)` | Ejecuta `PingMessageReceive.py` como `root`. |
| `Error: the "ping" command was not found (install the iputils-ping package)` | Ejecuta `apt-get install -y iputils-ping` en el emisor. |
| `Error: unable to resolve "..." to an IPv4 address` | El nombre del destino no se resuelve a una dirección IPv4. Usa la dirección IP. |
| `Error: the file is too big` | La carga útil supera el límite del protocolo (unos 112 MiB). |
| El emisor muestra `replies: 0` | Los pings o sus respuestas están bloqueados. Comprueba `ping <receiver IP>` y los cortafuegos. |
| El emisor nunca termina | El receptor no confirma (no está en marcha, se ejecuta con `--no-ack` o no ha podido cambiar `/proc/sys`). Usa `-r` en el emisor. |
| El receptor registra `Warning: unable to disable the kernel echo replies ... acknowledgements disabled` | `/proc/sys` es de sólo lectura (algo habitual en contenedores). Usa `-r` en el emisor. |
| El receptor registra `CRC-32 mismatch` | Algunos datos han llegado corruptos. Se reconstruyen automáticamente a partir de la siguiente ronda. |
| El receptor registra `the header changed (another file is using this session)` | Dos archivos distintos han usado el mismo número de sesión desde el mismo emisor. El nuevo sustituye al antiguo. |
| Después de matar el receptor con `kill -9`, el ordenador ya no responde a los pings | Restaura el ajuste a mano: `sysctl -w net.ipv4.icmp_echo_ignore_all=0`. |

## 9. Limitaciones y seguridad

 - **Sin cifrado y sin autenticación**: los datos viajan en claro dentro de los pings y cualquiera puede enviar archivos a un receptor que esté en marcha. Cifra los archivos sensibles antes de enviarlos y no dejes un receptor en marcha sin supervisión en una red que no sea de confianza.
 - **Sólo IPv4**.
 - **Uso de memoria**: los archivos recibidos se mantienen en memoria hasta que están completos y después se guardan; un archivo descomprimido puede ocupar hasta 1 GiB.
 - **Comportamiento del ping**: mientras el receptor está en marcha, es él quien responde a los pings de todo el ordenador en lugar del sistema operativo.
 - **Detectabilidad**: los pings parecen tráfico `ping -p` normal, pero el patrón de datos cambia con cada ping, algo que un monitor de red puede detectar.
