# ping-messenger

This README is also available in:\
[en-GB](doc/README.en-GB.md), en-US, [es-AR](doc/README.es-AR.md), [es-ES](doc/README.es-ES.md)

ping-messenger sends text messages and files (text or binary) from one computer to another hidden inside ordinary `ping` packets (ICMP echo requests). It is useful when the only traffic allowed between two hosts is ping, and as a teaching example of how data can travel inside ICMP.

It is made of two command-line programs:

 - **`PingMessageSend.py`**: runs on the computer that sends. It splits the file into small pieces and sends each one inside a ping, using the normal `ping` command of the system.
 - **`PingMessageReceive.py`**: runs on the computer that receives. It listens for the pings, puts the pieces back together, checks that nothing was corrupted and saves the file. When the file is complete, it tells the sender inside its ping replies, so the sender can stop.

## How it works, in short

 - Every ping carries 16 bytes of data chosen by the sender (`ping -p`). 7 of those bytes are a piece of the file; the rest are a small header and a checksum.
 - The file is compressed first (only if that makes it smaller) and its name travels with it.
 - The sender repeats the whole file in rounds. The receiver can start listening at any moment and keeps the pieces it already has, so lost pings are recovered in the next round.
 - When the file is complete and verified, the receiver answers the pings with an acknowledgement and the sender stops.

The technical details are in [doc/CODE.md](doc/CODE.md).

## Requirements

 - Debian 13 ("trixie") or any Linux with **Python 3.13 or later**. Only the Python standard library is used.
 - **Sender**: the `ping` command from the `iputils-ping` package (the BusyBox `ping` does not support the 16-byte pattern).
 - **Receiver**: root privileges (or the `CAP_NET_RAW` capability), because it opens a raw ICMP socket.
 - Both computers must reach each other over **IPv4**, and nothing in between may block ICMP echo requests and replies.

## Installation on Debian

Run these commands as `root` on both computers, from the folder that contains the two scripts:

```bash
apt-get update
apt-get install -y python3 iputils-ping
install -m 755 PingMessageSend.py PingMessageReceive.py /usr/local/bin/
```

To update to a newer version, copy the new scripts with the same `install` command. To uninstall, delete them:

```bash
rm -f /usr/local/bin/PingMessageSend.py /usr/local/bin/PingMessageReceive.py
```

## Usage

1. On the receiving computer, as `root`, start the receiver and tell it where to save the files:

   ```bash
   PingMessageReceive.py -o /root/received
   ```

2. On the sending computer, send a file to the IP address or name of the receiver:

   ```bash
   PingMessageSend.py -f message.txt -t 192.168.1.20
   ```

3. The sender stops by itself when the receiver confirms that the file arrived. The file is saved in `/root/received/` with its original name.

To send a short text message, write it to a file first:

```bash
echo "Meet me at 10:00" > message.txt
PingMessageSend.py -f message.txt -t 192.168.1.20
```

Press `Ctrl+C` to stop the receiver.

## Things to know

 - Each ping carries only 7 bytes of the file, so ping-messenger is meant for text messages and small files: a 10 KB file needs about 1,500 pings.
 - The data is **not encrypted**: anyone who can capture the traffic can rebuild the file.
 - While the receiver runs, it answers the pings itself instead of the operating system (it sets `net.ipv4.icmp_echo_ignore_all` to `1` and restores the original value when it stops). If it is killed with `kill -9`, restore it by hand with `sysctl -w net.ipv4.icmp_echo_ignore_all=0`.

## Documentation

 - [User manual](doc/MANUAL.md): all the options, examples and troubleshooting.
 - [Code documentation](doc/CODE.md): architecture, wire protocol and code map.
