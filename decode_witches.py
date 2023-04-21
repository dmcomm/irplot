
import json

CLOCK = 19520
ADJUST_HIGH = 0
ADJUST_LOW = CLOCK // 2

def decode(pulses):
	result = []
	current_byte = 0
	bit_count = 0
	level = True
	for pulse in pulses:
		if level:
			# falling edge, round down prev high
			new_bits = (pulse + ADJUST_HIGH) // CLOCK
			for _ in range(new_bits):
				current_byte <<= 1
				current_byte |= 1
			bit_count += new_bits
		else:
			# rising edge, round up prev low
			new_bits = (pulse + ADJUST_LOW) // CLOCK
			current_byte <<= new_bits
			bit_count += new_bits
		level = not level
		if bit_count == 10:
			result.append((current_byte >> 1) & 0xFF)
			current_byte = 0
			bit_count = 0
		if bit_count > 10:
			result.append(0x1000 + bit_count)
			return result
	current_byte <<= 10 - bit_count
	result.append((current_byte >> 1) & 0xFF)
	return result

if __name__ == "__main__":
    with open("irdata.json") as f:
        for item in json.load(f)["data"]:
            if item["id"].startswith("mw"):
                decoding = decode(item["A"][1:])
                print(" ".join("%02X" % x for x in decoding), end="\t")
                print(item["id"])

