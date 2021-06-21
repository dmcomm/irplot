/* This file is part of the DMComm project by BladeSabre. License: MIT. */

#include "ircomm.h"

const byte pinIrLed = 6;
const byte pinInputBasic = 3;
const byte pinInputDemod = 8;
const byte pinProbe = 2;

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
    pinMode(pinProbe, OUTPUT);
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

void outputPulse(uint16_t t) {
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
        delayMicroseconds(7);
        digitalWrite(pinIrLed, LOW);
        delayMicroseconds(7);
    }
    //TODO Take into account the time spent not waiting. Or use PWM.
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

int8_t receivePacket(bool first) {
    int32_t t;
    uint8_t pin;
    if (first) {
        t = initialTimeout;
    } else {
        t = replyTimeout;
    }
    if (sequenceHandler.isModulated) {
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
        t = waitLevel(pin, HIGH, sequenceHandler.replyDelay);
        if (t == -1) {
            //it shouldn't stop in the "on" state
            addLogItem(END);
            return -1;
        }
        //recording the "on" time
        addLogItem(packDur(t));
        t = waitLevel(pin, LOW, sequenceHandler.replyDelay);
        if (t == -1) {
            //finished
            return 0;
        }
        //recording the "off" time
        addLogItem(packDur(t));
    }
}

void execute() {
    uint16_t cursor = 0;
    uint16_t item;
    bool wasOn = false;
    logSize = 0;
    if (!sequenceHandler.goFirst) {
        if (receivePacket(true) == -1) {
            return;
        }
    }
    while (true) {
        item = sequenceHandler.get(cursor);
        if (item == END) {
            return;
        }
        if (item == WAIT) {
            digitalWrite(pinProbe, HIGH);
            delayMicroseconds(5);
            digitalWrite(pinProbe, LOW);
            wasOn = false;
            if (receivePacket(false) == -1) {
                return;
            }
        } else {
            if (wasOn) {
                delayMicroseconds(item);
                wasOn = false;
            } else if (sequenceHandler.isModulated) {
                outputModulated(item);
                wasOn = true;
            } else {
                outputPulse(item);
                wasOn = true;
            }
        }
        cursor ++;
    }
}

void loop() {
    int8_t b;
    uint16_t cursor;
    if (Serial.available()) {
        b = Serial.read();
        if (b == '\n') {
            //do nothing
        } else if (sequenceHandler.load(b) == 0) {
            execute();
            for (cursor = 0; cursor < logSize; cursor ++) {
                if (logBuffer[cursor] == END) {
                    Serial.print(F("END"));
                } else {
                    Serial.print(unpackDur(logBuffer[cursor]));
                }
                Serial.write(',');
            }
            Serial.println();
        } else {
            sequenceHandler.list(Serial);
        }
    }
}
