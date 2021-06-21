/* This file is part of the DMComm project by BladeSabre. License: MIT. */

#include "ircomm.h"

const byte pinIrLed = 6;
const byte pinInputBasic = 3;
const byte pinInputDemod = 8;
const uint16_t logBufferLength = 500;

uint16_t logBuffer[logBufferLength];
uint16_t logSize;

void setup() {
    Serial.begin(9600);
    digitalWrite(pinIrLed, LOW);
    pinMode(pinIrLed, OUTPUT);
    pinMode(pinInputBasic, INPUT_PULLUP);
    pinMode(pinInputDemod, INPUT_PULLUP);
}

void outputGapAndShortPulse(uint16_t t) {
    if (t > PULSE_LENGTH) {
        delayMicroseconds(t - PULSE_LENGTH);
    }
    digitalWrite(pinIrLed, HIGH);
    delayMicroseconds(PULSE_LENGTH);
    digitalWrite(pinIrLed, LOW);
}

void outputLongPulse(uint16_t t) {
    digitalWrite(pinIrLed, HIGH);
    delayMicroseconds(t);
    digitalWrite(pinIrLed, LOW);
}

void outputModulated(uint16_t t) {
    uint16_t pulses;
    if (t > 1500) {
        pulses = (t / 64) * 39 / 16;
    } else {
        pulses = t * 39 / 1024;
    }
    for (uint16_t pulse = 0; pulse < pulses; pulse ++) {
        digitalWrite(pinIrLed, HIGH);
        delayMicroseconds(13);
        digitalWrite(pinIrLed, LOW);
        delayMicroseconds(13);
    }
}

void execute(const uint16_t * sequence) {
    uint16_t seqType = pgm_read_word_near(sequence);
    uint16_t cursor = 1;
    uint16_t item;
    bool wasOn = false;
    logSize = 0;
    Serial.println(seqType); //test
    while (true) {
        item = pgm_read_word_near(sequence + cursor);
        if (item == END) {
            break;
        }
        if (item == WAIT) {
            wasOn = false;
            cursor += 1;
            item = pgm_read_word_near(sequence + cursor); //end timeout
            if (seqType == TYPE_PULSE) {
                //TODO
            } else if (seqType == TYPE_GAP_AND_PULSE) {
                //TODO
            } else {
                //modulated
                //TODO
            }
        } else {
            if (seqType == TYPE_PULSE) {
                outputGapAndShortPulse(item);
            } else if (seqType == TYPE_GAP_AND_PULSE) {
                if (wasOn) {
                    delayMicroseconds(item);
                    wasOn = false;
                } else {
                    outputLongPulse(item);
                    wasOn = true;
                }
            } else {
                //modulated
                if (wasOn) {
                    delayMicroseconds(item);
                    wasOn = false;
                } else {
                    outputModulated(item);
                    wasOn = true;
                }
            }
        }
        cursor ++;
    }
}

void loop() {
    int8_t b, n, i;
    uint16_t * sequence;
    if (Serial.available()) {
        b = Serial.read();
        n = b - 'a';
        if (b == '\n') {
            //do nothing
        } else if (n >= 0 && n < numSequences) {
            sequence = pgm_read_ptr_near(sequences + n);
            while (pgm_read_word_near(sequence) != END) {
                sequence ++;
            }
            sequence ++;
            execute(sequence);
        } else {
            for (n = 0; n < numSequences; n ++) {
                Serial.write('a' + n);
                Serial.write(' ');
                sequence = pgm_read_ptr_near(sequences + n);
                while (pgm_read_word_near(sequence) != END) {
                    Serial.write(pgm_read_word_near(sequence));
                    sequence ++;
                }
                Serial.println();
            }
        }
    }
}
