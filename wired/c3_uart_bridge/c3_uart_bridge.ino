// ESP32-C3 SuperMini: native USB CDC <-> UART1, 115200 8N1.
// First validate with ONLY GPIO5 wired to GPIO4. Disconnect the Q-SL1.
// This sketch generates no target commands and prints no diagnostic text.

#include <Arduino.h>
#include <HardwareSerial.h>
#include <driver/gpio.h>
#include <esp_log.h>

#if !defined(CONFIG_IDF_TARGET_ESP32C3)
#error "This sketch is for ESP32-C3 only."
#endif
#if !ARDUINO_USB_CDC_ON_BOOT || !ARDUINO_USB_MODE
#error "Enable native hardware USB CDC on boot."
#endif

constexpr int TARGET_RX = 4;
constexpr int TARGET_TX = 5;
constexpr uint32_t TARGET_BAUD = 115200;

HardwareSerial target(1);

struct Pending {
  uint8_t bytes[256];
  size_t count = 0;
  size_t offset = 0;

  void clear() {
    count = 0;
    offset = 0;
  }
};

Pending fromUsb;
Pending fromTarget;

// Keep unsent bytes after a short write. Do not read another chunk until
// the previous one has been accepted by the destination.
template <typename Source, typename Destination>
void forwardBytes(Source& source, Destination& destination, Pending& pending) {
  if (pending.offset == pending.count) {
    pending.clear();
    int ready = source.available();
    while (ready-- > 0 && pending.count < sizeof(pending.bytes)) {
      const int next = source.read();
      if (next < 0) {
        break;
      }
      pending.bytes[pending.count++] = static_cast<uint8_t>(next);
    }
  }

  const int room = destination.availableForWrite();
  if (room <= 0 || pending.offset == pending.count) {
    return;
  }

  size_t amount = pending.count - pending.offset;
  if (amount > static_cast<size_t>(room)) {
    amount = static_cast<size_t>(room);
  }
  if (amount > 64) {
    amount = 64;
  }
  const size_t sent = destination.write(pending.bytes + pending.offset, amount);
  if (sent <= amount) {
    pending.offset += sent;
  }
}

void setup() {
  esp_log_level_set("*", ESP_LOG_NONE);
  Serial.setDebugOutput(false);
  Serial.setRxBufferSize(4096);
  Serial.setTxBufferSize(4096);
  Serial.setTxTimeoutMs(5);
  Serial.begin();  // Native USB; does not set the target UART baud rate.

  target.setRxBufferSize(4096);
  target.setTxBufferSize(2048);
  target.begin(TARGET_BAUD, SERIAL_8N1, TARGET_RX, TARGET_TX);
  target.setHwFlowCtrlMode(UART_HW_FLOWCTRL_DISABLE);
  gpio_pulldown_dis(GPIO_NUM_4);
  gpio_pullup_en(GPIO_NUM_4);
}

void loop() {
  if (!Serial) {
    // Do not accumulate application-level traffic to replay after reconnect.
    fromUsb.clear();
    fromTarget.clear();
    while (Serial.available() > 0) {
      Serial.read();
    }
    while (target.available() > 0) {
      target.read();
    }
    delay(1);
    return;
  }

  forwardBytes(Serial, target, fromUsb);
  forwardBytes(target, Serial, fromTarget);
  delay(1);
}
