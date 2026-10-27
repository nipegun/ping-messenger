# ping-messenger

Este README también está disponible en:\
[en-GB](README.en-GB.md), [en-US](../README.md), es-AR, [es-ES](README.es-ES.md)

ping-messenger envía mensajes de texto y archivos (de texto o binarios) de una computadora a otra, escondidos dentro de paquetes `ping` comunes (solicitudes de eco ICMP). Es útil cuando el único tráfico permitido entre dos equipos es el ping, y como ejemplo didáctico de cómo pueden viajar datos dentro de ICMP.

Está formado por dos programas de línea de comandos:

 - **`PingMessageSend.py`**: se ejecuta en la computadora que envía. Divide el archivo en pedacitos y envía cada uno dentro de un ping, usando el comando `ping` normal del sistema.
 - **`PingMessageReceive.py`**: se ejecuta en la computadora que recibe. Escucha los pings, vuelve a juntar los pedazos, verifica que nada se haya corrompido y guarda el archivo. Cuando el archivo está completo, se lo avisa al emisor dentro de sus respuestas a los pings, para que el emisor pueda detenerse.

## Cómo funciona, en pocas palabras

 - Cada ping lleva 16 bytes de datos elegidos por el emisor (`ping -p`). 7 de esos bytes son un pedazo del archivo; el resto son una pequeña cabecera y una suma de verificación.
 - Primero se comprime el archivo (sólo si eso lo achica) y su nombre viaja con él.
 - El emisor repite el archivo entero en rondas. El receptor puede empezar a escuchar en cualquier momento y conserva los pedazos que ya tiene, así que los pings perdidos se recuperan en la ronda siguiente.
 - Cuando el archivo está completo y verificado, el receptor responde los pings con una confirmación y el emisor se detiene.

Los detalles técnicos están en [CODE.es-AR.md](CODE.es-AR.md).

## Requisitos

 - Debian 13 ("trixie") o cualquier Linux con **Python 3.13 o posterior**. Sólo se usa la biblioteca estándar de Python.
 - **Emisor**: el comando `ping` del paquete `iputils-ping` (el `ping` de BusyBox no admite el patrón de 16 bytes).
 - **Receptor**: privilegios de root (o la capacidad `CAP_NET_RAW`), porque abre un socket ICMP raw.
 - Las dos computadoras tienen que poder comunicarse entre sí por **IPv4**, y nada en el medio puede bloquear las solicitudes y respuestas de eco ICMP.

## Instalación en Debian

Ejecutá estos comandos como `root` en las dos computadoras, desde la carpeta que contiene los dos scripts:

```bash
apt-get update
apt-get install -y python3 iputils-ping
install -m 755 PingMessageSend.py PingMessageReceive.py /usr/local/bin/
```

Para actualizar a una versión más nueva, copiá los scripts nuevos con el mismo comando `install`. Para desinstalarlos, borralos:

```bash
rm -f /usr/local/bin/PingMessageSend.py /usr/local/bin/PingMessageReceive.py
```

## Uso

1. En la computadora receptora, como `root`, iniciá el receptor e indicale dónde guardar los archivos:

   ```bash
   PingMessageReceive.py -o /root/received
   ```

2. En la computadora emisora, enviá un archivo a la dirección IP o al nombre del receptor:

   ```bash
   PingMessageSend.py -f message.txt -t 192.168.1.20
   ```

3. El emisor se detiene solo cuando el receptor confirma que el archivo llegó. El archivo se guarda en `/root/received/` con su nombre original.

Para enviar un mensaje de texto corto, primero escribilo en un archivo:

```bash
echo "Meet me at 10:00" > message.txt
PingMessageSend.py -f message.txt -t 192.168.1.20
```

Presioná `Ctrl+C` para detener el receptor.

## Cosas para tener en cuenta

 - Cada ping lleva sólo 7 bytes del archivo, así que ping-messenger está pensado para mensajes de texto y archivos chicos: un archivo de 10 KB necesita unos 1500 pings.
 - Los datos **no están cifrados**: cualquiera que pueda capturar el tráfico puede reconstruir el archivo.
 - Mientras el receptor está en ejecución, es él quien responde los pings en lugar del sistema operativo (pone `net.ipv4.icmp_echo_ignore_all` en `1` y restaura el valor original cuando se detiene). Si se lo mata con `kill -9`, restaurá el valor a mano con `sysctl -w net.ipv4.icmp_echo_ignore_all=0`.

## Documentación

 - [Manual de usuario](MANUAL.es-AR.md): todas las opciones, ejemplos y solución de problemas.
 - [Documentación del código](CODE.es-AR.md): arquitectura, protocolo de comunicación y mapa del código.
