/*
 * This file is part of the DMComm project by BladeSabre. License: MIT.
 *
 * Pi Pico with two TSMP58000 (each with a 4K7 pullup resistor):
 * sensor "A" on pins 17-19 facing outwards, "B" on pins 22-24 facing outwards.
 * Triggers on channel A falling, records falling edges on the two channels,
 * and outputs JSON for irplot.js . However there is too much crossover.
 * With this type of sensor, seems it's better to use only one of them.
 */

const byte pinCHA = 13;
const byte pinExtraPowerA = 14;
const byte pinCHB = 17;
const byte pinExtraPowerB = 18;
const uint32_t timeoutA = 500000;
const uint32_t bufSize = 5000;

uint32_t bufferA[bufSize];
uint32_t bufferB[bufSize];
uint32_t prevTimeA, prevTimeB, cursorA, cursorB;
byte prevLevelA, prevLevelB;

void setup() {
    Serial.begin(9600);
    pinMode(pinCHA, INPUT);
    pinMode(pinCHB, INPUT);
    pinMode(pinExtraPowerA, OUTPUT);
    digitalWrite(pinExtraPowerA, HIGH);
    pinMode(pinExtraPowerB, OUTPUT);
    digitalWrite(pinExtraPowerB, HIGH);
    pinMode(LED_BUILTIN, OUTPUT);
}

void printResults(uint32_t * buffer, uint32_t count) {
    for (uint32_t cursor = 0; cursor < count; cursor ++) {
        Serial.print(buffer[cursor]);
        if (cursor != count - 1) {
            Serial.write(",");
        }
    }
}

void loop() {
    byte levelA, levelB;
    uint32_t currentTime;
    digitalWrite(LED_BUILTIN, HIGH);
    while (digitalRead(pinCHA) != LOW);
    bufferA[0] = 0;
    cursorA = 1;
    cursorB = 0;
    prevLevelA = LOW;
    prevLevelB = HIGH;
    prevTimeA = micros();
    prevTimeB = prevTimeA;
    digitalWrite(LED_BUILTIN, HIGH);
    while (true) {
        levelA = digitalRead(pinCHA);
        levelB = digitalRead(pinCHB);
        currentTime = micros();
        if (prevLevelA == HIGH && levelA == LOW && cursorA < bufSize) {
            bufferA[cursorA++] = currentTime - prevTimeA;
            prevTimeA = currentTime;
        }
        if (prevLevelB == HIGH && levelB == LOW && cursorB < bufSize) {
            bufferB[cursorB++] = currentTime - prevTimeB;
            prevTimeB = currentTime;
        }
        if (currentTime - prevTimeA > timeoutA) {
            break;
        }
        prevLevelA = levelA;
        prevLevelB = levelB;
    }
    Serial.print("{\"id\": \"\",\n\"note\": \"\",\n\"decode\": \"ic\",\n\"A\": [");
    printResults(bufferA, cursorA);
    Serial.print("],\n\"B\": [");
    printResults(bufferB, cursorB);
    Serial.print("]\n},\n\n");
    delay(200);
}
