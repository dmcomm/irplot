#This file is part of the DMComm project by BladeSabre. License: MIT.

#Some iC, Data Link and Fusion Loader interaction.
#Tested with CircuitPython 20210703-cece649 on Pi Pico.

import array
import board
import time
import digitalio
import pulseio
import pwmio
import rp2pio
import adafruit_pioasm

TYPE_DATALINK = 0
TYPE_FUSION = 1
TYPE_IC = 2
TYPE_XROS = 3
TYPE_XROSLINK = 4

WAIT_FOREVER = None
WAIT_REPLY = -1

pinProbeOut = board.GP0
pinProbeIn = board.GP1
pinIRLED = board.GP16
pinDemodIn = board.GP17
pinRawIn = board.GP14
pinXrosIn = board.GP12
pinProngDrive = board.GP19  #GP19 for high, GP20 for low (implied)
pinProngWeakPull = board.GP21
pinProngIn = board.GP26  #ADC0
pinsExtraPower = [board.GP13, board.GP18]

extraPowerOut = []
for pin in pinsExtraPower:
	io = digitalio.DigitalInOut(pin)
	io.direction = digitalio.Direction.OUTPUT
	io.value = True
	extraPowerOut.append(io)

#probeOut = digitalio.DigitalInOut(pinProbeOut)
#probeOut.direction = digitalio.Direction.OUTPUT

iC_TX_ASM = """
.program ictx
	pull
	mov osr ~ osr
	set pins 1
	set pins 0 [8]
""" + ("""
	out pins 1
	set pins 0 [8]
""" * 8) + """
	nop [12]
"""
iC_TX_PIO = adafruit_pioasm.assemble(iC_TX_ASM)

#guessing wildly about the bit mapping:
xros_TX_ASM = """
.program xrostx
	pull
	set pins 1 [1]
""" + ("""
	out pins 1
	set pins 1 [1]
""" * 8) + """
	nop [5]
	set pins 0
"""
xros_TX_PIO = adafruit_pioasm.assemble(xros_TX_ASM)

xros_RX_ASM = """
.program xrosrx
	wait 0 pin 0
loop:
	in pins 1
	jmp loop
"""
xros_RX_PIO = adafruit_pioasm.assemble(xros_RX_ASM)

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
		elif commType == TYPE_IC:
			self.replyTimeout_ms = 100
			self.packetLengthTimeout_ms = 30
			self.pulseMax = 25
			self.tickLength = 100
			self.tickMargin = 30
		elif commType == TYPE_XROSLINK:
			self.replyTimeout_ms = 100
			self.packetLengthTimeout_ms = 15
			self.pulseMax = 80
			self.tickLength = 400
			self.tickMargin = 100
		elif commType == TYPE_XROS:
			self.replyTimeout_ms = 30

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

def waitForStart(pulsesIn, params, wait_ms):
	if wait_ms == WAIT_REPLY:
		wait_ms = params.replyTimeout_ms
	if wait_ms == WAIT_FOREVER:
		while len(pulsesIn) == 0:
			pass
	else:
		wait_ns = wait_ms * 1_000_000
		timeStart = time.monotonic_ns()
		while len(pulsesIn) == 0 and time.monotonic_ns() - timeStart < wait_ns:
			pass
	if len(pulsesIn) == 0:
		pulsesIn.pause()
		raise WaitEnded("nothing received")

def receivePacketXros(pioIn, params, wait_ms):
	numWords = 4
	pioIn.restart()
	pioIn.clear_rxfifo()
	if wait_ms == WAIT_REPLY:
		wait_ms = params.replyTimeout_ms
	if wait_ms == WAIT_FOREVER:
		while pioIn.in_waiting < numWords:
			pass
	else:
		wait_ns = wait_ms * 1_000_000
		timeStart = time.monotonic_ns()
		while pioIn.in_waiting < numWords and time.monotonic_ns() - timeStart < wait_ns:
			pass
	if pioIn.in_waiting < numWords:
		raise WaitEnded("nothing received")
	samples = array.array("L", [0] * numWords)
	pioIn.readinto(samples)
	for s in samples:
		logBuffer.appendNoError(s & 0xFFFF)
		logBuffer.appendNoError(s >> 16)
		print(bin(s))
	logBuffer.appendNoError(0)

def receiveDurs(pulseIn, params, waitForStart_ms):
	pulseIn.clear()
	pulseIn.resume()
	receivedBytes.clear()
	waitForStart(pulseIn, params, waitForStart_ms)
	time.sleep(params.packetLengthTimeout_ms / 1000)
	while len(pulseIn) != 0:
		popPulse(pulseIn, "n/a")
	logBuffer.appendNoError(0xFFFF)

