# Codex Status Light Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and upload a first ESP32-S3 firmware that verifies the traffic-light LED module and I2C OLED wiring.

**Architecture:** The firmware runs on an ESP32-S3 dev board using Arduino through PlatformIO. It controls three GPIO outputs for red/yellow/green LEDs and uses the Adafruit SSD1306 stack over I2C on SDA 21 and SCL/SCK 20.

**Tech Stack:** PlatformIO, Arduino framework for ESP32, Adafruit SSD1306, Adafruit GFX.

---

### Task 1: Create Firmware Project

**Files:**
- Create: `F:\Codex_project\codex_status_light\platformio.ini`
- Create: `F:\Codex_project\codex_status_light\src\main.cpp`
- Create: `F:\Codex_project\codex_status_light\.vscode\extensions.json`

- [ ] **Step 1: Define ESP32-S3 PlatformIO configuration**

Use `esp32-s3-devkitc-1` with 16 MB flash, USB CDC enabled for serial monitor, and OLED libraries.

- [ ] **Step 2: Write LED and OLED self-test firmware**

Set red on GPIO4, yellow on GPIO5, green on GPIO6. Set OLED SDA to GPIO21 and SCL to GPIO20. On boot, show the pin map and cycle red, yellow, green.

- [ ] **Step 3: Compile**

Run: `C:\Users\han\AppData\Roaming\Python\Python311\Scripts\pio.exe run`

Expected: PlatformIO installs the ESP32 platform and libraries, then reports success.

- [ ] **Step 4: Upload**

Run: `C:\Users\han\AppData\Roaming\Python\Python311\Scripts\pio.exe run --target upload`

Expected: Firmware is written to the ESP32-S3 once Windows exposes the board as a serial or USB bootloader device.

- [ ] **Step 5: Verify**

Run: `C:\Users\han\AppData\Roaming\Python\Python311\Scripts\pio.exe device monitor --baud 115200`

Expected: Serial logs show the current LED state and OLED address. The physical lights cycle and the OLED displays the status text.
