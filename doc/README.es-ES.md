# ping-messenger

Este README también está disponible en:\
[en-GB](README.en-GB.md), [en-US](../README.md), [es-AR](README.es-AR.md), es-ES

ping-messenger envía mensajes de texto y archivos (de texto o binarios) de un ordenador a otro, ocultos dentro de paquetes `ping` normales (solicitudes de eco ICMP). Es útil cuando el único tráfico permitido entre dos equipos es el ping, y también como ejemplo didáctico de cómo pueden viajar datos dentro de ICMP.

Está formado por dos programas de línea de comandos:

 - **`PingMessageSend.py`**: se ejecuta en el ordenador que envía. Divide el archivo en trozos pequeños y envía cada uno dentro de un ping, usando el comando `ping` normal del sistema.
 - **`PingMessageReceive.py`**: se ejecuta en el ordenador que recibe. Escucha los pings, vuelve a juntar los trozos, comprueba que nada se haya corrompido y guarda el archivo. Cuando el archivo está completo, se lo comunica al emisor dentro de sus respuestas a los pings, para que el emisor pueda detenerse.

## Cómo funciona, en resumen

 - Cada ping lleva 16 bytes de datos elegidos por el emisor (`ping -p`). 7 de esos bytes son un trozo del archivo; el resto son una pequeña cabecera y una suma de verificación.
 - Primero se comprime el archivo (sólo si así ocupa menos) y su nombre viaja con él.
 - El emisor repite el archivo completo en rondas. El receptor puede empezar a escuchar en cualquier momento y conserva los trozos que ya tiene, así que los pings perdidos se recuperan en la siguiente ronda.
 - Cuando el archivo está completo y verificado, el receptor responde a los pings con una confirmación y el emisor se detiene.

Los detalles técnicos están en [CODE.es-ES.md](CODE.es-ES.md).

## Requisitos

 - Debian 13 ("trixie") o cualquier Linux con **Python 3.13 o posterior**. Sólo se usa la biblioteca estándar de Python.
 - **Emisor**: el comando `ping` del paquete `iputils-ping` (el `ping` de BusyBox no admite el patrón de 16 bytes).
 - **Receptor**: privilegios de root (o la capacidad `CAP_NET_RAW`), porque abre un socket ICMP raw.
 - Ambos ordenadores deben poder comunicarse entre sí por **IPv4**, y nada de lo que haya entre ellos puede bloquear las solicitudes y respuestas de eco ICMP.

## Instalación en Debian

Ejecuta estos comandos como `root` en ambos ordenadores, desde la carpeta que contiene los dos scripts:

```bash
apt-get update
apt-get install -y python3 iputils-ping
install -m 755 PingMessageSend.py PingMessageReceive.py /usr/local/bin/
```

Para actualizar a una versión más reciente, copia los nuevos scripts con el mismo comando `install`. Para desinstalarlo, bórralos:

```bash
rm -f /usr/local/bin/PingMessageSend.py /usr/local/bin/PingMessageReceive.py
```

## Uso

1. En el ordenador receptor, como `root`, inicia el receptor e indícale dónde guardar los archivos:

   ```bash
   PingMessageReceive.py -o /root/received
   ```

2. En el ordenador emisor, envía un archivo a la dirección IP o al nombre del receptor:

   ```bash
   PingMessageSend.py -f message.txt -t 192.168.1.20
   ```

3. El emisor se detiene por sí solo cuando el receptor confirma que el archivo ha llegado. El archivo se guarda en `/root/received/` con su nombre original.

Para enviar un mensaje de texto corto, escríbelo primero en un archivo:

```bash
echo "Meet me at 10:00" > message.txt
PingMessageSend.py -f message.txt -t 192.168.1.20
```

Pulsa `Ctrl+C` para detener el receptor.

## Cosas que debes saber

 - Cada ping lleva sólo 7 bytes del archivo, así que ping-messenger está pensado para mensajes de texto y archivos pequeños: un archivo de 10 KB necesita unos 1500 pings.
 - Los datos **no van cifrados**: cualquiera que pueda capturar el tráfico puede reconstruir el archivo.
 - Mientras el receptor está en marcha, es él quien responde a los pings en lugar del sistema operativo (pone `net.ipv4.icmp_echo_ignore_all` a `1` y restaura el valor original cuando se detiene). Si se mata con `kill -9`, restáuralo a mano con `sysctl -w net.ipv4.icmp_echo_ignore_all=0`.

## Documentación

 - [Manual de usuario](MANUAL.es-ES.md): todas las opciones, ejemplos y resolución de problemas.
 - [Documentación del código](CODE.es-ES.md): arquitectura, protocolo de transmisión y mapa del código.