def receivePacket_iC(pulsesIn, params, waitForStart_ms):
	pulsesIn.clear()
	pulsesIn.resume()
	receivedBytes.clear()
	waitForStart(pulsesIn, params, waitForStart_ms)
	#TODO: store time?
	time.sleep(params.packetLengthTimeout_ms / 1000)
	pulsesIn.pause()
	currentByte = 0
	pulseCount = 0
	ticksIntoByte = 0
	ended = False
	while not ended:
		pulseCount += 1
		if len(pulsesIn) == 0:
			raise BadPacket("ended with gap")
		tPulse = pulsesIn.popleft()
		logBuffer.appendNoError(tPulse)
		if tPulse > params.pulseMax:
			raise BadPacket("pulse %d = %d" % (pulseCount, tPulse))
		if len(pulsesIn) != 0:
			tGap = pulsesIn.popleft()
		else:
			tGap = 0xFFFF
			ended = True
		logBuffer.appendNoError(tGap)
		dur = tPulse + tGap
		ticks = round(dur / params.tickLength)
		durRounded = ticks * params.tickLength
		offRounded = abs(dur - durRounded)
		if ticksIntoByte + ticks >= 9:
			#finish byte
			for i in range(8 - ticksIntoByte):
				currentByte >>= 1
				currentByte |= 0x80
			receivedBytes.append(currentByte)
			currentByte = 0
			ticksIntoByte = 0
		elif offRounded > params.tickMargin:
			raise BadPacket("pulse+gap %d = %d" % (pulseCount, dur))
		else:
			for i in range(ticks - 1):
				currentByte >>= 1
				currentByte |= 0x80
			currentByte >>= 1
			ticksIntoByte += ticks

def receivePacketModulated(pulsesIn, params, waitForStart_ms):
	pulsesIn.clear()
	pulsesIn.resume()
	receivedBytes.clear()
	packetLengthTimeout_ns = params.packetLengthTimeout_ms * 1_000_000
	packetContinueTimeout_ns = params.packetContinueTimeout_ms * 1_000_000
	#wait for first pulse:
	waitForStart(pulsesIn, params, waitForStart_ms)
	#wait until the pulses stop or it takes too long:
	numPulsesPrev = 1
	timeStart = time.monotonic_ns()
	timePrevPulse = timeStart
	while True:
		numPulses = len(pulsesIn)
		timeCurrent = time.monotonic_ns()
		if numPulses != numPulsesPrev:
			numPulsesPrev = numPulses
			timePrevPulse = timeCurrent
		if timeCurrent - timePrevPulse > packetContinueTimeout_ns:
			pulsesIn.pause()
			break
		if timeCurrent - timeStart > packetLengthTimeout_ns:
			pulsesIn.pause()
			raise BadPacket("too long")
	#process the packet:
	#TODO: store timeStart-pulsesIn[0]?
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

def sendPacketModulated(pulseOut, params, bytesToSend):
	pulseOutLength = len(bytesToSend) * 16 + 4
	arrayToSend = array.array("H")
	for i in range(pulseOutLength):
		arrayToSend.append(0)
		#This function would be simpler if we append as we go along,
		#but still hoping for a fix that allows reuse of the array.
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
	pwmOut = None
	pulseOut = None
	pulseIn = None
	pioOut = None
	pioIn = None
	if commType == TYPE_DATALINK or commType == TYPE_FUSION:
		pwmOut = pwmio.PWMOut(pinIRLED, frequency=38000, duty_cycle=2**15)
		pulseOut = pulseio.PulseOut(pwmOut)
		pulseIn = pulseio.PulseIn(pinDemodIn, maxlen=300, idle_state=True)
		pulseIn.pause()
		if not goFirst:
			pulseOut.send(array.array('H', [100, 100])) #workaround for bug
		def sendPacket(packet):
			sendPacketModulated(pulseOut, params, packet)
		def receivePacket(w):
			receivePacketModulated(pulseIn, params, w)
	elif commType == TYPE_IC:
		pulseIn = pulseio.PulseIn(pinRawIn, maxlen=300, idle_state=True)
		pulseIn.pause()
		pioOut = rp2pio.StateMachine(
			iC_TX_PIO,
			frequency=100000,
			first_out_pin=pinIRLED,
			first_set_pin=pinIRLED,
		)
		def sendPacket(packet):
			pioOut.write(bytes(packet))
		def receivePacket(w):
			receivePacket_iC(pulseIn, params, w)
	elif commType == TYPE_XROSLINK:
		pulseIn = pulseio.PulseIn(pinXrosIn, maxlen=300, idle_state=True)
		pulseIn.pause()
		pioOut = rp2pio.StateMachine(
			iC_TX_PIO,
			frequency=25000,
			first_out_pin=pinIRLED,
			first_set_pin=pinIRLED,
		)
		def sendPacket(packet):
			pioOut.write(bytes(packet))
		def receivePacket(w):
			receivePacket_iC(pulseIn, params, w)
	elif commType == TYPE_XROS:
		pioIn = rp2pio.StateMachine(
			xros_RX_PIO,
			frequency=1000000,
			first_in_pin=pinXrosIn,
			auto_push=True,
			in_shift_right=False,
		)
		pioOut = rp2pio.StateMachine(
			xros_TX_PIO,
			frequency=175000,
			first_out_pin=pinIRLED,
			first_set_pin=pinIRLED,
		)
		def sendPacket(packet):
			pioOut.write(bytes(packet))
		def receivePacket(w):
			receivePacketXros(pioIn, params, w)
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
	finally:
		if pulseOut is not None:
			pulseOut.deinit()
		if pwmOut is not None:
			pwmOut.deinit()
		if pulseIn is not None:
			pulseIn.deinit()
		if pioOut is not None:
			pioOut.deinit()
		if pioIn is not None:
			pioIn.deinit()
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
fusionBattle2nd = [TYPE_FUSION, False, [0x0B,0x88,0xA0,0x80,0x80,0x00,0x00,0x00,0x40,0x40,0xC0,0x00,0x00,0x00,0x00,0x00,0xF7],
	[0x0B,0x90,0xE0,0x80,0x00,0x00,0x00,0x00,0x87], [0x0B,0x20,0x50,0x7B]] #Agumon/Agumon/Agunimon
