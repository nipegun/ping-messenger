#!/usr/bin/env -S PYTHONDONTWRITEBYTECODE=1 python3

# PingMessageSend.py
#
# Sends a file (text or binary) to a remote host hidden inside the payload of
# ICMP echo requests. Every request is generated with the system "ping" command
# and its "-p" (pattern) option, which accepts up to 16 bytes, so every ping
# carries exactly one 16-byte protocol frame.
#
# The file is sent in rounds that repeat until the receiver (PingMessageReceive.py)
# acknowledges it by answering a ping with an ACK frame, or until the maximum
# number of rounds is reached.
#
# Protocol details: doc/CODE.md

import argparse
import binascii
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import zlib

# Protocol constants (must be identical in PingMessageReceive.py)
cMagic = 0xA7
cTypeHeader = 0x01
cTypeData = 0x02
cTypeAck = 0x03
cFrameSize = 16
cChunkSize = 7
cMaxChunks = 2 ** 24
cMaxBlobSize = cMaxChunks * cChunkSize
cMaxNameLength = 255
cFlagCompressed = 0x01

# Sender defaults
cDefaultHeaderEvery = 32
cDefaultInterval = 0.01
cDefaultTimeout = 1.0
cMaxConsecutiveErrors = 10


def fCrc16(pData):
  # CRC-16/CCITT-FALSE (polynomial 0x1021, initial value 0xFFFF)
  return binascii.crc_hqx(pData, 0xFFFF)


def fGetChunkCount(pBlobSize):
  return (pBlobSize + cChunkSize - 1) // cChunkSize


def fGetFramesPerRound(pChunkCount, pHeaderEvery):
  return pChunkCount + (pChunkCount + pHeaderEvery - 1) // pHeaderEvery


def fGetSessionId(pBlobCrc):
  # The session id is derived from the blob checksum, so sending the same file
  # again produces the same session and the receiver recognises it
  return ((pBlobCrc >> 16) ^ pBlobCrc) & 0xFFFF


def fBuildFrame(pType, pSessionId, pBody):
  # Frame layout: magic (1) | type (1) | session (2) | body (10) | CRC-16 (2)
  vFrame = struct.pack('!BBH', cMagic, pType, pSessionId) + pBody
  return vFrame + struct.pack('!H', fCrc16(vFrame))


def fBuildHeaderFrame(pSessionId, pBlobSize, pBlobCrc, pFlags):
  # Header body: blob size (4) | blob CRC-32 (4) | flags (1) | reserved (1)
  vBody = struct.pack('!IIBB', pBlobSize, pBlobCrc, pFlags, 0)
  return fBuildFrame(cTypeHeader, pSessionId, vBody)


def fBuildDataFrame(pSessionId, pSequence, pChunk):
  # Data body: sequence (3) | chunk (7, the last one padded with zeros)
  vBody = pSequence.to_bytes(3, 'big') + pChunk.ljust(cChunkSize, b'\x00')
  return fBuildFrame(cTypeData, pSessionId, vBody)


def fParseFrame(pFrame):
  # Returns a dictionary with the frame fields, or None if it is not a valid frame
  if len(pFrame) != cFrameSize or pFrame[0] != cMagic:
    return None
  vExpectedCrc = struct.unpack('!H', pFrame[14:16])[0]
  if fCrc16(pFrame[:14]) != vExpectedCrc:
    return None
  vType = pFrame[1]
  vSessionId = struct.unpack('!H', pFrame[2:4])[0]
  vBody = pFrame[4:14]
  dFrame = {'type': vType, 'session': vSessionId}
  if vType == cTypeHeader:
    vSize, vCrc, vFlags, vReserved = struct.unpack('!IIBB', vBody)
    dFrame['size'] = vSize
    dFrame['crc'] = vCrc
    dFrame['flags'] = vFlags
  elif vType == cTypeData:
    dFrame['sequence'] = int.from_bytes(vBody[:3], 'big')
    dFrame['chunk'] = vBody[3:]
  elif vType == cTypeAck:
    dFrame['crc'] = struct.unpack('!I', vBody[:4])[0]
  else:
    return None
  return dFrame


def fFindFrames(pData):
  # Scans every offset because the position of the pattern inside the ICMP
  # payload depends on the size of the timestamp that ping writes first
  lFrames = []
  for vOffset in range(len(pData) - cFrameSize + 1):
    if pData[vOffset] != cMagic:
      continue
    dFrame = fParseFrame(pData[vOffset:vOffset + cFrameSize])
    if dFrame is not None:
      lFrames.append((vOffset, dFrame))
  return lFrames


