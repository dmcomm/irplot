#This file is part of the DMComm project by BladeSabre. License: MIT.

#Some Data Link and Fusion Loader interaction.
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

demodPulsesIn = pulseio.PulseIn(board.GP9, maxlen=300, idle_state=True)
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

class Buffer:
	def __init__(self, length, typecode, filler=0):
		self.array = array.array(typecode)
		self.length = length
		self.cursor = 0
		for i in range(length):
			self.array.append(filler)
	def __len__(self):
		return self.cursor
	def __getitem__(self, i):
		if i < 0 or i >= self.cursor:
			raise IndexError("index out of range")
		return self.array[i]
	def __setitem__(self, i, x):
		if i < 0 or i >= self.cursor:
			raise IndexError("index out of range")
		self.array[i] = x
	def appendNoError(self, x):
		if self.cursor == self.length:
			return False
		self.array[self.cursor] = x
		self.cursor += 1
		return True
	def append(self, x):
		if not self.appendNoError(x):
			raise IndexError("full")
	def clear(self):
		self.cursor = 0

logBuffer = Buffer(2000, "L")
receivedBytes = Buffer(30, "B")

arraysToSend = {}
for numBytes in [4, 5, 8, 12, 17]:
	theLength = numBytes * 16 + 4
	arraysToSend[theLength] = array.array('H', range(theLength))

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
			self.replyTimeout_ms = 40
			self.packetLengthTimeout_ms = 300
			self.packetContinueTimeout_ms = 10
		elif commType == TYPE_FUSION:
			self.startPulseMin = 5000
			self.startPulseSend = 5880
			self.startPulseMax = 7000
			self.startGapMin = 3000
			self.startGapSend = 3872
			self.startGapMax = 4000
			self.bitPulseMin = 250
			self.bitPulseSend = 480
			self.bitPulseMax = 600
			self.bitGapMin = 200
			self.bitGapSendShort = 480
			self.bitGapThreshold = 650
			self.bitGapSendLong = 1450
			self.bitGapMax = 1600
			self.stopPulseMin = 700
			self.stopPulseSend = 950
			self.stopPulseMax = 1100
			self.stopGapSend = 1500
			self.replyTimeout_ms = 100
			self.packetLengthTimeout_ms = 300
			self.packetContinueTimeout_ms = 10

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

def popPulse(pulsesIn, emptyErrorCode):
	if len(pulsesIn) == 0:
		raise WaitEnded(str(emptyErrorCode))
	t = pulsesIn.popleft()
	logBuffer.appendNoError(t)
	return t

def receivePacketModulated(pulsesIn, params, waitForStart_ms):
	pulsesIn.clear()
	pulsesIn.resume()
	receivedBytes.clear()
	packetLengthTimeout_10ms = (params.packetLengthTimeout_ms + 9) // 10
	packetContinueTimeout_10ms = (params.packetContinueTimeout_ms + 9) // 10
	#wait for first pulse:
	if waitForStart_ms == WAIT_REPLY:
		waitForStart_ms = params.replyTimeout_ms
	if waitForStart_ms is None:
		while len(pulsesIn) == 0:
			time.sleep(0.01)
	else:
		waitForStart_10ms = (waitForStart_ms + 9) // 10
		while len(pulsesIn) == 0 and waitForStart_10ms > 0:
			time.sleep(0.01)
			waitForStart_10ms -= 1
	if len(pulsesIn) == 0:
		raise WaitEnded("nothing received")
	#wait until the pulses stop or it takes too long:
	sleepsSinceStart = 0
	sleepsSincePrevPulse = 0
	numPulsesPrev = 1
	while True:
		numPulses = len(pulsesIn)
		if numPulses != numPulsesPrev:
			numPulsesPrev = numPulses
			sleepsSincePrevPulse = 0
		if sleepsSincePrevPulse > packetContinueTimeout_10ms:
			break
		if sleepsSinceStart > packetLengthTimeout_10ms:
			raise BadPacket("too long")
		sleepsSinceStart += 1
		sleepsSincePrevPulse += 1
		time.sleep(0.01)
	pulsesIn.pause()
	#process the packet:
	try:
		t = popPulse(pulsesIn, -2)
		if t < params.startPulseMin or t > params.startPulseMax:
			raise BadPacket("start pulse = %d" % t)
		t = popPulse(pulsesIn, -1)
		if t < params.startGapMin or t > params.startGapMax:
			raise BadPacket("start gap = %d" % t)
		currentByte = 0
		bitCount = 0
		while True:
			t = popPulse(pulsesIn, 2*bitCount+1)
			if t >= params.bitPulseMin and t <= params.bitPulseMax:
				#normal pulse
				pass
			elif t >= params.stopPulseMin and t <= params.stopPulseMax:
				#stop pulse
				break
			else:
				raise BadPacket("bit %d pulse = %d" % (bitCount, t))
			t = popPulse(pulsesIn, 2*bitCount+2)
			if t < params.bitGapMin or t > params.bitGapMax:
				raise BadPacket("bit %d gap = %d" % (bitCount, t))
			currentByte >>= 1
			if t > params.bitGapThreshold:
				currentByte |= 0x80
			bitCount += 1
			if bitCount % 8 == 0:
				receivedBytes.appendNoError(currentByte)
				currentByte = 0
		if bitCount % 8 != 0:
			#currentByte >>= 8 - bitCount % 8
			#receivedBytes.appendNoError(currentByte)
			raise BadPacket("bitCount = %d" % bitCount)
	finally:
		logBuffer.appendNoError(0xFFFF)

