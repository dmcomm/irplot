#This file is part of the DMComm project by BladeSabre. License: MIT.

#Some interaction with pronged devices, iC, Data Link and Fusion Loader.
#New PulseOut API was added to CircuitPython on 2021-07-28.

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
TYPE_2PRONG = 5
TYPE_3PRONG = 6
TYPE_XROSMINI = 7

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
pinsExtraPower = [board.GP11, board.GP13, board.GP18]

prongWeakPullOut = digitalio.DigitalInOut(pinProngWeakPull)
prongWeakPullOut.direction = digitalio.Direction.OUTPUT

extraPowerOut = []
for pin in pinsExtraPower:
	io = digitalio.DigitalInOut(pin)
	io.direction = digitalio.Direction.OUTPUT
	io.value = True
	extraPowerOut.append(io)

xrosInSize = 12
xrosInBuffers = [array.array("L", [0] * 8) for i in range(xrosInSize)]

probeOut = digitalio.DigitalInOut(pinProbeOut)
probeOut.direction = digitalio.Direction.OUTPUT

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

#Run at 1MHz, OUT and SET pins the same, in_shift_right=False. High 24 bits of data should be 1.
#(This is not really how it works and will need redone.)
xros_TX_ASM = """
.program xrostx
	pull
	set pins 1 [2]
loop:
	set pins 1 [10]
	out pins 1
	mov isr ~ osr
	in null 24
	mov x isr
	; push ; testing
	set pins 1
	jmp x-- loop ; loop if there are any 0s left in low 8 bits osr
	nop [24]
	nop [24]
	set pins 0

	mov osr ~ null
	out null 21
	mov x osr ; x = 4095 (above=20), 2047 (above=21)
delay:
	jmp x-- delay
"""
xros_TX_PIO = adafruit_pioasm.assemble(xros_TX_ASM)

#Outputs pulses to the SET pin, high first, with the specified durations +4 at clock speed.
durs_TX_ASM = """
	pull
	set pins 1
	mov x osr
loophigh:
	jmp x-- loophigh
	pull
	set pins 0
	mov x osr
looplow:
	jmp x-- looplow
"""
durs_TX_PIO = adafruit_pioasm.assemble(durs_TX_ASM)

#take 240 samples after pin low, 30 per word, at half of clock speed
#use in_shift_right=False, out_shift_right=True, auto_push=True, push_threshold=30
scope240_ASM = """
	mov osr ~ null
	out null 24
	mov x osr ; x = 255
	set y 15
subtract:
	jmp x-- next
next:
	jmp y-- subtract
	; x = 239
	wait 0 pin 0
sampling:
	in pins 1
	jmp x-- sampling
"""
scope240_PIO = adafruit_pioasm.assemble(scope240_ASM)

prong_TX_ASM = """
start:
	pull
	mov x osr
	jmp x-- notdrivelow
	jmp drivelow  ; if osr==0
notdrivelow:
	jmp x-- notdrivehigh
	jmp drivehigh ; if osr==1
notdrivehigh:
	jmp x-- delay
	jmp release   ; if osr==2
	; else:
delay:
	jmp x-- delay
	jmp start
drivelow:
	set pins 0
	set pindirs 3
	jmp start
drivehigh:
	set pins 1
	set pindirs 3
	jmp start
release:
	set pindirs 0
"""
prong_TX_PIO = adafruit_pioasm.assemble(prong_TX_ASM)

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
			self.nextByteTimeout_ms = 5
			self.gapMax = 6
			self.tickLength = 17
			self.tickMargin = 6
		elif commType == TYPE_2PRONG:
			self.idleLevel = True
			self.invertBitRead = False
			self.preHighSend = 3000
			self.preLowMin = 40000
			self.preLowSend = 59000
			#self.preLowMax? PulseIn only goes up to 65535
			self.startHighMin = 1500
			self.startHighSend = 2083
			self.startHighMax = 2500
			self.startLowMin = 600
			self.startLowSend = 917
			self.startLowMax = 1200
			self.bitHighMin = 800
			self.bit0HighSend = 1000
			self.bitHighThreshold = 1800
			self.bit1HighSend = 2667
			self.bitHighMax = 3400
			self.bitLowMin = 1000
			self.bit1LowSend = 1667
			self.bit0LowSend = 3167
			self.bitLowMax = 3500
			self.cooldownSend = 400
			self.replyTimeout_ms = 100
			self.packetLengthTimeout_ms = 300
		elif commType == TYPE_3PRONG:
			self.idleLevel = True
			self.invertBitRead = False
			self.preHighSend = 3000
			self.preLowMin = 40000
			self.preLowSend = 60000
			#self.preLowMax? PulseIn only goes up to 65535
			self.startHighMin = 1500
			self.startHighSend = 2200
			self.startHighMax = 2500
			self.startLowMin = 1000
			self.startLowSend = 1600
			self.startLowMax = 2000
			self.bitHighMin = 800
			self.bit0HighSend = 1600
			self.bitHighThreshold = 2600
			self.bit1HighSend = 4000
			self.bitHighMax = 4500
			self.bitLowMin = 1200
			self.bit1LowSend = 1600
			self.bit0LowSend = 4000
			self.bitLowMax = 4500
			self.cooldownSend = 400
			self.replyTimeout_ms = 100
			self.packetLengthTimeout_ms = 300
		elif commType == TYPE_XROSMINI:
			self.idleLevel = False
			self.invertBitRead = True
			self.preHighSend = 5000
			self.preLowMin = 30000
			self.preLowSend = 40000
			#self.preLowMax? PulseIn only goes up to 65535
			self.startHighMin = 9000
			self.startHighSend = 11000
			self.startHighMax = 13000
			self.startLowMin = 4000
			self.startLowSend = 6000
			self.startLowMax = 8000
			self.bitHighMin = 1000
			self.bit0HighSend = 4000
			self.bitHighThreshold = 3000
			self.bit1HighSend = 1400
			self.bitHighMax = 4500
			self.bitLowMin = 1200
			self.bit1LowSend = 4400
			self.bit0LowSend = 1600
			self.bitLowMax = 5000
			self.cooldownSend = 200
			self.replyTimeout_ms = 100
			self.packetLengthTimeout_ms = 300

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

