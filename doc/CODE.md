# ping-messenger code documentation

This CODE is also available in:\
[en-GB](CODE.en-GB.md), en-US, [es-AR](CODE.es-AR.md), [es-ES](CODE.es-ES.md)

Technical reference of the codebase, meant to be read surgically: jump to the section you need. Line numbers refer to the current version of the scripts.

## Index

 1. [Architecture and design decisions](#1-architecture-and-design-decisions)
 2. [Module map](#2-module-map)
 3. [Key symbol index](#3-key-symbol-index)
 4. [Main flows](#4-main-flows)
 5. [Entry points](#5-entry-points)
 6. [Impact analysis](#6-impact-analysis)
 7. [Extension points](#7-extension-points)
 8. [Wire protocol](#8-wire-protocol)

## 1. Architecture and design decisions

ping-messenger is two standalone Python 3.13 scripts with no dependencies outside the standard library:

 - `PingMessageSend.py` turns a file into a sequence of 16-byte frames and sends one frame per ICMP echo request.
 - `PingMessageReceive.py` captures the echo requests with a raw socket, rebuilds the file and acknowledges it inside the echo replies.

The reasons behind the structure:

 - **Two single-file scripts, no shared module.** Each script can be copied alone to a host and run. The price is that the protocol code (constants, `fCrc16`, `fBuildFrame`, `fParseFrame`, `fFindFrames`, `fGetChunkCount`) is duplicated in both files and **must be kept identical**. The comment `Protocol constants (must be identical in ...)` marks the duplicated block.
 - **The sender uses the system `ping` command, not a raw socket.** That way the sender needs no root privileges and its traffic is regular `ping -p` traffic. The price is the payload size: iputils `ping -p` accepts at most 16 pattern bytes, so the frame is exactly 16 bytes (`cFrameSize`). One process is spawned per frame (`ping -c 1`), which also makes every ping independent and lets the sender read the reply of each one.
 - **The frame is self-describing and self-checking.** A magic byte (`0xA7`) and a CRC-16 let the receiver find frames at any offset of any ping payload and discard foreign or corrupted data. `ping` writes a timestamp before the pattern, so the offset of the frame is not fixed; both sides scan every offset (`fFindFrames`).
 - **Carousel delivery instead of retransmission requests.** The only return channel is the echo reply, so the sender does not ask which frames were lost: it repeats the whole file in rounds. The receiver stores frames by sequence number, ignores duplicates and can join at any moment. The header frame (size and CRC-32 of the file) is repeated every `--header-every` data frames so a late receiver learns the size soon.
 - **Session identifier derived from the content.** `fGetSessionId` folds the CRC-32 of the payload into 16 bits, so sending the same file again produces the same session and an interrupted transfer continues where it stopped. The receiver keys its state by `(source IP, session)`, so several senders and files can be received at the same time.
 - **Acknowledgement inside the echo reply.** To put data in the reply, the receiver has to build the replies itself: it sets `net.ipv4.icmp_echo_ignore_all` to `1` while it runs, answers every echo request addressed to a unicast local address (so the host stays pingable) and restores the original value in a `finally` block. `SIGTERM` and `SIGHUP` are turned into `SystemExit` so the restore also runs on those signals. If the host was already ignoring pings, only protocol pings are answered.
 - **ACK detection by parsing the output of `ping`.** When the data of a reply differs from what was sent, iputils `ping` prints `wrong data byte ...` followed by a hex dump of the received data. The sender runs `ping` with `LC_ALL=C` and rebuilds the bytes from that dump (`fExtractReplyDump`). This ties the ACK to the output format of iputils; without it the transfer still works, limited by `--rounds`.
 - **Integrity at two levels.** CRC-16/CCITT-FALSE per frame (discard corrupted frames) and CRC-32 over the whole payload (discard a corrupted file and rebuild it in the next round).
 - **Compression only when it helps.** The payload is compressed with zlib level 9 and the compressed version is used only if it is smaller; a header flag tells the receiver.
 - **Defensive receiver.** File names coming from the network are sanitized (`fSanitizeFileName`), files are opened with mode `xb` so nothing is ever overwritten (`fSaveFile`), decompression is capped at 1 GiB (`cMaxDecompressedSize`) and silent sessions are purged after 10 minutes.
 - **Dates.** The receiver logs in UTC with the display format of the project, `2026/10/29@13:59:59.723` (`fGetDisplayDate`).

## 2. Module map

| Module | Path | Responsibility | Depends on | Used by |
|---|---|---|---|---|
| PingMessageSend | `PingMessageSend.py` | Build the payload from a file, split it into frames, send one frame per `ping`, detect the ACK in the replies, report progress. | Python standard library (`argparse`, `binascii`, `os`, `re`, `shutil`, `socket`, `struct`, `subprocess`, `sys`, `time`, `zlib`); the `ping` command of iputils. | The user (command line). Talks to `PingMessageReceive.py` over ICMP. |
| PingMessageReceive | `PingMessageReceive.py` | Capture echo requests with a raw socket, reassemble and verify files, save them, answer the pings and send the ACK. | Python standard library (`argparse`, `binascii`, `datetime`, `ipaddress`, `os`, `signal`, `socket`, `struct`, `sys`, `time`, `zlib`); root or `CAP_NET_RAW`; `/proc/sys/net/ipv4/icmp_echo_ignore_all`. | The user (command line). Receives from `PingMessageSend.py` over ICMP. |
| Protocol (duplicated) | Constants and `fCrc16`, `fGetChunkCount`, `fBuildFrame`, `fParseFrame`, `fFindFrames` in both scripts | Frame layout, frame checksum, frame search. | `binascii`, `struct`. | Both scripts. |

## 3. Key symbol index

### PingMessageSend.py

| Symbol | File:line | What it does |
|---|---|---|
| Protocol constants | `PingMessageSend.py:29` | `cMagic`, frame types, `cFrameSize`, `cChunkSize`, `cMaxChunks`, `cMaxBlobSize`, `cMaxNameLength`, `cFlagCompressed`. |
| Sender defaults | `PingMessageSend.py:41` | `cDefaultHeaderEvery`, `cDefaultInterval`, `cDefaultTimeout`, `cMaxConsecutiveErrors`. |
| `fCrc16` | `PingMessageSend.py:47` | CRC-16/CCITT-FALSE of a byte string. |
| `fGetChunkCount` | `PingMessageSend.py:52` | Number of 7-byte data frames for a payload size. |
| `fGetFramesPerRound` | `PingMessageSend.py:56` | Data frames plus repeated header frames in one round. |
| `fGetSessionId` | `PingMessageSend.py:60` | 16-bit session identifier derived from the payload CRC-32. |
| `fBuildFrame` | `PingMessageSend.py:66` | Assembles a 16-byte frame and appends its CRC-16. |
| `fBuildHeaderFrame` | `PingMessageSend.py:72` | Header frame: payload size, payload CRC-32, flags. |
| `fBuildDataFrame` | `PingMessageSend.py:78` | Data frame: 24-bit sequence and a 7-byte chunk. |
| `fParseFrame` | `PingMessageSend.py:84` | Validates a 16-byte frame and returns its fields, or `None`. |
| `fFindFrames` | `PingMessageSend.py:110` | Finds every valid frame at any offset of a byte string. |
| `fBuildBlob` | `PingMessageSend.py:123` | Reads the file and builds the payload (name + content, compressed if smaller). |
| `fIterRoundFrames` | `PingMessageSend.py:146` | Generator of the frames of one round. |
| `fPing` | `PingMessageSend.py:157` | Runs one `ping -n -c 1 -W T -p HEX` and returns exit code, stdout and stderr. |
| `fExtractReplyDump` | `PingMessageSend.py:178` | Rebuilds the reply bytes from the `wrong data byte` dump of iputils `ping`. |
| `fIsAckReply` | `PingMessageSend.py:197` | True if the reply contains the ACK frame of the session and payload CRC. |
| `fResolveTarget` | `PingMessageSend.py:205` | Resolves the target to an IPv4 address. |
| `fPrintProgress` | `PingMessageSend.py:213` | Progress line (in place on a terminal). |
| `fParseArguments` | `PingMessageSend.py:222` | Command-line options and their validation. |
| `fMain` | `PingMessageSend.py:247` | Main loop: rounds, pings, ACK detection, summary. |
| `__main__` block | `PingMessageSend.py:311` | Exit codes and error reporting. |

### PingMessageReceive.py

| Symbol | File:line | What it does |
|---|---|---|
| Protocol constants | `PingMessageReceive.py:34` | Same values as in the sender (without `cMaxNameLength`). |
| Receiver settings | `PingMessageReceive.py:45` | ICMP types, `cIpPktInfo`, `cEchoIgnorePath`, timeouts, `cOnceLingerSeconds`, `cMaxDecompressedSize`, `cDefaultFileName`. |
| `fGetDisplayDate` | `PingMessageReceive.py:57` | Current UTC date in the display format of the project. |
| `fLog` | `PingMessageReceive.py:63` | Prints a log line with the date. |
| `fCrc16` | `PingMessageReceive.py:67` | Same as in the sender. |
| `fGetChunkCount` | `PingMessageReceive.py:72` | Same as in the sender. |
| `fBuildFrame` | `PingMessageReceive.py:76` | Same as in the sender. |
| `fBuildAckFrame` | `PingMessageReceive.py:82` | ACK frame carrying the payload CRC-32. |
| `fParseFrame` | `PingMessageReceive.py:88` | Same as in the sender. |
| `fFindFrames` | `PingMessageReceive.py:114` | Same as in the sender. |
| `fIcmpChecksum` | `PingMessageReceive.py:127` | Internet checksum (RFC 1071). |
| `fBuildEchoReply` | `PingMessageReceive.py:138` | Builds an ICMP echo reply message. |
| `fBuildAckPayload` | `PingMessageReceive.py:144` | Reply data: request bytes before the first frame, then the ACK frame repeated. |
| `fNewSession` | `PingMessageReceive.py:153` | Empty state dictionary of a transfer. |
| `fSanitizeFileName` | `PingMessageReceive.py:166` | Makes a network-supplied name safe to use inside the output directory. |
| `fDecodeBlob` | `PingMessageReceive.py:174` | Decompresses (capped) and splits the payload into name and content. |
| `fSaveFile` | `PingMessageReceive.py:192` | Saves without overwriting (`.1`, `.2`, ... suffixes). |
| `fLogProgress` | `PingMessageReceive.py:207` | Logs the progress of a transfer every 10%. |
| `fCompleteSession` | `PingMessageReceive.py:217` | Joins the chunks, checks the CRC-32, decodes and saves the file. |
| `fProcessFrame` | `PingMessageReceive.py:239` | Updates the session with a header or data frame; returns the ACK frame and the saved path. |
| `fReceivePacket` | `PingMessageReceive.py:285` | `recvmsg` on the raw socket plus the `IP_PKTINFO` addresses. |
| `fGetReplySource` | `PingMessageReceive.py:297` | Source address of the reply and whether the request was unicast. |
| `fSendEchoReply` | `PingMessageReceive.py:308` | Sends the reply from the pinged address (`IP_PKTINFO`), falling back to `sendto`. |
| `fHandlePacket` | `PingMessageReceive.py:324` | Processes one IP packet: validates ICMP, finds frames, answers. |
| `fPurgeSessions` | `PingMessageReceive.py:357` | Forgets sessions silent for more than `cSessionTimeout`. |
| `fReadEchoIgnore` / `fWriteEchoIgnore` | `PingMessageReceive.py:365` / `PingMessageReceive.py:370` | Read and write `icmp_echo_ignore_all`. |
| `fHandleSignal` | `PingMessageReceive.py:375` | Turns `SIGTERM`/`SIGHUP` into `SystemExit`. |
| `fParseArguments` | `PingMessageReceive.py:380` | Command-line options. |
| `fMain` | `PingMessageReceive.py:390` | Socket setup, echo-ignore switch, receive loop, restore. |
| `__main__` block | `PingMessageReceive.py:458` | Signal handlers, exit codes and error reporting. |

## 4. Main flows

### 4.1 Sending a file

```text
__main__                                   PingMessageSend.py:311
└─ fMain                                   PingMessageSend.py:247
   ├─ fParseArguments                      PingMessageSend.py:222
   ├─ shutil.which('ping')
   ├─ fResolveTarget                       PingMessageSend.py:205
   ├─ fBuildBlob                           PingMessageSend.py:123   (zlib.compress, only if smaller)
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

`ping` exit code `0` (reply) and `1` (no reply) are normal; any other code counts as an error, and `cMaxConsecutiveErrors` errors in a row abort the transfer.

### 4.2 Receiving a file

```text
__main__                                   PingMessageReceive.py:458   (SIGTERM/SIGHUP → fHandleSignal)
└─ fMain                                   PingMessageReceive.py:390
   ├─ fParseArguments                      PingMessageReceive.py:380
   ├─ socket(AF_INET, SOCK_RAW, IPPROTO_ICMP) + IP_PKTINFO
   ├─ fReadEchoIgnore / fWriteEchoIgnore('1')   (unless --no-ack)
   ├─ loop:
   │  ├─ fReceivePacket                    PingMessageReceive.py:285
   │  ├─ fHandlePacket                     PingMessageReceive.py:324
   │  │  ├─ fIcmpChecksum                  (echo requests with a valid checksum only)
   │  │  ├─ fFindFrames → fParseFrame      (first header or data frame of the payload)
   │  │  ├─ fProcessFrame                  PingMessageReceive.py:239
   │  │  │  ├─ fNewSession                 (first frame of a (source IP, session))
   │  │  │  ├─ header: store size, CRC-32, flags, total; restart if they changed
   │  │  │  ├─ data: store the chunk by sequence; fLogProgress
   │  │  │  └─ all chunks present → fCompleteSession
   │  │  │     └─ CRC-32 check → fDecodeBlob → fSaveFile → fSanitizeFileName
   │  │  ├─ fBuildAckPayload               (if the session is completed)
   │  │  ├─ fGetReplySource
   │  │  └─ fSendEchoReply → fBuildEchoReply → fIcmpChecksum
   │  └─ fPurgeSessions                    (every cPurgeInterval seconds)
   └─ finally: fWriteEchoIgnore(original value), socket close
```

### 4.3 Acknowledgement

1. The data frame that completes the file reaches `fProcessFrame`, which saves the file and returns `fBuildAckFrame(session, CRC-32)`.
2. `fHandlePacket` replaces the reply data with `fBuildAckPayload`: it keeps the bytes before the frame offset (the `ping` timestamp, so the round-trip time is still computed) and fills the rest with the ACK frame repeated.
3. Every later frame of a completed session also gets an ACK reply (`dSession['completed']`), so the ACK is repeated until the sender stops.
4. On the sender, `ping` sees different data and prints the `wrong data byte` dump; `fIsAckReply` finds the ACK frame with the same session and CRC-32 and the main loop stops.

### 4.4 Receiver start and shutdown

 - Start: open the raw socket (fails without root) → read `icmp_echo_ignore_all` → write `1` → remember the original value. If the original value was `1`, only protocol pings are answered (`vAnswerAllPings = False`). If writing fails, acknowledgements are disabled.
 - `--once`: after the first saved file, keep answering for `cOnceLingerSeconds` (5 s) when acknowledgements are on, then leave the loop.
 - Shutdown (`Ctrl+C`, `SystemExit` from a signal, `--once`, an exception): the `finally` of `fMain` writes the original value back and closes the socket.

## 5. Entry points

| Command | Handler | File |
|---|---|---|
| `PingMessageSend.py -f FILE -t TARGET [-r ROUNDS] [-i INTERVAL] [-W TIMEOUT] [-H HEADER_EVERY] [--no-compress]` | `fMain` (`fParseArguments` for the options) | `PingMessageSend.py` |
| `PingMessageReceive.py [-o OUTPUT_DIR] [--no-ack] [--once]` | `fMain` (`fParseArguments` for the options) | `PingMessageReceive.py` |

Sender options (`fParseArguments`, `PingMessageSend.py:222`):

| Option | Attribute | Default | Validation |
|---|---|---|---|
| `-f`, `--file` | `file` | required | must be an existing file |
| `-t`, `--target` | `target` | required | resolved by `fResolveTarget` |
| `-r`, `--rounds` | `rounds` | `0` (unlimited) | `>= 0` |
| `-i`, `--interval` | `interval` | `cDefaultInterval` (0.01) | `>= 0` |
| `-W`, `--timeout` | `timeout` | `cDefaultTimeout` (1.0) | `> 0` |
| `-H`, `--header-every` | `header_every` | `cDefaultHeaderEvery` (32) | `>= 1` |
| `--no-compress` | `no_compress` | `False` | |

Receiver options (`fParseArguments`, `PingMessageReceive.py:380`):

| Option | Attribute | Default |
|---|---|---|
| `-o`, `--output-dir` | `output_dir` | `.` |
| `--no-ack` | `no_ack` | `False` |
| `--once` | `once` | `False` |

Exit codes: sender `0` (finished, with or without ACK), `1` (error), `130` (`Ctrl+C`); receiver `0` (`--once`), `1` (error), `130` (`Ctrl+C`), `129`/`143` (`SIGHUP`/`SIGTERM`).

## 6. Impact analysis

| Component | What is affected if it changes |
|---|---|
| Protocol constants (`cMagic`, `cType*`, `cFrameSize`, `cChunkSize`, `cMaxChunks`, `cFlagCompressed`) | Both scripts must change together; older versions stop interoperating. `cFrameSize` cannot exceed 16 (limit of `ping -p`). `cChunkSize` is tied to the data body layout (10 bytes = 3 of sequence + 7 of chunk) and to `cMaxBlobSize`. |
| `fBuildFrame`, `fParseFrame`, `fCrc16` | The wire format. Any change breaks compatibility; must be identical in both scripts. `fParseFrame` returns `None` for unknown types, so new types are ignored by old versions. |
| `fFindFrames` | Used by the receiver on every echo request and by the sender on every reply dump. A slower implementation slows down both; a stricter one may miss frames at unusual offsets. |
| `fGetSessionId` | Sender only. Changing it changes the session of every file; resumes from an older sender are not recognized (harmless otherwise). |
| Payload layout (`fBuildBlob` ↔ `fDecodeBlob`) | Name length byte, name, content, optional zlib. Both ends must agree; `cMaxNameLength` (255) is bound to the 1-byte length. |
| `fPing` / `fExtractReplyDump` | ACK detection depends on the output of iputils `ping` and on `LC_ALL=C`. A different `ping` implementation or format breaks ACK detection (transfers still work with `--rounds`). |
| `fBuildAckPayload` | Must keep the bytes before the frame (timestamp) so `ping` accepts the reply and computes the RTT, and must place the ACK where `ping` dumps the data. |
| `icmp_echo_ignore_all` handling in `fMain` (receiver) | Changes how the whole host answers pings. The restore lives in `finally`; a `SIGKILL` leaves the value at `1`. |
| `fHandlePacket` reply logic (`pAnswerAllPings`, `fGetReplySource`) | Decides which pings the host answers while the receiver runs (unicast only, all or only protocol pings). |
| `fSanitizeFileName`, `fSaveFile`, `cMaxDecompressedSize` | Security boundary of the receiver: path traversal, overwriting and decompression bombs. |
| `fCompleteSession` | On CRC-32 mismatch or decode error it clears the chunks and waits for the next round; changing it changes the recovery behavior. |
| `cSessionTimeout`, `cPurgeInterval` | Memory used by abandoned transfers and how long a paused transfer can be resumed. |

## 7. Extension points

### Add a command-line option

1. Add it in `fParseArguments` of the script, with its validation.
2. Use `vArgs.<attribute>` in `fMain` or pass it down as a parameter.
3. Update the options tables of [section 5](#5-entry-points), the MANUAL and the README (all languages).

### Add a frame type

1. Define `cType<Name>` with the same value in both scripts.
2. Add its body layout to `fParseFrame` in both scripts (otherwise it returns `None` and the frame is ignored).
3. Receiver: handle it in `fHandlePacket` (which today only processes `cTypeHeader` and `cTypeData` from requests) or in `fProcessFrame`. Sender: build it with `fBuildFrame` and, if it travels in replies, detect it like `fIsAckReply`.
4. Document the layout in [section 8](#8-wire-protocol).

### Add a payload flag (for example, encryption)

1. Define `cFlag<Name>` with the same value in both scripts.
2. Set it in `fBuildBlob` (sender) and honor it in `fDecodeBlob` (receiver).
3. Old receivers ignore unknown flags and would save the transformed data as is; if that is not acceptable, change `cMagic` so old versions ignore the new frames.

### Change the payload limits

`cMaxChunks` is bounded by the 24-bit sequence number and the header carries the size in 32 bits. Raising the limits requires changing the data or header body layout in both scripts (see [section 6](#6-impact-analysis)).

## 8. Wire protocol

### 8.1 Frame (16 bytes, big endian)

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Magic `0xA7` (`cMagic`) |
| 1 | 1 | Type: `0x01` header, `0x02` data, `0x03` ACK |
| 2 | 2 | Session identifier |
| 4 | 10 | Body (depends on the type) |
| 14 | 2 | CRC-16/CCITT-FALSE (polynomial `0x1021`, initial value `0xFFFF`) of bytes 0 to 13 |

### 8.2 Bodies (10 bytes)

| Type | Layout |
|---|---|
| Header (`0x01`) | payload size (4) \| payload CRC-32 (4) \| flags (1, bit `0x01` = zlib) \| reserved (1, `0`) |
| Data (`0x02`) | sequence (3) \| chunk (7, the last one padded with `0x00`) |
| ACK (`0x03`) | payload CRC-32 (4) \| reserved (6, `0`) |

### 8.3 Payload

Before the optional compression: `name length (1) | name (UTF-8, up to 255 bytes) | file content`. The payload is compressed with zlib level 9 only if the result is smaller, and the header flag `0x01` is set. The CRC-32 in the header and in the ACK is computed over the payload as transmitted (after compression).

Limits: `cMaxChunks = 2^24` data frames of 7 bytes, so `cMaxBlobSize = 117440512` bytes of payload. The receiver caps the decompressed payload at 1 GiB.

### 8.4 Session identifier

`session = ((crc32 >> 16) XOR crc32) AND 0xFFFF`, where `crc32` is the CRC-32 of the payload. The receiver keys its state by `(source IPv4 address, session)`.

### 8.5 Round

```text
header, data 0 ... data 31, header, data 32 ... data 63, header, ...
```

The header frame is sent before every data frame whose sequence is a multiple of `--header-every` (32 by default). Frames per round = `chunks + ceil(chunks / header_every)`.

### 8.6 Placement inside the ICMP payload

 - Request: `ping -p <32 hex digits>` fills the ICMP data with the 16-byte frame repeated; `ping` overwrites the first bytes with its timestamp, so the first complete frame is not at a fixed offset. The receiver uses the first valid header or data frame found by `fFindFrames`.
 - Reply without ACK: the same data as the request (like the kernel would answer).
 - Reply with ACK: the request bytes before the offset of the first frame, followed by the ACK frame repeated up to the original length.
 - On the sender, iputils `ping` detects that the reply data differs and prints it as `#<offset>\t<hex bytes>` lines, which `fExtractReplyDump` turns back into bytes.