def sendPacketModulated(params, bytesToSend):
	pulseOutLength = len(bytesToSend) * 16 + 4
	arrayToSend = arraysToSend[pulseOutLength]
	arrayToSend[0] = params.startPulseSend
	arrayToSend[1] = params.startGapSend
	bufCursor = 2
	for currentByte in bytesToSend:
		for j in range(8):
			arrayToSend[bufCursor] = params.bitPulseSend
			bufCursor += 1
			if currentByte & 1:
				arrayToSend[bufCursor] = params.bitGapSendLong
			else:
				arrayToSend[bufCursor] = params.bitGapSendShort
			bufCursor += 1
			currentByte >>= 1
	arrayToSend[bufCursor] = params.stopPulseSend
	arrayToSend[bufCursor + 1] = params.stopGapSend
	pulseOut.send(arrayToSend)
	return arrayToSend

def printBytes(bytesToPrint):
	for b in bytesToPrint:
		print("0x%02X" % b, end=",")
	print()

def doComm(sequence, printLog):
	logBuffer.clear()
	commType = sequence[0]
	goFirst = sequence[1]
	packetsToSend = sequence[2:]
	params = Params(commType)
	if commType == TYPE_DATALINK or commType == TYPE_FUSION:
		def sendPacket(packet):
			sendPacketModulated(params, packet)
		def receivePacket(w):
			receivePacketModulated(demodPulsesIn, params, w)
	else:
		raise ValueError("commType")
	try:
		if not goFirst:
			receivePacket(WAIT_FOREVER)
			printBytes(receivedBytes)
		for packet in packetsToSend:
			sendPacket(packet)
			receivePacket(WAIT_REPLY)
			printBytes(receivedBytes)
	except BadPacket as e:
		print(repr(e))
	except WaitEnded as e:
		print(repr(e))
	if printLog:
		for i in range(len(logBuffer)):
			print(logBuffer[i], end=",")
		print(".") 
	if goFirst:
		time.sleep(5)
	else:
		time.sleep(0.25)

