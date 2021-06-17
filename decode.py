
import json, sys

def checksum(x):
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

def byteReplace(bytes):
    result = []
    got7D = False
    for b in bytes:
        if got7D:
            if b == 0xE0:
                result.append(0xC0)
                got7D = False
            elif b == 0xE1:
                result.append(0xC1)
                got7D = False
            else:
                result.append(None)
        elif b == 0x7D:
            got7D = True
        else:
            result.append(b)
    return result

class iC_decoder:
    def reset(self):
        self.dashes = []
        self.hexpackets = []
        self.hexdigits = []
        self.checked = []
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
        self.hexdigits.append("%02X" % self.currentByte)
        self.bytes.append(self.currentByte)
        self.currentByte = 0
        self.pulses = 0
    def abortByte(self):
        self.dashes.append("x ")
        self.hexdigits.append("?")
        self.bytes.append(None)
        self.currentByte = 0
        self.pulses = 0
    def endPacket(self):
        self.dashes.append("\n")
        self.bytes = self.bytes[14:-1]
        if self.cropHex:
            self.hexdigits = self.hexdigits[14:-1]
        if self.reverseHex:
            self.hexdigits.reverse()
        hexstr = " ".join(self.hexdigits)
        self.hexpackets.append(hexstr)
        bytes2 = byteReplace(self.bytes)
        if len(bytes2) == 4 and None not in bytes2:
            data = bytes2[1] << 8 | bytes2[0]
            checksum1 = bytes2[3] << 8 | bytes2[2]
            checksum2 = checksum(data)
            if checksum1 == checksum2:
                self.checked.append("%04X" % data)
            else:
                self.checked.append("chkfail " + hexstr)
        else:
            self.checked.append("error " + hexstr)
        self.hexdigits = []
        self.bytes = []
        self.currentByte = 0
        self.pulses = 0
    def decode(self, durations, cropHex=False, reverseHex=False):
        self.cropHex = cropHex
        self.reverseHex = reverseHex
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
                self.endPacket()
        self.endByte()
        self.endPacket()
    def getDiagram(self):
        return "".join(self.dashes)
    def getHex(self):
        return "\t".join(self.hexpackets)
    def getChecked(self):
        return "\t".join(self.checked)

def decodeAndPrint(durations, mode, end):
    if mode == "dashes":
        decoder.decode(durations, cropHex=False)
        print(decoder.getDiagram(), end=end)
    elif mode == "full":
        decoder.decode(durations, cropHex=False)
        print(decoder.getHex(), end=end)
    else:
        decoder.decode(durations, cropHex=True)
        print(decoder.getChecked(), end=end)

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ["dashes", "full", "checked"]:
        print("dashes/full/checked?")
    else:
        decoder = iC_decoder()
        with open("irdata.json") as f:
            for item in json.load(f)["data"]:
                print(item["id"], end="\t")
                decodeAndPrint(item["A"], sys.argv[1], "\t")
                decodeAndPrint(item["B"], sys.argv[1], "\n")
