/* This file is part of the DMComm project by BladeSabre. License: MIT. */

const uint16_t WAIT = 0xFFFF;
const uint16_t END = 0xFFFE;

class SequenceHandler {
public:
    bool isModulated;
    bool goFirst;
    uint16_t replyDelay;
    void list(Stream& output);
    int8_t load(uint8_t id);
    uint16_t get(uint16_t i);
private:
    uint16_t * durationsPGM;
};

extern SequenceHandler sequenceHandler;
