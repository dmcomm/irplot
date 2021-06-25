#This file is part of the DMComm project by BladeSabre. License: MIT.

#Some Data Link interaction.
#Tested with CircuitPython 20210625-769805c on Pi Pico.

import array
import board
import time
import digitalio
import pulseio
import pwmio

TYPE_DATALINK = 0
TYPE_FUSION = 1

WAIT_FOREVER = None
WAIT_REPLY = -1

probePin = digitalio.DigitalInOut(board.GP8)
probePin.direction = digitalio.Direction.OUTPUT

demodPulsesIn = pulseio.PulseIn(board.GP9, maxlen=150, idle_state=True)
demodPulsesIn.pause()

demodPower = digitalio.DigitalInOut(board.GP10)
demodPower.direction = digitalio.Direction.OUTPUT
demodPower.value = True

pwm = pwmio.PWMOut(board.GP11, frequency=38000, duty_cycle=2**15)
pulseOut = pulseio.PulseOut(pwm)
pulseOut.send(array.array('H', [100, 100])) #workaround for bug?

#GP12 used for LED joint

#GP13 rawPulsesIn

rawPower = digitalio.DigitalInOut(board.GP14)
rawPower.direction = digitalio.Direction.OUTPUT
rawPower.value = True

logBuffer = array.array('L', range(2000))
logSize = 0
def addToLog(x):
	global logSize
	if logSize < len(logBuffer):
		logBuffer[logSize] = x
		logSize += 1

class WaitEnded(Exception):
	pass

class BadPacket(Exception):
	pass

class Params:
	def __init__(self, commType):
		if commType == TYPE_DATALINK:
			self.startPulseMin = 9000
			self.startPulseSend = 9800
			self.startPulseMax = 11000
			self.startGapMin = 2000
			self.startGapSend = 2450
			self.startGapMax = 3000
			self.bitPulseMin = 300
			self.bitPulseSend = 500
			self.bitPulseMax = 650
			self.bitGapMin = 300
			self.bitGapSendShort = 700
			self.bitGapThreshold = 800
			self.bitGapSendLong = 1300
			self.bitGapMax = 1500
			self.stopPulseMin = 1000
			self.stopPulseSend = 1300
			self.stopPulseMax = 1400
			self.stopGapSend = 400
			self.stepTimeout_ns = 5_000_000
			self.replyTimeout_ns = 12_000_000

class FakePulsesIn:
	def __init__(self, arr):
		self.arr = arr
		self.cursor = 0
	def __len__(self):
		return len(self.arr) - self.cursor
	def clear(self):
		pass
	def pause(self):
		pass
	def resume(self):
		pass
	def popleft(self):
		x = self.arr[self.cursor]
		self.cursor += 1
		return x

def waitPulse(pulsesIn, timeout_ns, position):
	startTime = time.monotonic_ns()
	while len(pulsesIn) == 0 and (timeout_ns is None or time.monotonic_ns() - startTime < timeout_ns):
		pass
	if len(pulsesIn) != 0:
		t = pulsesIn.popleft()
		addToLog(t)
		return t
	elif position is None:
		return None
	else:
		raise WaitEnded("%d" % position)

def receivePacketDatalink(pulsesIn, params, waitForStart_ns):
	pulsesIn.clear()
	pulsesIn.resume()
	bytes = []
	if waitForStart_ns == WAIT_REPLY:
		waitForStart_ns = params.replyTimeout_ns
	try:
		t = waitPulse(pulsesIn, waitForStart_ns, -2)
		if t < params.startPulseMin or t > params.startPulseMax:
			raise BadPacket("start pulse = %d" % t)
		t = waitPulse(pulsesIn, params.stepTimeout_ns, -1)
		if t < params.startGapMin or t > params.startGapMax:
			raise BadPacket("start gap = %d" % t)
		currentByte = 0
		bitCount = 0
		while True:
			t = waitPulse(pulsesIn, params.stepTimeout_ns, 2*bitCount+1)
			if t >= params.bitPulseMin and t <= params.bitPulseMax:
				#normal pulse
				pass
			elif t >= params.stopPulseMin and t <= params.stopPulseMax:
				#stop pulse
				break
			else:
				raise BadPacket("bit %d pulse = %d" % (bitCount, t))
			t = waitPulse(pulsesIn, params.stepTimeout_ns, 2*bitCount+2)
			if t < params.bitGapMin or t > params.bitGapMax:
				raise BadPacket("bit %d gap = %d" % (bitCount, t))
			currentByte >>= 1
			if t > params.bitGapThreshold:
				currentByte |= 0x80
			bitCount += 1
			if bitCount % 8 == 0:
				bytes.append(currentByte)
				currentByte = 0
		if bitCount % 8 != 0:
			#currentByte >>= 8 - bitCount % 8
			#bytes.append(currentByte)
			raise BadPacket("bitCount = %d" % bitCount)
	finally:
		pulsesIn.pause()
		addToLog(0xFFFF)
	return bytes