def receiveByteXros(pioIn, params, wait_ms, destBuffer):
	if wait_ms == WAIT_REPLY:
		wait_ms = params.replyTimeout_ms
	if wait_ms == WAIT_FOREVER:
		while pioIn.in_waiting < 8:
			pass
	else:
		wait_ns = wait_ms * 1_000_000
		timeStart = time.monotonic_ns()
		while pioIn.in_waiting < 8 and time.monotonic_ns() - timeStart < wait_ns:
			pass
	if pioIn.in_waiting == 0:
		return True
	if pioIn.in_waiting < 8:
		raise BadPacket("PIO in waiting = %d" % pioIn.in_waiting)
	pioIn.readinto(destBuffer)
	return False

def decodeScopeBits(buffer):
	prevLevel = False
	samplesSame = 0
	for item in buffer:
		#b = bin(item)
		#print("0" * (34 - len(b)) + b[2:])
		for i in range(29, -1, -1):
			level = item & (1 << i) != 0
			if level == prevLevel:
				samplesSame += 1
			else:
				logBuffer.appendNoError(samplesSame)
				samplesSame = 1
				prevLevel = level
	logBuffer.appendNoError(0)

#this is not really how it works and will need redone
def decodeByteXros(params, startIndex):
	currentByte = 0
	ticksIntoByte = 0
	i = startIndex
	while True:
		if i >= len(logBuffer):
			raise BadPacket("no room")
		tPulse = logBuffer[i]
		if tPulse == 0:
			raise BadPacket("ended with gap")
		if i >= len(logBuffer) - 1:
			raise BadPacket("no room")
		tGap = logBuffer[i+1]
		if tGap > params.gapMax:
			raise BadPacket("gap %d = %d" % (i - startIndex, tGap))
		if tGap == 0:
			#finish byte
			for i in range(8 - ticksIntoByte):
				currentByte >>= 1
				currentByte |= 0x80
			receivedBytes.append(currentByte)
			return
		dur = tPulse + tGap
		ticks = round(dur / params.tickLength)
		durRounded = ticks * params.tickLength
		offRounded = abs(dur - durRounded)
		if offRounded > params.tickMargin:
			raise BadPacket("pulse+gap %d = %d" % (i - startIndex, dur))
		for j in range(ticks - 1):
			currentByte >>= 1
			currentByte |= 0x80
		currentByte >>= 1
		ticksIntoByte += ticks
		i += 2

def receivePacketXros(pioIn, params, wait_ms):
	receivedBytes.clear()
	pioIn.clear_rxfifo()
	time.sleep(0.001)
	pioIn.clear_rxfifo()
	if receiveByteXros(pioIn, params, wait_ms, xrosInBuffers[0]):
		raise WaitEnded("nothing received")
	for i in range(1, xrosInSize):
		if receiveByteXros(pioIn, params, params.nextByteTimeout_ms, xrosInBuffers[i]):
			break
	#time1 = time.monotonic()
	for j in range(i):
		startIndex = len(logBuffer)
		decodeScopeBits(xrosInBuffers[j])
		decodeByteXros(params, startIndex)
	#print((time.monotonic() - time1) * 1000)

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

