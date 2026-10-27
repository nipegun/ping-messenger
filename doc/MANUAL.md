# ping-messenger user manual

This MANUAL is also available in:\
[en-GB](MANUAL.en-GB.md), en-US, [es-AR](MANUAL.es-AR.md), [es-ES](MANUAL.es-ES.md)

## Contents

 1. [What ping-messenger does](#1-what-ping-messenger-does)
 2. [Before you start](#2-before-you-start)
 3. [Quick start](#3-quick-start)
 4. [The receiver: PingMessageReceive.py](#4-the-receiver-pingmessagereceivepy)
 5. [The sender: PingMessageSend.py](#5-the-sender-pingmessagesendpy)
 6. [Common tasks](#6-common-tasks)
 7. [Tuning the transfer](#7-tuning-the-transfer)
 8. [Troubleshooting](#8-troubleshooting)
 9. [Limitations and security](#9-limitations-and-security)

## 1. What ping-messenger does

ping-messenger moves a text message or a file from one computer (the **sender**) to another (the **receiver**) using only `ping` packets. From the network's point of view, the sender is just pinging the receiver many times.

 - On the sender you run `PingMessageSend.py`. It does not need root.
 - On the receiver you run `PingMessageReceive.py`. It needs root.

The receiver must be started first, or at least before the sender finishes, but it does not matter if it starts while the sender is already sending: the sender repeats the file in **rounds** until the receiver confirms that it has it.

## 2. Before you start

Check these points on both computers:

| Check | Sender | Receiver |
|---|---|---|
| Python 3.13 or later (`python3 --version`) | Yes | Yes |
| `ping` from `iputils-ping` (`ping -V` prints `ping from iputils ...`) | Yes | No |
| Root user, or the `CAP_NET_RAW` capability | No | Yes |
| IPv4 connectivity between both computers | Yes | Yes |
| No firewall dropping ICMP echo requests and replies | Yes | Yes |

On Debian, as `root`:

```bash
apt-get update
apt-get install -y python3 iputils-ping
install -m 755 PingMessageSend.py PingMessageReceive.py /usr/local/bin/
```

You can also run the scripts from any folder without installing them, for example `./PingMessageSend.py ...`.

A quick test: from the sender, `ping -c 3 <receiver IP>` must get replies before you try ping-messenger.

## 3. Quick start

1. **Receiver** (as `root`):

   ```bash
   PingMessageReceive.py -o /root/received
   ```

   It prints something like:

   ```text
   [2026/10/27@10:45:12.345] Listening for ICMP echo requests, files will be saved to "/root/received"
   [2026/10/27@10:45:12.346] Acknowledgements enabled: /proc/sys/net/ipv4/icmp_echo_ignore_all set to 1 while the receiver runs
   ```

2. **Sender**:

   ```bash
   echo "Hello from ping-messenger" > hello.txt
   PingMessageSend.py -f hello.txt -t 192.168.1.20
   ```

   It prints something like:

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

3. **Receiver** again: the file is in `/root/received/hello.txt`, and the log shows:

   ```text
   [2026/10/27@10:45:20.101] 192.168.1.10 0x3f2a: new transfer detected
   [2026/10/27@10:45:20.102] 192.168.1.10 0x3f2a: header received (36 bytes, uncompressed, 6 data frames)
   [2026/10/27@10:45:20.150] 192.168.1.10 0x3f2a: 1/6 data frames (10%)
   ...
   [2026/10/27@10:45:20.390] 192.168.1.10 0x3f2a: file saved to "/root/received/hello.txt" (26 bytes)
   ```

4. Press `Ctrl+C` on the receiver when you do not expect more files.

The numbers above are an example: the session, sizes and times change with every file.

## 4. The receiver: PingMessageReceive.py

```text
PingMessageReceive.py [-o OUTPUT_DIR] [--no-ack] [--once]
```

| Option | Default | What it does |
|---|---|---|
| `-o`, `--output-dir` | Current directory | Folder where the received files are saved. It is created if it does not exist. |
| `--no-ack` | Off | Do not answer the pings nor send acknowledgements. The operating system keeps answering the pings as usual. The sender will never know that the file arrived, so use `-r` on the sender. |
| `--once` | Off | Exit after the first file is saved. With acknowledgements enabled, it keeps answering for 5 more seconds so the sender receives the confirmation. |
| `-h`, `--help` | | Show the help and exit. |

### What the receiver does

 - It listens for every ping that reaches the computer and looks inside it for ping-messenger data. Normal pings are ignored (but still answered, see below).
 - It can receive several files at the same time, from the same or different senders. Each transfer is identified by the sender's IP address and a **session** number (shown as `0x3f2a` in the log). Sending the same file again produces the same session.
 - It logs the progress every 10% of the file.
 - When all the pieces have arrived, it checks the whole file with a CRC-32 checksum. If the check fails, it discards the pieces and rebuilds the file from the next round.
 - Transfers that stay silent for 10 minutes are forgotten.

### Where the files are saved

 - Each file is saved in the output folder with the name it had on the sender.
 - An existing file is never overwritten: if `hello.txt` already exists, the new one is saved as `hello.txt.1`, then `hello.txt.2`, and so on.
 - Slashes in the name are replaced by `_`, so a file can never be written outside the output folder. A file without a usable name is saved as `received.bin`.

### Acknowledgements and the ping replies

By default the receiver answers the pings itself instead of the operating system. That is how it puts the acknowledgement inside the replies:

 - On start it sets `/proc/sys/net/ipv4/icmp_echo_ignore_all` to `1` (the kernel stops answering pings) and remembers the previous value.
 - While it runs, it answers every ping addressed to the computer, so the computer still looks pingable. If the computer was already ignoring pings before, it only answers the ping-messenger pings.
 - Pings sent to broadcast or multicast addresses are not answered.
 - When it stops (`Ctrl+C`, `--once`, `SIGTERM` or `SIGHUP`), it restores the previous value and logs `... restored to 0`.

If it cannot change that setting (for example in some containers, where `/proc/sys` is read-only), it logs a warning and continues with acknowledgements disabled, as if `--no-ack` had been given.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | `--once` was given and a file was received. |
| `1` | Error (for example, not running as root). |
| `129` / `143` | Stopped by `SIGHUP` / `SIGTERM`. |
| `130` | Stopped with `Ctrl+C`. |

## 5. The sender: PingMessageSend.py

```text
PingMessageSend.py -f FILE -t TARGET [-r ROUNDS] [-i INTERVAL] [-W TIMEOUT] [-H HEADER_EVERY] [--no-compress]
```

| Option | Default | What it does |
|---|---|---|
| `-f`, `--file` | Required | File to send. Text or binary. |
| `-t`, `--target` | Required | IPv4 address or host name of the computer that runs `PingMessageReceive.py`. |
| `-r`, `--rounds` | `0` | Maximum number of times the whole file is sent. `0` means "repeat until the receiver acknowledges". |
| `-i`, `--interval` | `0.01` | Seconds to wait between one ping and the next. |
| `-W`, `--timeout` | `1` | Seconds to wait for the reply to each ping. |
| `-H`, `--header-every` | `32` | Repeat the header (file size and checksum) every N pieces of the file. |
| `--no-compress` | Off | Do not compress the file before sending it. |
| `-h`, `--help` | | Show the help and exit. |

### What the sender shows

 - **File**: the file and its size.
 - **Target**: the target as you wrote it and the IP address it resolves to.
 - **Session**: the session number. The receiver shows the same number in its log.
 - **Payload**: the bytes that will actually travel (name + content, compressed if that made it smaller) and the number of data frames (one per ping, 7 bytes each).
 - **Round**: the number of pings in one round (data frames plus header frames).
 - **Rounds**: the round limit.
 - A progress line with the current round, ping and the number of replies received. In a terminal it is updated in place.
 - A final summary with the pings sent, the replies and the time it took, followed by whether the receiver acknowledged the file.

### When it stops

 - When a reply carries the acknowledgement of the receiver: `The receiver acknowledged the file. Transfer complete.`
 - When the `-r` rounds have been sent without an acknowledgement: `All the rounds were sent without an acknowledgement from the receiver.` This does not mean that the file was lost; it only means that the sender did not get a confirmation (for example, because the receiver runs with `--no-ack`).
 - When `ping` fails 10 times in a row with a real error (not just "no reply"), it stops with an error.
 - When you press `Ctrl+C`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Finished: acknowledged, or all the rounds were sent. Check the last line to know which. |
| `1` | Error (file not found, target cannot be resolved, `ping` missing or failing...). |
| `130` | Stopped with `Ctrl+C`. |

## 6. Common tasks

### Send a short text message

```bash
echo "The backup finished at 03:00" > message.txt
PingMessageSend.py -f message.txt -t 192.168.1.20
```

On the receiver, read it with `cat /root/received/message.txt`.

### Receive exactly one file and exit

```bash
PingMessageReceive.py -o /root/received --once
```

Useful in scripts: when the command ends, the file is already saved.

### Send without acknowledgements

When the receiver cannot answer the pings (it runs with `--no-ack`, or in a container where it cannot change `/proc/sys`), limit the number of rounds so the sender does not run forever:

```bash
PingMessageSend.py -f message.txt -t 192.168.1.20 -r 3
```

More rounds give more chances to recover lost pings.

### Send a binary file

Any file works, for example `PingMessageSend.py -f photo.jpg -t 192.168.1.20`. Files that are already compressed (JPEG, ZIP...) are sent uncompressed automatically, because compressing them again would not make them smaller.

## 7. Tuning the transfer

 - **Speed**: each ping carries 7 bytes. A round needs about `payload / 7` pings plus one header every 32 pings. Lowering `-i` (for example `-i 0`) sends faster but may lose more pings on slow or busy networks; lost pings are recovered in the next round.
 - **Slow links**: if replies arrive late, raise `-W` (for example `-W 3`). A ping without a reply is not an error: the request may still have reached the receiver.
 - **Receivers that start late**: the header is repeated every 32 data frames so a receiver that starts in the middle of a round learns the file size quickly. Lower `-H` to repeat it more often (more pings per round) or raise it to send fewer pings.
 - **Compression**: it is on by default and only used when it makes the payload smaller. `--no-compress` is only useful to compare sizes.
 - **Maximum size**: the payload (after compression) can be up to 117,440,512 bytes (about 112 MiB), but in practice ping-messenger is meant for much smaller files.

## 8. Troubleshooting

| Message or symptom | Cause and solution |
|---|---|
| `Error: a raw ICMP socket needs root privileges (or CAP_NET_RAW)` | Run `PingMessageReceive.py` as `root`. |
| `Error: the "ping" command was not found (install the iputils-ping package)` | Run `apt-get install -y iputils-ping` on the sender. |
| `Error: unable to resolve "..." to an IPv4 address` | The target name does not resolve to IPv4. Use the IP address. |
| `Error: the file is too big` | The payload exceeds the protocol limit (about 112 MiB). |
| The sender shows `replies: 0` | The pings or their replies are blocked. Check `ping <receiver IP>` and the firewalls. |
| The sender never finishes | The receiver does not acknowledge (it is not running, it runs with `--no-ack`, or it could not change `/proc/sys`). Use `-r` on the sender. |
| The receiver logs `Warning: unable to disable the kernel echo replies ... acknowledgements disabled` | `/proc/sys` is read-only (common in containers). Use `-r` on the sender. |
| The receiver logs `CRC-32 mismatch` | Some data arrived corrupted. It is rebuilt automatically from the next round. |
| The receiver logs `the header changed (another file is using this session)` | Two different files used the same session number from the same sender. The new one replaces the old one. |
| After the receiver was killed with `kill -9`, the computer no longer answers pings | Restore the setting by hand: `sysctl -w net.ipv4.icmp_echo_ignore_all=0`. |

## 9. Limitations and security

 - **No encryption and no authentication**: the data travels in the clear inside the pings and anyone can send files to a running receiver. Encrypt sensitive files before sending them, and do not leave a receiver running unattended on an untrusted network.
 - **IPv4 only**.
 - **Memory usage**: received files are kept in memory until they are complete and then saved; a decompressed file can be up to 1 GiB.
 - **Ping behavior**: while the receiver runs, it answers the pings of the whole computer instead of the operating system.
 - **Detectability**: the pings look like normal `ping -p` traffic, but the data pattern changes with every ping, which a network monitor can notice.
