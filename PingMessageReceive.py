#!/usr/bin/env -S PYTHONDONTWRITEBYTECODE=1 python3

# PingMessageReceive.py
#
# Listens for ICMP echo requests and rebuilds the files that PingMessageSend.py
# hides inside their payload (one 16-byte protocol frame per ping).
#
# The receiver can start listening at any moment: frames are stored by session
# and sequence number, the header frame (repeated by the sender) gives the
# total size, and the frames received again in later rounds are ignored.
#
# Unless --no-ack is given, the automatic echo replies of the kernel are
# disabled while the receiver runs (net.ipv4.icmp_echo_ignore_all) and the
# receiver answers the pings itself. Once a file is complete, the replies to
# that session carry an ACK frame, which tells the sender that it can stop.
#
# Requires root privileges (raw socket).
#
# Protocol details: doc/CODE.md

import argparse
import binascii
import datetime
import ipaddress
import os
import signal
import socket
import struct
import sys
import time
import zlib

# Protocol constants (must be identical in PingMessageSend.py)
cMagic = 0xA7
cTypeHeader = 0x01
cTypeData = 0x02
cTypeAck = 0x03
cFrameSize = 16
cChunkSize = 7
cMaxChunks = 2 ** 24
cMaxBlobSize = cMaxChunks * cChunkSize
cFlagCompressed = 0x01

# Receiver settings
cIcmpEchoReply = 0
cIcmpEchoRequest = 8
cIpPktInfo = getattr(socket, 'IP_PKTINFO', 8)
cEchoIgnorePath = '/proc/sys/net/ipv4/icmp_echo_ignore_all'
cSocketTimeout = 1.0
cSessionTimeout = 600
cPurgeInterval = 30
cOnceLingerSeconds = 5
cMaxDecompressedSize = 1024 * 1024 * 1024
cDefaultFileName = 'received.bin'


def fGetDisplayDate():
  # UTC date in the display format of the project: 2026/10/29@13:59:59.723
  vNow = datetime.datetime.now(datetime.timezone.utc)
  return vNow.strftime('%Y/%m/%d@%H:%M:%S.') + f'{vNow.microsecond // 1000:03d}'


def fLog(pMessage):
  print(f'[{fGetDisplayDate()}] {pMessage}', flush=True)


def fCrc16(pData):
  # CRC-16/CCITT-FALSE (polynomial 0x1021, initial value 0xFFFF)
  return binascii.crc_hqx(pData, 0xFFFF)


def fGetChunkCount(pBlobSize):
  return (pBlobSize + cChunkSize - 1) // cChunkSize


def fBuildFrame(pType, pSessionId, pBody):
  # Frame layout: magic (1) | type (1) | session (2) | body (10) | CRC-16 (2)
  vFrame = struct.pack('!BBH', cMagic, pType, pSessionId) + pBody
  return vFrame + struct.pack('!H', fCrc16(vFrame))


def fBuildAckFrame(pSessionId, pBlobCrc):
  # ACK body: blob CRC-32 (4) | reserved (6)
  vBody = struct.pack('!I', pBlobCrc) + bytes(6)
  return fBuildFrame(cTypeAck, pSessionId, vBody)


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


def fIcmpChecksum(pData):
  # Internet checksum (RFC 1071). Over a whole ICMP message it returns 0 when the message is valid.
  vData = pData
  if len(vData) % 2 == 1:
    vData = vData + b'\x00'
  vSum = sum(struct.unpack(f'!{len(vData) // 2}H', vData))
  while vSum >> 16:
    vSum = (vSum & 0xFFFF) + (vSum >> 16)
  return (~vSum) & 0xFFFF


def fBuildEchoReply(pIdentifier, pSequence, pData):
  vHeader = struct.pack('!BBHHH', cIcmpEchoReply, 0, 0, pIdentifier, pSequence)
  vChecksum = fIcmpChecksum(vHeader + pData)
  return struct.pack('!BBHHH', cIcmpEchoReply, 0, vChecksum, pIdentifier, pSequence) + pData


