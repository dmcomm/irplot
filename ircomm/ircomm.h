/* This file is part of the DMComm project by BladeSabre. License: MIT. */

const uint16_t TYPE_PULSE = 0;
const uint16_t TYPE_GAP_AND_PULSE = 1;
const uint16_t TYPE_MODULATED = 2;

const uint16_t WAIT = 0xFFFF;
const uint16_t END = 0xFFFE;

const uint16_t PULSE_LENGTH = 20;

extern const uint16_t * const sequences[] PROGMEM;
extern const int8_t numSequences;
