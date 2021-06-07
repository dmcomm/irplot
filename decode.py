
import json

class iC_decoder:
    def reset(self):
        self.dashes = []
        self.hexpackets = []
        self.hexdigits = []
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
        self.currentByte = 0
        self.pulses = 0
    def abortByte(self):
        self.dashes.append("x ")
        self.hexdigits.append("?")
        self.currentByte = 0
        self.pulses = 0
    def endPacket(self):
        self.dashes.append("\n")
        if self.cropHex:
            self.hexdigits = self.hexdigits[14:-1]
        if self.reverseHex:
            self.hexdigits.reverse()
        self.hexpackets.append(self.hexdigits)
        self.hexdigits = []
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
        return "\t".join(" ".join(x) for x in self.hexpackets)

if __name__ == "__main__":
    with open("irdata.json") as f:
        decoder = iC_decoder()
        for item in json.load(f)["data"]:
            decoder.decode(item["A"])
            #print(item["id"])
            #print(decoder.getDiagram())
            print(decoder.getHex(), end="\t")
            decoder.decode(item["B"], cropHex=True)
            print(decoder.getHex())