datalinkListen = [TYPE_DATALINK, False]
datalinkGive10Pt1st = [TYPE_DATALINK, True, [0x13,0x01,0x00,0x00,0x10,0xB1,0x00,0xD5], [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86]]
datalinkTakePt1st = [TYPE_DATALINK, True, [0x13,0x01,0x10,0x00,0x00,0xB1,0x00,0xD5], [0x13,0x01,0x10,0x00,0x00,0xB1,0xB1,0x86]]
datalinkGive10Pt2nd = [TYPE_DATALINK, False, [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86], [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86]]
datalinkTakePt2nd = [TYPE_DATALINK, False, [0x13,0x01,0x10,0x00,0x10,0xB1,0xB1,0x96], [0x13,0x01,0x10,0x00,0x10,0xB1,0xB1,0x96]]
datalinkBattle1st_1 = [TYPE_DATALINK, True, [0x11,0x01,0x30,0x16,0x24,0x01,0x01,0x08,0x00,0xB1,0x00,0x38]]
datalinkBattle2nd_1 = [TYPE_DATALINK, False, [0x11,0x01,0x30,0x16,0x24,0x01,0x00,0x08,0x01,0xB1,0xB1,0xE9]]
datalinkBattle1st_2 = [TYPE_DATALINK, True, [0x11,0x01,0x30,0x16,0x24,0x00,0x00,0x08,0x00,0xB1,0x00,0x36], [0x11,0x01,0x30,0x16,0x24,0x00,0x00,0x08,0x00,0xB1,0xB1,0xE7]]

#Fusion can't initiate when receiving Digimon.
#Doesn't seem to matter which "take" code we use.
#Seems to retry individual packets. Need to investigate this.
fusionListen = [TYPE_FUSION, False]
fusionGiveAgumon = [TYPE_FUSION, True, [0x0B,0x20,0x00,0x2B], [0x0B,0xA0,0x40,0x40,0x9B], [0x0B,0x20,0xF0,0xC7]]
fusionGiveAquilamon = [TYPE_FUSION, True, [0x0B,0x20,0x00,0x2B], [0x0B,0xA0,0x40,0x30,0xC7], [0x0B,0x20,0xF0,0xC7]]
fusionGiveBallistamon = [TYPE_FUSION, True, [0x0B,0x20,0x00,0x2B], [0x0B,0xA0,0x40,0xF0,0x67], [0x0B,0x20,0xF0,0xC7]]
fusionGiveDevimon = [TYPE_FUSION, True, [0x0B,0x20,0x00,0x2B], [0x0B,0xA0,0x40,0xB4,0x20], [0x0B,0x20,0xF0,0xC7]]
fusionGiveGuardromon = [TYPE_FUSION, True, [0x0B,0x20,0x00,0x2B], [0x0B,0xA0,0x40,0x92,0x04], [0x0B,0x20,0xF0,0xC7]]
fusionTakeAgumon = [TYPE_FUSION, False, [0x0B,0x20,0x80,0xAB], [0x0B,0xA0,0xC0,0x40,0x5B], [0x0B,0x20,0x50,0x7B]]
fusionTakeAquilamon = [TYPE_FUSION, False, [0x0B,0x20,0x80,0xAB], [0x0B,0xA0,0xC0,0x30,0x27], [0x0B,0x20,0x50,0x7B]]
fusionTakeBallistamon = [TYPE_FUSION, False, [0x0B,0x20,0x80,0xAB], [0x0B,0xA0,0xC0,0xF0,0xE7], [0x0B,0x20,0x50,0x7B]]
fusionTakeDevimon = [TYPE_FUSION, False, [0x0B,0x20,0x80,0xAB], [0x0B,0xA0,0xC0,0xB4,0xA0], [0x0B,0x20,0x50,0x7B]]
fusionTakeGuardromon = [TYPE_FUSION, False, [0x0B,0x20,0x80,0xAB], [0x0B,0xA0,0xC0,0x92,0x84], [0x0B,0x20,0x50,0x7B]]
fusionTakeDigimonScan = fusionTakeAgumon[:4]
fusionBattle1 = [TYPE_FUSION, True, [0x0B,0x88,0x20,0x80,0x80,0x00,0x00,0x00,0x40,0x40,0xC0,0x00,0x00,0x00,0x00,0x00,0x77]]
fusionBattle2 = [TYPE_FUSION, False, [0x0B,0x88,0xA0,0x80,0x80,0x00,0x00,0x00,0x40,0x40,0xC0,0x00,0x00,0x00,0x00,0x00,0xF7]]

runs = 1
while(True):
	print("begin", runs)
	runs += 1
	doComm(fusionTakeDigimonScan, False)
