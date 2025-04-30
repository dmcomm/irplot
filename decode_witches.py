
import json

CLOCK = 19520

def decode(pulses):
	result = []
	current_byte = 0
	bit_count = 0
	level = 1
	for pulse in pulses:
		new_bits = round(pulse / CLOCK)
		for _ in range(new_bits):
			current_byte <<= 1
			current_byte |= level
		bit_count += new_bits
		level = 1 - level
		if bit_count == 10:
			result.append((current_byte >> 1) & 0xFF)
			current_byte = 0
			bit_count = 0
		if bit_count > 10:
			# this is an error: raise exception in the real thing
			result.append(0x1000 + bit_count)
			return result
	current_byte <<= 10 - bit_count
	result.append((current_byte >> 1) & 0xFF)
	return result

if __name__ == "__main__":
    with open("irdata.json") as f:
        for item in json.load(f)["data"]:
            if item["id"].startswith("mw"):
                pulses = item["A"][1:]
                decoding = decode(pulses)
                print(" ".join("%02X" % x for x in decoding), end="\t")
                #print(" ".join("%.2f" % (x / CLOCK) for x in pulses), end="\t")
                print(item["id"])

