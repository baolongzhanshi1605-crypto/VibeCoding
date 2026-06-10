#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>

constexpr uint8_t PIN_LED_RED = 4;
constexpr uint8_t PIN_LED_YELLOW = 5;
constexpr uint8_t PIN_LED_GREEN = 6;

constexpr uint8_t PIN_OLED_SDA = 8;
constexpr uint8_t PIN_OLED_SCL = 9;

// Chinese labels are UTF-8 byte strings so this source file stays ASCII-safe.
constexpr const char *TEXT_TITLE =
    "Codex"
    "\xE5\xB7\xA5"
    "\xE4\xBD\x9C"
    "\xE6\x8C\x87"
    "\xE7\xA4\xBA"
    "\xE7\x81\xAF";
constexpr const char *TEXT_STATUS_LABEL =
    "\xE7\x9B\xAE"
    "\xE5\x89\x8D"
    "\xE7\x8A\xB6"
    "\xE6\x80\x81"
    "\xEF\xBC\x9A";
constexpr const char *TEXT_IDLE =
    "\xE7\xA9\xBA"
    "\xE9\x97\xB2";
constexpr const char *TEXT_WORKING =
    "\xE6\xAD\xA3"
    "\xE5\x9C\xA8"
    "\xE5\xB9\xB2"
    "\xE6\xB4\xBB";
constexpr const char *TEXT_WAITING =
    "\xE7\xAD\x89"
    "\xE5\xBE\x85"
    "\xE7\xA1\xAE"
    "\xE8\xAE\xA4";
constexpr const char *TEXT_DONE =
    "\xE5\xAE\x8C"
    "\xE6\x88\x90"
    "\xE4\xBB\xBB"
    "\xE5\x8A\xA1";

U8G2_SSD1306_128X64_NONAME_F_SW_I2C display(
    U8G2_R0,
    PIN_OLED_SCL,
    PIN_OLED_SDA,
    U8X8_PIN_NONE);

uint8_t oledAddress = 0x3C;
bool oledReady = false;
unsigned long lastRefreshAt = 0;
uint8_t currentState = 0;

struct LightState {
  const char *name;
  const char *statusText;
  uint8_t red;
  uint8_t yellow;
  uint8_t green;
};

const LightState states[] = {
    {"IDLE", TEXT_IDLE, LOW, LOW, HIGH},
    {"WORKING", TEXT_WORKING, LOW, HIGH, LOW},
    {"WAITING", TEXT_WAITING, HIGH, LOW, LOW},
    {"DONE", TEXT_DONE, LOW, LOW, HIGH},
};

void setLights(const LightState &state) {
  digitalWrite(PIN_LED_RED, state.red);
  digitalWrite(PIN_LED_YELLOW, state.yellow);
  digitalWrite(PIN_LED_GREEN, state.green);
}

bool i2cDeviceExists(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

bool initOled() {
  if (i2cDeviceExists(0x3C)) {
    oledAddress = 0x3C;
  } else if (i2cDeviceExists(0x3D)) {
    oledAddress = 0x3D;
  } else {
    return false;
  }

  display.setI2CAddress(oledAddress << 1);
  Serial.println("OLED begin...");
  display.begin();
  Serial.println("OLED begin done");
  display.enableUTF8Print();
  return true;
}

void scanI2cBus() {
  Serial.println("I2C scan start");
  uint8_t count = 0;

  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.print("I2C device found at 0x");
      if (address < 16) {
        Serial.print("0");
      }
      Serial.println(address, HEX);
      count++;
    }
  }

  if (count == 0) {
    Serial.println("I2C scan found no devices");
  }
}

void drawStatus(const LightState &state) {
  if (!oledReady) {
    return;
  }

  display.clearBuffer();
  display.setFont(u8g2_font_wqy12_t_gb2312);
  display.drawUTF8(0, 14, TEXT_TITLE);
  display.drawUTF8(0, 29, "----------------");
  display.drawUTF8(0, 49, TEXT_STATUS_LABEL);
  display.drawUTF8(66, 49, state.statusText);
  display.sendBuffer();
}

void showState(uint8_t index) {
  const LightState &state = states[index];
  setLights(state);
  drawStatus(state);

  Serial.print("State=");
  Serial.print(state.name);
  Serial.print(" R=");
  Serial.print(PIN_LED_RED);
  Serial.print(" Y=");
  Serial.print(PIN_LED_YELLOW);
  Serial.print(" G=");
  Serial.print(PIN_LED_GREEN);
  Serial.print(" OLED=");
  Serial.println(oledReady ? "OK" : "NOT_FOUND");
}

void handleCommand(String command) {
  command.trim();
  command.toLowerCase();

  if (command == "green" || command == "idle") {
    currentState = 0;
  } else if (command == "yellow" || command == "work" || command == "working") {
    currentState = 1;
  } else if (command == "red" || command == "wait" || command == "waiting") {
    currentState = 2;
  } else if (command == "done") {
    currentState = 3;
  } else if (command.length() > 0) {
    Serial.print("Unknown command: ");
    Serial.println(command);
    Serial.println("Use: idle, working, waiting, done");
    return;
  }

  showState(currentState);
}

void setup() {
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  setLights(states[currentState]);

  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("Serial ready");
  Serial.println("Starting OLED probe...");

  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  Wire.setClock(100000);
  scanI2cBus();
  oledReady = initOled();

  Serial.println("Codex Status Light");
  Serial.println("Pins: R=4 Y=5 G=6 OLED_SDA=8 OLED_SCK=9");
  Serial.println(oledReady ? "OLED detected" : "OLED not found at 0x3C/0x3D");

  showState(currentState);
  lastRefreshAt = millis();
}

void loop() {
  if (Serial.available() > 0) {
    handleCommand(Serial.readStringUntil('\n'));
  }

  if (millis() - lastRefreshAt >= 1000) {
    drawStatus(states[currentState]);
    lastRefreshAt = millis();
  }
}