def receivePacketProngs(pulseIn, params, waitForStart_ms):
	pulseIn.clear()
	pulseIn.resume()
	packetLengthTimeout_ns = params.packetLengthTimeout_ms * 1_000_000
	#wait for first pulse:
	waitForStart(pulseIn, params, waitForStart_ms)
	#wait until we get enough durations or it takes too long:
	timeStart = time.monotonic_ns()
	while True:
		if len(pulseIn) >= 35:
			pulseIn.pause()
			break
		if time.monotonic_ns() - timeStart > packetLengthTimeout_ns:
			pulseIn.pause()
			raise BadPacket("timed out")
	#process the packet:
	#TODO: store timeStart-pulsesIn[0]?
	try:
		t = pulseIn.popleft()
		logBuffer.appendNoError(t)
		if t < params.preLowMin:
			raise BadPacket("preLow = %d" % t)
		t = pulseIn.popleft()
		logBuffer.appendNoError(t)
		if t < params.startHighMin or t > params.startHighMax:
			raise BadPacket("startHigh = %d" % t)
		t = pulseIn.popleft()
		logBuffer.appendNoError(t)
		if t < params.startLowMin or t > params.startLowMax:
			raise BadPacket("startLow = %d" % t)
		result = 0
		bitCount = 0
		for i in range(16):
			t = pulseIn.popleft()
			logBuffer.appendNoError(t)
			if t < params.bitHighMin or t > params.bitHighMax:
				raise BadPacket("bitHigh %d = %d" % (i + 1, t))
			result >>= 1
			if t > params.bitHighThreshold:
				result |= 0x8000
			t = pulseIn.popleft()
			logBuffer.appendNoError(t)
			if t < params.bitLowMin or t > params.bitLowMax:
				raise BadPacket("bitLow %d = %d" % (i + 1, t))
		print("%04X" % result)
	finally:
		logBuffer.appendNoError(0xFFFF)

def sendPacketProngs(pioOut, params, bitsToSend):
	if params.idleLevel == True:
		DRIVE_ACTIVE = 0
		DRIVE_INACTIVE = 1
	else:
		DRIVE_ACTIVE = 1
		DRIVE_INACTIVE = 0
	RELEASE = 2
	arrayToSend = array.array("L", [
		DRIVE_INACTIVE, params.preHighSend,
		DRIVE_ACTIVE, params.preLowSend,
		DRIVE_INACTIVE, params.startHighSend,
		DRIVE_ACTIVE, params.startLowSend,
	])
	for i in range(16):
		arrayToSend.append(DRIVE_INACTIVE)
		if bitsToSend & 1:
			arrayToSend.append(params.bit1HighSend)
			arrayToSend.append(DRIVE_ACTIVE)
			arrayToSend.append(params.bit1LowSend)
		else:
			arrayToSend.append(params.bit0HighSend)
			arrayToSend.append(DRIVE_ACTIVE)
			arrayToSend.append(params.bit0LowSend)
		bitsToSend >>= 1
	arrayToSend.append(DRIVE_INACTIVE)
	arrayToSend.append(params.cooldownSend)
	arrayToSend.append(RELEASE)
	pioOut.write(arrayToSend)

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
	outObject = None
	inObject = None
	if commType == TYPE_DATALINK or commType == TYPE_FUSION:
		outObject = pulseio.PulseOut(pinIRLED, frequency=38000, duty_cycle=2**15)
		inObject = pulseio.PulseIn(pinDemodIn, maxlen=300, idle_state=True)
		inObject.pause()
		def sendPacket(packet):
			sendPacketModulated(outObject, params, packet)
		def receivePacket(w):
			receivePacketModulated(inObject, params, w)
	elif commType == TYPE_IC:
		inObject = pulseio.PulseIn(pinRawIn, maxlen=300, idle_state=True)
		inObject.pause()
		outObject = rp2pio.StateMachine(
			iC_TX_PIO,
			frequency=100000,
			first_out_pin=pinIRLED,
			first_set_pin=pinIRLED,
		)
		def sendPacket(packet):
			outObject.write(bytes(packet))
		def receivePacket(w):
			receivePacket_iC(inObject, params, w)
	elif commType == TYPE_XROSLINK:
		inObject = pulseio.PulseIn(pinXrosIn, maxlen=300, idle_state=True)
		inObject.pause()
		outObject = rp2pio.StateMachine(
			iC_TX_PIO,
			frequency=25000,
			first_out_pin=pinIRLED,
			first_set_pin=pinIRLED,
		)
		def sendPacket(packet):
			outObject.write(bytes(packet))
		def receivePacket(w):
			receivePacket_iC(inObject, params, w)
	elif commType == TYPE_XROS:
		inObject = rp2pio.StateMachine(
			scope240_PIO,
			frequency=2_000_000,
			first_in_pin=pinXrosIn,
			in_shift_right=False,
			out_shift_right=True,
			auto_push=True,
			push_threshold=30,
		)
		outObject = rp2pio.StateMachine(
			durs_TX_PIO,
			frequency=1_000_000,
			#first_out_pin=pinIRLED,
			first_set_pin=pinIRLED,
			#wait_for_txstall=False, #temp for debugging
		)
		#print(outObject.frequency)
		def sendPacket(packet):
			toSend = array.array("L", [dur - 4 for dur in packet])
			#print(toSend)
			outObject.write(toSend)
			#temp for debugging:
			#testResult = array.array("L", [0])
			#while True:
			#	time.sleep(1)
			#	if outObject.in_waiting != 0:
			#		outObject.readinto(testResult)
			#		print("0x%08X" % testResult[0])
		def receivePacket(w):
			receivePacketXros(inObject, params, w)
	elif commType in [TYPE_2PRONG, TYPE_3PRONG, TYPE_XROSMINI]:
		prongWeakPullOut.value = params.idleLevel
		inObject = pulseio.PulseIn(pinProngIn, maxlen=100, idle_state=params.idleLevel)
		inObject.pause()
		outObject = rp2pio.StateMachine(
			prong_TX_PIO,
			frequency=1_000_000,
			first_set_pin=pinProngDrive,
			set_pin_count=2,
			initial_set_pin_direction=0,
		)
		def sendPacket(packet):
			sendPacketProngs(outObject, params, (packet[1] << 8) | packet[0])
		def receivePacket(w):
			receivePacketProngs(inObject, params, w)
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
		if inObject is not None:
			inObject.deinit()
		if outObject is not None:
			outObject.deinit()
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
#xrosTrade1 = [TYPE_XROS, True, [0x05], [0x02,0x05,0x00,0x01,0x01,0xE4,0x00,0xE6,0x03]]
#scope screenshots had [0x02,0x05,0x00,0x01,0xE4,0x00,0x00,0xE6,0x03] but maybe they were mixed up
#xrosTrade2 = [TYPE_XROS, False, [0x06]]
#xrosTest = [TYPE_XROS, True, [0x05,0xE4]]