def fBuildBlob(pFilePath, pCompress):
  # Blob layout before compression: name length (1) | name (UTF-8) | file content
  vNameBytes = os.path.basename(pFilePath).encode('utf-8', errors='surrogateescape')
  if len(vNameBytes) > cMaxNameLength:
    vNameBytes = vNameBytes[:cMaxNameLength].decode('utf-8', errors='ignore').encode('utf-8')
  try:
    with open(pFilePath, 'rb') as vFile:
      vContent = vFile.read()
  except OSError as vError:
    raise RuntimeError(f'unable to read "{pFilePath}": {vError}') from vError
  vRawBlob = bytes([len(vNameBytes)]) + vNameBytes + vContent
  vBlob = vRawBlob
  vFlags = 0
  if pCompress:
    vCompressedBlob = zlib.compress(vRawBlob, 9)
    if len(vCompressedBlob) < len(vRawBlob):
      vBlob = vCompressedBlob
      vFlags = vFlags | cFlagCompressed
  if len(vBlob) > cMaxBlobSize:
    raise RuntimeError(f'the file is too big: the payload takes {len(vBlob)} bytes and the protocol limit is {cMaxBlobSize} bytes')
  return vBlob, vFlags, len(vContent)


def fIterRoundFrames(pSessionId, pBlob, pBlobCrc, pFlags, pHeaderEvery):
  # One round: the header frame, then the data frames, with the header repeated
  # every pHeaderEvery data frames so a receiver that starts late learns the size
  vHeaderFrame = fBuildHeaderFrame(pSessionId, len(pBlob), pBlobCrc, pFlags)
  for vSequence in range(fGetChunkCount(len(pBlob))):
    if vSequence % pHeaderEvery == 0:
      yield vHeaderFrame
    vStart = vSequence * cChunkSize
    yield fBuildDataFrame(pSessionId, vSequence, pBlob[vStart:vStart + cChunkSize])


def fPing(pTargetIp, pPattern, pTimeout):
  # Returns (exit code, stdout, stderr) of a single "ping -p"
  lCommand = ['ping', '-n', '-c', '1', '-W', f'{pTimeout:g}', '-p', pPattern, pTargetIp]
  dEnvironment = dict(os.environ)
  # Untranslated output, so the reply dump can always be parsed
  dEnvironment['LC_ALL'] = 'C'
  try:
    vResult = subprocess.run(
      lCommand,
      capture_output=True,
      text=True,
      encoding='utf-8',
      errors='replace',
      env=dEnvironment,
      timeout=pTimeout + 10
    )
  except subprocess.TimeoutExpired:
    return 1, '', 'ping did not finish in time'
  return vResult.returncode, vResult.stdout, vResult.stderr


def fExtractReplyDump(pPingOutput):
  # When the data of an echo reply differs from the data sent, iputils ping
  # prints "wrong data byte ..." followed by a hex dump of the received data in
  # lines like "#16\ta7 3 1f ...". This rebuilds those bytes.
  lBytes = []
  for vLine in pPingOutput.splitlines():
    vMatch = re.match(r'^#\d+\s+(.*)$', vLine)
    if vMatch is None:
      continue
    for vToken in vMatch.group(1).split():
      try:
        vByte = int(vToken, 16)
      except ValueError:
        continue
      if 0 <= vByte <= 255:
        lBytes.append(vByte)
  return bytes(lBytes)


def fIsAckReply(pPingOutput, pSessionId, pBlobCrc):
  vDump = fExtractReplyDump(pPingOutput)
  for vOffset, dFrame in fFindFrames(vDump):
    if dFrame['type'] == cTypeAck and dFrame['session'] == pSessionId and dFrame['crc'] == pBlobCrc:
      return True
  return False


def fResolveTarget(pTarget):
  try:
    lAddresses = socket.getaddrinfo(pTarget, None, socket.AF_INET)
  except socket.gaierror as vError:
    raise RuntimeError(f'unable to resolve "{pTarget}" to an IPv4 address: {vError}') from vError
  return lAddresses[0][4][0]


def fPrintProgress(pIsTty, pRound, pFrameIndex, pFramesPerRound, pReplies, pForce):
  vPercent = pFrameIndex * 100 / pFramesPerRound
  vLine = f'Round {pRound}: ping {pFrameIndex}/{pFramesPerRound} ({vPercent:5.1f}%), replies: {pReplies}'
  if pIsTty:
    print(f'\r{vLine}', end='', flush=True)
  elif pForce or pFrameIndex == pFramesPerRound:
    print(vLine, flush=True)


