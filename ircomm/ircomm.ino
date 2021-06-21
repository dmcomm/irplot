/* This file is part of the DMComm project by BladeSabre. License: MIT. */

#include "ircomm.h"

const byte pinIrLed = 6;
const byte pinInputBasic = 3;
const byte pinInputDemod = 8;

const int32_t replyTimeout = 20000;
const int32_t initialTimeout = 5000000;

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

uint16_t packDur(uint32_t dur) {
    if (dur < 0x8000) {
        return dur;
    } else if (dur < 0x100000) {
        return 0x8000 | (dur >> 5);
    } else {
        return END;
    }
}

uint32_t unpackDur(uint16_t packedDur) {
    if (packedDur < 0x8000) {
        return packedDur;
    } else {
        return (((uint32_t)(packedDur & 0x7FFF)) << 5);
    }
}

void addLogItem(uint16_t item) {
    if (logSize < logBufferLength) {
        logBuffer[logSize] = item;
        logSize ++;
    }
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

int32_t waitLevel(uint8_t pin, uint8_t level, int32_t timeoutMicros) {
    int32_t startTime = micros();
    int32_t dur = 0;
    while (digitalRead(pin) != level && dur < timeoutMicros) {
        dur = micros() - startTime;
    }
    if (dur < timeoutMicros) {
        return dur;
    } else {
        return -1;
    }
}

int8_t receivePacket(uint16_t seqType, bool first, uint16_t endTimeout) {
    int32_t t, tFalling;
    uint8_t pin;
    if (first) {
        t = initialTimeout;
    } else {
        t = replyTimeout;
    }
    if (seqType == TYPE_MODULATED) {
        pin = pinInputDemod;
    } else {
        pin = pinInputBasic;
    }
    t = waitLevel(pin, LOW, t);
    if (t == -1) {
        addLogItem(END);
        return -1;
    }
    if (first) {
        addLogItem(0);
    } else {
        addLogItem(packDur(t)); //TODO ?
    }
    while (true) {
        tFalling = t;
        t = waitLevel(pin, HIGH, endTimeout);
        if (t == -1) {
            //it shouldn't stop in the "on" state
            addLogItem(END);
            return -1;
        }
        if (seqType != TYPE_PULSE) {
            //recording the "on" time
            addLogItem(packDur(t));
        }
        t = waitLevel(pin, LOW, endTimeout);
        if (t == -1) {
            //finished
            return 0;
        }
        if (seqType == TYPE_PULSE) {
            //recording the total time
            addLogItem(packDur(t + tFalling));
        } else {
            //recording the "off" time
            addLogItem(packDur(t));
        }
    }
}

void execute(const uint16_t * sequence) {
    uint16_t seqType = pgm_read_word_near(sequence);
    uint16_t cursor = 1;
    uint16_t item;
    bool wasOn = false;
    bool receivingFirst;
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
            receivingFirst = (cursor == 2);
            if (receivePacket(seqType, receivingFirst, item) == -1) {
                break;
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
    for (cursor = 0; cursor < logSize; cursor ++) {
        Serial.print(unpackDur(logBuffer[cursor]));
        Serial.write(',');
    }
    Serial.println();
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