fusionBattle1stA = [TYPE_FUSION, True, [0x0B,0x88,0x20,0x80,0x80,0x00,0x00,0x00,0x40,0x40,0xC0,0x00,0x00,0x00,0x00,0x00,0x77],
	[0x0B,0x90,0x60,0x80,0x00,0x00,0x00,0x00,0x07], [0x0B,0x20,0xF0,0xC7]] #Agumon/Agumon/Agunimon, computer wins
fusionBattle1stB = [TYPE_FUSION, True, [0x0B,0x88,0x20,0x80,0x80,0x00,0x00,0x00,0x40,0x40,0xC0,0x00,0x00,0x00,0x00,0x00,0x77],
	[0x0B,0x90,0x60,0x00,0x00,0x00,0x00,0x00,0xFB], [0x0B,0x20,0xF0,0xC7]] #Agumon/Agumon/Agunimon, computer loses
fusionBattle1stC = [TYPE_FUSION, True, [0x0B,0x88,0x20,0x80,0x80,0x00,0x00,0x00,0x40,0x40,0x20,0x00,0x00,0x00,0x00,0x00,0xF7],
	[0x0B,0x90,0x60,0x00,0x00,0x00,0x00,0x00,0xFB], [0x0B,0x20,0xF0,0xC7]] #Agumon/Agumon/Airdramon, computer loses
fusionBattle1stD = [TYPE_FUSION, True, [0x0B,0x88,0x20,0x80,0x80,0x00,0x00,0x00,0xF0,0x8C,0x51,0x00,0x00,0x00,0x00,0x00,0x8D],
[0x0B,0x90,0x60,0x00,0x00,0x00,0x00,0x00,0xFB], [0x0B,0x20,0xF0,0xC7]] #Ballistamon/Dorulumon/Starmons (nothing interesting), computer loses

icListen = [TYPE_IC, False]
icTest = [TYPE_IC, True, [0x00,0xFF,0x01,0x80]]
icGaoChu3 = [TYPE_IC, True,
	[0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFF,0x13,0x70,0x70,0x67,0x7D,0xE0,0xE5,0x97,0xC1],
	[0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFF,0x13,0x70,0x70,0x57,0x42,0x5D,0x86,0xC1],
	[0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFF,0x13,0x70,0x70,0x97,0x01,0x68,0x3C,0xC1],
	[0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFF,0x13,0x70,0x70,0x07,0x00,0xBC,0x34,0xC1],
	[0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFF,0x13,0x70,0x70,0xC7,0x81,0x97,0x6B,0xC1]]

xroslinkListen = [TYPE_XROSLINK, False]
xroslink1 = [TYPE_XROSLINK, True, [0x05], [0x02,0x1B,0xC0]] #but after that it doesn't reply
	#(tried increasing gap between bytes to match, which breaks on iC, but no difference here so let's not do that)
xroslink2 = [TYPE_XROSLINK, False, [0x06]]

xrosListen = [TYPE_XROS, False]
xrosTrade1 = [TYPE_XROS, True, [0x05]]
xrosTrade2 = [TYPE_XROS, False, [0x06]]

runs = 1
while(True):
	print("begin", runs)
	runs += 1
	doComm(xrosTrade2, True)