def fParseArguments():
  vParser = argparse.ArgumentParser(
    description='Send a file hidden inside the payload of ICMP echo requests (ping -p).'
  )
  vParser.add_argument('-f', '--file', required=True, help='File to send (text or binary).')
  vParser.add_argument('-t', '--target', required=True, help='IPv4 address or FQDN of the host running PingMessageReceive.py.')
  vParser.add_argument('-r', '--rounds', type=int, default=0, help='Maximum number of full passes over the file. 0 repeats until the receiver acknowledges it. Default: 0.')
  vParser.add_argument('-i', '--interval', type=float, default=cDefaultInterval, help=f'Seconds to wait between pings. Default: {cDefaultInterval:g}.')
  vParser.add_argument('-W', '--timeout', type=float, default=cDefaultTimeout, help=f'Seconds to wait for each echo reply. Default: {cDefaultTimeout:g}.')
  vParser.add_argument('-H', '--header-every', type=int, default=cDefaultHeaderEvery, help=f'Repeat the header frame every N data frames. Default: {cDefaultHeaderEvery}.')
  vParser.add_argument('--no-compress', action='store_true', help='Do not compress the file with zlib before sending it.')
  vArgs = vParser.parse_args()
  if vArgs.rounds < 0:
    vParser.error('--rounds must be 0 or greater')
  if vArgs.interval < 0:
    vParser.error('--interval must be 0 or greater')
  if vArgs.timeout <= 0:
    vParser.error('--timeout must be greater than 0')
  if vArgs.header_every < 1:
    vParser.error('--header-every must be 1 or greater')
  if not os.path.isfile(vArgs.file):
    vParser.error(f'file not found: {vArgs.file}')
  return vArgs


def fMain():
  vArgs = fParseArguments()
  if shutil.which('ping') is None:
    raise RuntimeError('the "ping" command was not found (install the iputils-ping package)')
  vTargetIp = fResolveTarget(vArgs.target)
  vBlob, vFlags, vFileSize = fBuildBlob(vArgs.file, not vArgs.no_compress)
  vBlobCrc = zlib.crc32(vBlob) & 0xFFFFFFFF
  vSessionId = fGetSessionId(vBlobCrc)
  vChunkCount = fGetChunkCount(len(vBlob))
  vFramesPerRound = fGetFramesPerRound(vChunkCount, vArgs.header_every)
  vIsTty = sys.stdout.isatty()
  vCompression = 'zlib compressed' if vFlags & cFlagCompressed else 'uncompressed'
  vRoundsText = str(vArgs.rounds) if vArgs.rounds > 0 else 'unlimited, until the receiver acknowledges'

  print(f'File:       {vArgs.file} ({vFileSize} bytes)')
  print(f'Target:     {vArgs.target} ({vTargetIp})')
  print(f'Session:    0x{vSessionId:04x}')
  print(f'Payload:    {len(vBlob)} bytes ({vCompression}), {vChunkCount} data frames')
  print(f'Round:      {vFramesPerRound} pings (header every {vArgs.header_every} data frames)')
  print(f'Rounds:     {vRoundsText}')

  vRound = 0
  vPingsSent = 0
  vRepliesReceived = 0
  vConsecutiveErrors = 0
  vAcknowledged = False
  vStartTime = time.monotonic()
  while not vAcknowledged and (vArgs.rounds == 0 or vRound < vArgs.rounds):
    vRound = vRound + 1
    vFrameIndex = 0
    for vFrame in fIterRoundFrames(vSessionId, vBlob, vBlobCrc, vFlags, vArgs.header_every):
      vFrameIndex = vFrameIndex + 1
      vReturnCode, vStdout, vStderr = fPing(vTargetIp, vFrame.hex(), vArgs.timeout)
      vPingsSent = vPingsSent + 1
      if vReturnCode == 0:
        vRepliesReceived = vRepliesReceived + 1
      if vReturnCode in (0, 1):
        # 1 only means that no reply arrived: the request may still have reached the receiver
        vConsecutiveErrors = 0
      else:
        vConsecutiveErrors = vConsecutiveErrors + 1
        vMessage = vStderr.strip() or f'ping exited with code {vReturnCode}'
        print(f'\nWarning: {vMessage}', file=sys.stderr)
        if vConsecutiveErrors >= cMaxConsecutiveErrors:
          raise RuntimeError(f'ping failed {cMaxConsecutiveErrors} times in a row')
      if fIsAckReply(vStdout, vSessionId, vBlobCrc):
        vAcknowledged = True
      fPrintProgress(vIsTty, vRound, vFrameIndex, vFramesPerRound, vRepliesReceived, vAcknowledged)
      if vAcknowledged:
        break
      if vArgs.interval > 0:
        time.sleep(vArgs.interval)

  if vIsTty:
    print()
  vElapsed = time.monotonic() - vStartTime
  print(f'Pings sent: {vPingsSent}, replies: {vRepliesReceived}, elapsed: {vElapsed:.1f} s')
  if vAcknowledged:
    print('The receiver acknowledged the file. Transfer complete.')
  else:
    print('All the rounds were sent without an acknowledgement from the receiver.')
  return 0


if __name__ == '__main__':
  vExitCode = 1
  try:
    vExitCode = fMain()
  except KeyboardInterrupt:
    print('\nInterrupted by the user.', file=sys.stderr)
    vExitCode = 130
  except Exception as vError:
    print(f'\nError: {vError}', file=sys.stderr)
    vExitCode = 1
  finally:
    sys.stdout.flush()
  sys.exit(vExitCode)
