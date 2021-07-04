
import json, sys

LONG_GAP = -1
BYTE_ERROR = -2

#calculate the 16 redundancy bits for 16 bits of data
def redundancyBits(x):
    result = 0x79B4
    mask = 0x19D8
    for i in range(16):
        if x & 1:
            result ^= mask
        x >>= 1
        mask <<= 1
        if mask >= 0x10000:
            mask ^= 0x10811
    return result

#if a single bit 1->0 will fix it, return fixed data, else None
def autofix(data, chk):
    chkOfData = redundancyBits(data)
    if chkOfData == chk:
        return data
    mask = 0x0001
    for i in range(16):
        data2 = data & ~mask
        chk2 = chk & ~mask
        if chkOfData == chk2:
            return data
        if redundancyBits(data2) == chk:
            return data2
        mask <<= 1
    return None

class iC_decoder:
    def reset(self):
        self.dashes = []
        self.bytes = []
        self.currentByte = 0
        self.pulses = 0
    def addPulse(self):
        self.dashes.append("|")
        self.currentByte >>= 1
        self.pulses += 1
    def addNonPulse(self):
        self.dashes.append("-")
        self.currentByte >>= 1
        self.currentByte |= 0x80
        self.pulses += 1
    def endByte(self):
        for i in range(8 - self.pulses):
            self.addNonPulse()
        self.dashes.append(" ")
        self.bytes.append(self.currentByte)
        self.currentByte = 0
        self.pulses = 0
    def abortByte(self):
        self.dashes.append("x ")
        self.bytes.append(BYTE_ERROR)
        self.currentByte = 0
        self.pulses = 0
    def longGap(self):
        self.dashes.append("\n")
        self.bytes.append(LONG_GAP)
        self.currentByte = 0
        self.pulses = 0
    def decode(self, durations):
        self.reset()
        for dur in durations[1:]:
            ticks = round(dur / 100)
            dur100 = ticks * 100
            off100 = abs(dur - dur100)
            if self.pulses + ticks >= 9:
                self.endByte()
            elif off100 > 30:
                self.abortByte()
            else:
                for j in range(ticks - 1):
                    self.addNonPulse()
                self.addPulse()
            if dur > 15000:
                self.longGap()
        self.endByte()
    def getDiagram(self):
        return "".join(self.dashes)
    def getBytes(self):
        return self.bytes
    def getHex(self):
        def f(b):
            if b == BYTE_ERROR:
                return "??"
            elif b == LONG_GAP:
                return "....."
            else:
                return "%02X" % b
        return " ".join(f(b) for b in self.bytes)

class iC_decoder_step2:
    def __init__(self):
        self.startSequence = [0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFF,0x13,0x70,0x70]
    def reset(self):
        self.result = []
        self.startPacket()
    def startPacket(self):
        self.packetCursor = -1
        self.packetBytes = []
        self.packetBytesRaw = []
        self.got7D = False
    def abortPacket(self):
        if len(self.result) > 0 and self.result[-1].startswith("?"):
            self.result[-1] = self.result[-1] + "?"
        else:
            self.result.append("?")
        self.startPacket()
    def endPacket(self):
        hexstr = " ".join("%02X" % b for b in self.packetBytesRaw)
        if len(self.packetBytes) == 4 and None not in self.packetBytes:
            data = self.packetBytes[1] << 8 | self.packetBytes[0]
            chkGiven = self.packetBytes[3] << 8 | self.packetBytes[2]
            if chkGiven == redundancyBits(data):
                self.result.append("%04X" % data)
            else:
                dataFixed = autofix(data, chkGiven)
                if dataFixed is not None:
                    self.result.append("%04X autofix " % dataFixed + hexstr)
                else:
                    self.result.append("chkfail " + hexstr)
        else:
            self.result.append("error " + hexstr)
        self.startPacket()
    def processByte(self, b):
        self.packetCursor += 1
        if b == BYTE_ERROR:
            self.abortPacket()
        elif self.packetCursor == 0 and b in [LONG_GAP, 0xFF]:
            self.packetCursor -= 1
        elif self.packetCursor < 14:
            if b != self.startSequence[self.packetCursor]:
                self.abortPacket()
        else:
            self.packetBytesRaw.append(b)
            if self.got7D:
                #7D E0 -> C0, 7D E1 -> C1, 7D by itself is an error
                if b == 0xE0:
                    self.packetBytes.append(0xC0)
                    self.got7D = False
                elif b == 0xE1:
                    self.packetBytes.append(0xC1)
                    self.got7D = False
                else:
                    self.packetBytes.append(None)
            elif b == 0x7D:
                self.got7D = True
            elif b == 0xC1 or b == LONG_GAP:
                self.endPacket()
            else:
                self.packetBytes.append(b)
    def decode(self, bytes):
        self.reset()
        for b in bytes:
            self.processByte(b)
    def getHex(self):
        return "\t".join(x for x in self.result)

def decodeAndPrint(durations, mode, end):
    decoder.decode(durations)
    if mode == "dashes":
        print(decoder.getDiagram(), end=end)
    elif mode == "full":
        print(decoder.getHex(), end=end)
    else:
        decoder2.decode(decoder.getBytes())
        print(decoder2.getHex(), end=end)

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ["dashes", "full", "checked"]:
        print("dashes/full/checked?")
    else:
        decoder = iC_decoder()
        decoder2 = iC_decoder_step2()
        with open("irdata.json") as f:
            for item in json.load(f)["data"]:
                decodeType = item.get("decode", "")
                if decodeType == "ic" or decodeType == "ics":
                    print(item["id"], end="\t")
                    if "B" in item:
                        decodeAndPrint(item["A"], sys.argv[1], "\t")
                        print("B:", end="\t")
                        decodeAndPrint(item["B"], sys.argv[1], "\n")
                    else:
                        decodeAndPrint(item["A"], sys.argv[1], "\n")