#xrosTrade1 = [TYPE_XROS, True, [32,1,34,1,16,1,16,2,16,1,16,1,53,10], [15,1,34,1,16,1,16,1,16,2,16,1,16,1,53,2500, 32,1,34,1,16,1,16,2,16,1,16,1,52,2500, 15,2,16,1,16,1,16,1,16,2,16,1,16,1,16,2,52,2500, 32,1,16,2,16,1,16,1,16,2,16,1,16,1,53,2500, 32,2,16,1,16,1,16,1,16,2,16,1,16,1,53,2500, 15,1,16,2,33,1,16,2,52,2500,15,2,15,2,16,1,16,1,16,2,16,1,16,1,16,1,53,2500, 15,2,50,1,16,2,52,2500,49,2,16,1,16,1,16,2,16,1,16,1,52,10]]
#clean it up:
xrosTrade1 = [TYPE_XROS, True, [31,4,30,4,13,4,13,4,13,4,13,4,52,10], [14,4,30,4,13,4,13,4,13,4,13,4,13,4,52,2500, 31,4,30,4,13,4,13,4,13,4,13,4,52,2500, 14,4,13,4,13,4,13,4,13,4,13,4,13,4,13,4,52,2500, 31,4,13,4,13,4,13,4,13,4,13,4,13,4,52,2500, 31,4,13,4,13,4,13,4,13,4,13,4,13,4,52,2500, 14,4,13,4,30,4,13,4,52,2500,13,4,13,4,13,4,13,4,13,4,13,4,13,4,13,4,52,2500, 14,4,47,4,13,4,52,2500,48,4,13,4,13,4,13,4,13,4,13,4,52,10], [14,4,13,4,30,4,13,4,13,4,13,4,13,4,52,10]]
xrosTrade2 = [TYPE_XROS, False, [14,4,47,4,13,4,13,4,13,4,13,4,52,10], [14,4,47,4,13,4,13,4,13,4,13,4,52,10]]
xrosTest = [TYPE_XROS, True, [10,10,10,10,10,10]]

dmogBattle1 = [TYPE_2PRONG, True, [0x03, 0xFC], [0x02, 0xFD]]
dmogBattle2 = [TYPE_2PRONG, False, [0x03, 0xFC]]
jd3giveCourage = [TYPE_2PRONG, True, [0x0F, 0x8C], [0x0F, 0x48]]
penxGiveStrMax = [TYPE_3PRONG, False, [0x59, 0x04], [0x09, 0x07]]
xrosMiniBattle1 = [TYPE_XROSMINI, True, [0x17, 0x10], [0x97, 0x00], [0x47, 0x2E], [0xF7, 0x11]]

time.sleep(5)
runs = 1
while(True):
	print("begin", runs)
	runs += 1
	doComm(datalinkGive10Pt2nd, True)