def fBuildAckPayload(pRequestData, pFrameOffset, pAckFrame):
  # Keeps the bytes before the first frame (the ping timestamp, needed for the
  # round-trip time) and fills the rest with the ACK frame repeated, just like
  # ping fills the payload with its pattern
  vLength = len(pRequestData) - pFrameOffset
  vRepeated = (pAckFrame * (vLength // cFrameSize + 1))[:vLength]
  return pRequestData[:pFrameOffset] + vRepeated


def fNewSession():
  return {
    'chunks': {},
    'size': None,
    'crc': None,
    'flags': 0,
    'total': None,
    'completed': False,
    'lastSeen': time.monotonic(),
    'lastStep': -1,
  }


def fSanitizeFileName(pName):
  # The name comes from the network: it must never leave the output directory
  vName = pName.replace('\x00', '').replace('/', '_').replace('\\', '_').strip()
  if vName in ('', '.', '..'):
    vName = cDefaultFileName
  return vName


def fDecodeBlob(pBlob, pFlags):
  # Returns (file name, file content) from a complete blob
  vRawBlob = pBlob
  if pFlags & cFlagCompressed:
    vDecompressor = zlib.decompressobj()
    vRawBlob = vDecompressor.decompress(pBlob, cMaxDecompressedSize)
    if vDecompressor.unconsumed_tail:
      raise ValueError(f'the decompressed file exceeds the limit of {cMaxDecompressedSize} bytes')
    if not vDecompressor.eof:
      raise ValueError('the compressed data is incomplete')
  if len(vRawBlob) < 1 or len(vRawBlob) < 1 + vRawBlob[0]:
    raise ValueError('malformed payload')
  vNameLength = vRawBlob[0]
  vName = vRawBlob[1:1 + vNameLength].decode('utf-8', errors='replace')
  vContent = vRawBlob[1 + vNameLength:]
  return vName, vContent


def fSaveFile(pOutputDir, pName, pContent):
  # Never overwrites: adds .1, .2, ... to the name if the file already exists
  vName = fSanitizeFileName(pName)
  vPath = os.path.join(pOutputDir, vName)
  vCounter = 0
  while True:
    try:
      with open(vPath, 'xb') as vFile:
        vFile.write(pContent)
      return vPath
    except FileExistsError:
      vCounter = vCounter + 1
      vPath = os.path.join(pOutputDir, f'{vName}.{vCounter}')


def fLogProgress(pLabel, pSession):
  if pSession['total'] is None:
    return
  vReceived = len(pSession['chunks'])
  vStep = vReceived * 10 // pSession['total']
  if vStep > pSession['lastStep']:
    pSession['lastStep'] = vStep
    fLog(f'{pLabel}: {vReceived}/{pSession["total"]} data frames ({vStep * 10}%)')


def fCompleteSession(pLabel, pSession, pOutputDir):
  # Rebuilds, verifies and saves the file. Returns the saved path, or None.
  vBlob = b''.join(pSession['chunks'][vSequence] for vSequence in range(pSession['total']))[:pSession['size']]
  if zlib.crc32(vBlob) & 0xFFFFFFFF != pSession['crc']:
    fLog(f'{pLabel}: CRC-32 mismatch, discarding the data frames and waiting for the next round')
    pSession['chunks'] = {}
    pSession['lastStep'] = -1
    return None
  try:
    vName, vContent = fDecodeBlob(vBlob, pSession['flags'])
    vPath = fSaveFile(pOutputDir, vName, vContent)
  except (ValueError, zlib.error, OSError) as vError:
    fLog(f'{pLabel}: unable to save the file ({vError}), waiting for the next round')
    pSession['chunks'] = {}
    pSession['lastStep'] = -1
    return None
  pSession['completed'] = True
  pSession['chunks'] = {}
  fLog(f'{pLabel}: file saved to "{vPath}" ({len(vContent)} bytes)')
  return vPath


def fProcessFrame(pSessions, pSourceIp, pFrame, pOutputDir):
  # Returns (ACK frame to send back or None, path of the file saved now or None)
  vSessionId = pFrame['session']
  vKey = (pSourceIp, vSessionId)
  vLabel = f'{pSourceIp} 0x{vSessionId:04x}'
  dSession = pSessions.get(vKey)
  if dSession is None:
    dSession = fNewSession()
    pSessions[vKey] = dSession
    fLog(f'{vLabel}: new transfer detected')
  dSession['lastSeen'] = time.monotonic()

  if pFrame['type'] == cTypeHeader:
    if dSession['size'] is not None and (pFrame['size'], pFrame['crc']) != (dSession['size'], dSession['crc']):
      fLog(f'{vLabel}: the header changed (another file is using this session), starting over')
      dSession = fNewSession()
      pSessions[vKey] = dSession
    if dSession['size'] is None:
      if pFrame['size'] < 1 or pFrame['size'] > cMaxBlobSize:
        fLog(f'{vLabel}: ignoring a header with an invalid size ({pFrame["size"]} bytes)')
        return None, None
      dSession['size'] = pFrame['size']
      dSession['crc'] = pFrame['crc']
      dSession['flags'] = pFrame['flags']
      dSession['total'] = fGetChunkCount(pFrame['size'])
      lOutOfRange = [vSequence for vSequence in dSession['chunks'] if vSequence >= dSession['total']]
      for vSequence in lOutOfRange:
        del dSession['chunks'][vSequence]
      vCompression = 'zlib compressed' if pFrame['flags'] & cFlagCompressed else 'uncompressed'
      fLog(f'{vLabel}: header received ({pFrame["size"]} bytes, {vCompression}, {dSession["total"]} data frames)')
  elif pFrame['type'] == cTypeData and not dSession['completed']:
    vSequence = pFrame['sequence']
    if dSession['total'] is None or vSequence < dSession['total']:
      if vSequence not in dSession['chunks']:
        dSession['chunks'][vSequence] = pFrame['chunk']
        fLogProgress(vLabel, dSession)

  if dSession['completed']:
    return fBuildAckFrame(vSessionId, dSession['crc']), None
  if dSession['total'] is not None and len(dSession['chunks']) == dSession['total']:
    vSavedPath = fCompleteSession(vLabel, dSession, pOutputDir)
    if vSavedPath is not None:
      return fBuildAckFrame(vSessionId, dSession['crc']), vSavedPath
  return None, None


def fReceivePacket(pSocket):
  # Returns (IP packet, (local address, header destination address) or None)
  vPacket, lAncillary, vFlags, vAddress = pSocket.recvmsg(65535, socket.CMSG_SPACE(12))
  vPktInfo = None
  for vLevel, vType, vData in lAncillary:
    if vLevel == socket.IPPROTO_IP and vType == cIpPktInfo and len(vData) >= 12:
      # struct in_pktinfo: ipi_ifindex | ipi_spec_dst | ipi_addr
      vInterfaceIndex, vSpecDst, vHeaderDst = struct.unpack('=i4s4s', vData[:12])
      vPktInfo = (socket.inet_ntoa(vSpecDst), socket.inet_ntoa(vHeaderDst))
  return vPacket, vPktInfo


def fGetReplySource(pDestinationIp, pPktInfo):
  # Returns (source address for the reply or None, whether the request was sent to a unicast local address).
  # Requests sent to broadcast or multicast addresses are not answered, as the kernel does by default.
  if pPktInfo is not None:
    vSpecDst, vHeaderDst = pPktInfo
    if vSpecDst != '0.0.0.0':
      return vSpecDst, vSpecDst == vHeaderDst
  vAddress = ipaddress.IPv4Address(pDestinationIp)
  return None, not (vAddress.is_multicast or pDestinationIp == '255.255.255.255')


def fSendEchoReply(pSocket, pReplyTo, pReplyFrom, pIdentifier, pSequence, pData):
  vPacket = fBuildEchoReply(pIdentifier, pSequence, pData)
  if pReplyFrom is not None:
    # Answers from the same address that was pinged
    vPktInfo = struct.pack('=i4s4s', 0, socket.inet_aton(pReplyFrom), bytes(4))
    try:
      pSocket.sendmsg([vPacket], [(socket.IPPROTO_IP, cIpPktInfo, vPktInfo)], 0, (pReplyTo, 0))
      return
    except OSError:
      pass
  try:
    pSocket.sendto(vPacket, (pReplyTo, 0))
  except OSError as vError:
    fLog(f'Warning: unable to send an echo reply to {pReplyTo}: {vError}')


def fHandlePacket(pSocket, pPacket, pPktInfo, pSessions, pOutputDir, pAckEnabled, pAnswerAllPings):
  # Processes one received IP packet. Returns the path of the file saved now, or None.
  if len(pPacket) < 20:
    return None
  vHeaderLength = (pPacket[0] & 0x0F) * 4
  if vHeaderLength < 20 or len(pPacket) < vHeaderLength + 8:
    return None
  vSourceIp = socket.inet_ntoa(pPacket[12:16])
  vDestinationIp = socket.inet_ntoa(pPacket[16:20])
  vIcmp = pPacket[vHeaderLength:]
  vType, vCode, vChecksum, vIdentifier, vSequence = struct.unpack('!BBHHH', vIcmp[:8])
  if vType != cIcmpEchoRequest or fIcmpChecksum(vIcmp) != 0:
    return None

  vData = vIcmp[8:]
  vReplyData = vData
  vIsProtocolFrame = False
  vSavedPath = None
  for vOffset, dFrame in fFindFrames(vData):
    if dFrame['type'] in (cTypeHeader, cTypeData):
      vIsProtocolFrame = True
      vAckFrame, vSavedPath = fProcessFrame(pSessions, vSourceIp, dFrame, pOutputDir)
      if vAckFrame is not None:
        vReplyData = fBuildAckPayload(vData, vOffset, vAckFrame)
      break

  if pAckEnabled and (pAnswerAllPings or vIsProtocolFrame):
    vReplyFrom, vIsUnicast = fGetReplySource(vDestinationIp, pPktInfo)
    if vIsUnicast:
      fSendEchoReply(pSocket, vSourceIp, vReplyFrom, vIdentifier, vSequence, vReplyData)
  return vSavedPath


def fPurgeSessions(pSessions):
  # Forgets the sessions that have been silent for a long time
  vNow = time.monotonic()
  for vKey in list(pSessions.keys()):
    if vNow - pSessions[vKey]['lastSeen'] > cSessionTimeout:
      del pSessions[vKey]


def fReadEchoIgnore():
  with open(cEchoIgnorePath, 'r') as vFile:
    return vFile.read().strip()


def fWriteEchoIgnore(pValue):
  with open(cEchoIgnorePath, 'w') as vFile:
    vFile.write(pValue)


def fHandleSignal(pSignalNumber, pStackFrame):
  # Turns SIGTERM and SIGHUP into a normal exit, so the finally blocks restore the system
  raise SystemExit(128 + pSignalNumber)


def fParseArguments():
  vParser = argparse.ArgumentParser(
    description='Receive the files that PingMessageSend.py hides inside ICMP echo requests.'
  )
  vParser.add_argument('-o', '--output-dir', default='.', help='Directory where the received files are saved. Default: current directory.')
  vParser.add_argument('--no-ack', action='store_true', help='Do not answer the pings nor send acknowledgements: the kernel keeps answering them.')
  vParser.add_argument('--once', action='store_true', help='Exit after receiving the first file.')
  return vParser.parse_args()


def fMain():
  vArgs = fParseArguments()
  vOutputDir = os.path.abspath(vArgs.output_dir)
  os.makedirs(vOutputDir, exist_ok=True)
  try:
    vSocket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
  except PermissionError as vError:
    raise RuntimeError('a raw ICMP socket needs root privileges (or CAP_NET_RAW)') from vError

  vOriginalEchoIgnore = None
  try:
    vSocket.setsockopt(socket.IPPROTO_IP, cIpPktInfo, 1)
    vSocket.settimeout(cSocketTimeout)
    vAckEnabled = not vArgs.no_ack
    vAnswerAllPings = True
    if vAckEnabled:
      try:
        vCurrentEchoIgnore = fReadEchoIgnore()
        fWriteEchoIgnore('1')
        vOriginalEchoIgnore = vCurrentEchoIgnore
        # If the host was already ignoring pings, only the protocol pings are answered
        vAnswerAllPings = vCurrentEchoIgnore != '1'
      except OSError as vError:
        fLog(f'Warning: unable to disable the kernel echo replies ({vError}), acknowledgements disabled')
        vAckEnabled = False

    fLog(f'Listening for ICMP echo requests, files will be saved to "{vOutputDir}"')
    if vAckEnabled:
      fLog(f'Acknowledgements enabled: {cEchoIgnorePath} set to 1 while the receiver runs')
    else:
      fLog('Acknowledgements disabled: the kernel answers the pings')

    dSessions = {}
    vLastPurge = time.monotonic()
    vFirstFileTime = None
    while True:
      if vArgs.once and vFirstFileTime is not None:
        if not vAckEnabled or time.monotonic() - vFirstFileTime >= cOnceLingerSeconds:
          break
      try:
        vPacket, vPktInfo = fReceivePacket(vSocket)
      except TimeoutError:
        vPacket = None
        vPktInfo = None
      if vPacket is not None:
        try:
          vSavedPath = fHandlePacket(vSocket, vPacket, vPktInfo, dSessions, vOutputDir, vAckEnabled, vAnswerAllPings)
        except Exception as vError:
          fLog(f'Warning: error while processing a packet: {vError}')
          vSavedPath = None
        if vSavedPath is not None and vFirstFileTime is None:
          vFirstFileTime = time.monotonic()
          if vArgs.once and vAckEnabled:
            fLog(f'Answering the sender for {cOnceLingerSeconds} more seconds before exiting')
      if time.monotonic() - vLastPurge >= cPurgeInterval:
        fPurgeSessions(dSessions)
        vLastPurge = time.monotonic()
  finally:
    if vOriginalEchoIgnore is not None:
      try:
        fWriteEchoIgnore(vOriginalEchoIgnore)
        fLog(f'{cEchoIgnorePath} restored to {vOriginalEchoIgnore}')
      except OSError as vError:
        fLog(f'Warning: unable to restore {cEchoIgnorePath} to {vOriginalEchoIgnore}: {vError}')
    vSocket.close()
  return 0


if __name__ == '__main__':
  vExitCode = 1
  try:
    signal.signal(signal.SIGTERM, fHandleSignal)
    signal.signal(signal.SIGHUP, fHandleSignal)
    vExitCode = fMain()
  except KeyboardInterrupt:
    print('', flush=True)
    fLog('Interrupted by the user')
    vExitCode = 130
  except Exception as vError:
    fLog(f'Error: {vError}')
    vExitCode = 1
  finally:
    sys.stdout.flush()
  sys.exit(vExitCode)
