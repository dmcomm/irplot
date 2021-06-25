#This file is part of the DMComm project by BladeSabre. License: MIT.

#Some Data Link interaction.
#Tested with CircuitPython 20210622-47a6b13 on Pi Pico.

import array
import board
import time
import digitalio
import pulseio
import pwmio

TYPE_DATALINK_TRADE = 0
TYPE_DATALINK_BATTLE = 1
TYPE_FUSION_TRADE = 2
TYPE_FUSION_BATTLE = 3

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

def receivePacketDatalink(pulsesIn, bitsWanted, waitForStart_ns):
	if bitsWanted % 8 != 0:
		raise NotImplementedError("bitsWanted not divisible by 8")
	pulsesIn.clear()
	pulsesIn.resume()
	bytes = []
	if waitForStart_ns == WAIT_REPLY:
		waitForStart_ns = 12000000
	try:
		t = waitPulse(pulsesIn, waitForStart_ns, -2)
		if t < 9000 or t > 11000:
			raise BadPacket("start pulse = %d" % t)
		t = waitPulse(pulsesIn, 5000000, -1)
		if t < 2000 or t > 3000:
			raise BadPacket("start gap = %d" % t)
		currentByte = 0
		for i in range(1, bitsWanted + 1):
			t = waitPulse(pulsesIn, 3000000, 2*i)
			if t < 300 or t > 650:
				raise BadPacket("bit %d pulse = %d" % (i, t))
			t = waitPulse(pulsesIn, 3000000, 2*i+1)
			if t < 400 or t > 1500:
				raise BadPacket("bit %d gap = %d" % (i, t))
			currentByte >>= 1
			if t > 800:
				currentByte |= 0x80
			if i % 8 == 0:
				bytes.append(currentByte)
				currentByte = 0
		t = waitPulse(pulsesIn, 3000000, bitsWanted+1)
		if t < 1000 or t > 1400:
			raise BadPacket("stop pulse = %d" % t)
	finally:
		pulsesIn.pause()
		addToLog(0xFFFF)
	return bytes

def sendPacketDatalink(sendBuffer, bytes):
	sendBuffer[0] = 9800
	sendBuffer[1] = 2450
	bufCursor = 2
	for i in range(len(bytes)):
		currentByte = bytes[i]
		for j in range(8):
			sendBuffer[bufCursor] = 500
			bufCursor += 1
			if currentByte & 1:
				sendBuffer[bufCursor] = 1300
			else:
				sendBuffer[bufCursor] = 700
			bufCursor += 1
			currentByte >>= 1
	sendBuffer[bufCursor] = 1300
	sendBuffer[bufCursor + 1] = 400
	pulseOut.send(sendBuffer)

def printBytes(bytes):
	for b in bytes:
		print("0x%02X" % b, end=",")
	print()

def doComm(sequence, printLog):
	logSize = 0
	commType = sequence[0]
	goFirst = sequence[1]

	if commType == TYPE_DATALINK_TRADE:
		sendBuffer = array.array('H', range(132))
		def sendPacket(packet):
			sendPacketDatalink(sendBuffer, packet)
		def receivePacket(w):
			return receivePacketDatalink(demodPulsesIn, 64, w)
	else:
		raise ValueError("commType")
	try:
		if not goFirst:
			received = receivePacket(WAIT_FOREVER)
			printBytes(received)
		for packet in sequence[2:]:
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

datalinkGive10Pt1st = [TYPE_DATALINK_TRADE, True, [0x13,0x01,0x00,0x00,0x10,0xB1,0x00,0xD5], [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86]]
datalinkTakePt1st = [TYPE_DATALINK_TRADE, True, [0x13,0x01,0x10,0x00,0x00,0xB1,0x00,0xD5], [0x13,0x01,0x10,0x00,0x00,0xB1,0xB1,0x86]]
datalinkGive10Pt2nd = [TYPE_DATALINK_TRADE, False, [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86], [0x13,0x01,0x00,0x00,0x10,0xB1,0xB1,0x86]]
datalinkTakePt2nd = [TYPE_DATALINK_TRADE, False, [0x13,0x01,0x10,0x00,0x10,0xB1,0xB1,0x96], [0x13,0x01,0x10,0x00,0x10,0xB1,0xB1,0x96]]

runs = 1
while(True):
	print("begin", runs)
	runs += 1
	doComm(datalinkGive10Pt2nd, True)