def sendPacketDatalink(sendBuffer, params, bytes):
	sendBuffer[0] = params.startPulseSend
	sendBuffer[1] = params.startGapSend
	bufCursor = 2
	for i in range(len(bytes)):
		currentByte = bytes[i]
		for j in range(8):
			sendBuffer[bufCursor] = params.bitPulseSend
			bufCursor += 1
			if currentByte & 1:
				sendBuffer[bufCursor] = params.bitGapSendLong
			else:
				sendBuffer[bufCursor] = params.bitGapSendShort
			bufCursor += 1
			currentByte >>= 1
	sendBuffer[bufCursor] = params.stopPulseSend
	sendBuffer[bufCursor + 1] = params.stopGapSend
	pulseOut.send(sendBuffer)

def printBytes(bytes):
	for b in bytes:
		print("0x%02X" % b, end=",")
	print()

def doComm(sequence, printLog):
	global logSize
	logSize = 0
	commType = sequence[0]
	goFirst = sequence[1]
	packetsToSend = sequence[2:]
	if packetsToSend == []:
		bytesInPacket = 0
	else:
		bytesInPacket = len(packetsToSend[0])
	params = Params(commType)
	if commType == TYPE_DATALINK:
		sendBuffer = array.array('H', range(bytesInPacket * 16 + 4))
		def sendPacket(packet):
			sendPacketDatalink(sendBuffer, params, packet)
		def receivePacket(w):
			return receivePacketDatalink(demodPulsesIn, params, w)
	else:
		raise ValueError("commType")
	try:
		if not goFirst:
			received = receivePacket(WAIT_FOREVER)
			printBytes(received)
		for packet in packetsToSend:
			sendPacket(packet)
			received = receivePacket(WAIT_REPLY)
			printBytes(received)
	except BadPacket as e:
		print(repr(e))
	except WaitEnded as e:
		print(repr(e))
	if printLog:
		for i in range(logSize):
			print(logBuffer[i], end=",")
		print(".") 
	if goFirst:
		time.sleep(5)
	else:
		time.sleep(0.25)

datalinkListen = [TYPE_DATALINK, False, []]
datalinkGive10Pt1st = [TYPE_DATALINK, True, [0x13,0x01,0x00,0x00,0x10,0xB1,0x00,0xD5], [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86]]
datalinkTakePt1st = [TYPE_DATALINK, True, [0x13,0x01,0x10,0x00,0x00,0xB1,0x00,0xD5], [0x13,0x01,0x10,0x00,0x00,0xB1,0xB1,0x86]]
datalinkGive10Pt2nd = [TYPE_DATALINK, False, [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86], [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86]]
datalinkTakePt2nd = [TYPE_DATALINK, False, [0x13,0x01,0x10,0x00,0x10,0xB1,0xB1,0x96], [0x13,0x01,0x10,0x00,0x10,0xB1,0xB1,0x96]]
datalinkBattle1st_1 = [TYPE_DATALINK, True, [0x11,0x01,0x30,0x16,0x24,0x01,0x01,0x08,0x00,0xB1,0x00,0x38]]
datalinkBattle2nd_1 = [TYPE_DATALINK, False, [0x11,0x01,0x30,0x16,0x24,0x01,0x00,0x08,0x01,0xB1,0xB1,0xE9]]
datalinkBattle1st_2 = [TYPE_DATALINK, True, [0x11,0x01,0x30,0x16,0x24,0x00,0x00,0x08,0x00,0xB1,0x00,0x36], [0x11,0x01,0x30,0x16,0x24,0x00,0x00,0x08,0x00,0xB1,0xB1,0xE7]]

runs = 1
while(True):
	print("begin", runs)
	runs += 1
	doComm(datalinkGive10Pt1st, True)
