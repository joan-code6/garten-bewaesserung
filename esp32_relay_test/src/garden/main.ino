#include <WiFi.h>
#include <esp_now.h>

// ==================== CONFIG ====================

const int  RELAY_PINS[]     = {5, 6, 7};
const int  RELAY_COUNT      = sizeof(RELAY_PINS) / sizeof(RELAY_PINS[0]);
const bool RELAY_ACTIVE_LOW = false;

const unsigned long STATUS_INTERVAL = 60000;

// ==================== STATE ====================

bool relayStates[RELAY_COUNT] = {false};
unsigned long lastStatus = 0;

esp_now_peer_info_t bridgePeer;
bool bridgeKnown = false;

// ==================== RELAY HELPERS ====================

int relayIdx(int pin) {
  for (int i = 0; i < RELAY_COUNT; i++)
    if (RELAY_PINS[i] == pin) return i;
  return -1;
}

void setRelay(int idx, bool on) {
  relayStates[idx] = on;
  bool level = RELAY_ACTIVE_LOW ? !on : on;
  digitalWrite(RELAY_PINS[idx], level ? HIGH : LOW);
}

// ==================== JSON HELPERS ====================

bool parseSet(const char* json, int* pin, bool* state) {
  const char* p = strstr(json, "\"pin\"");
  if (!p) return false;
  p = strchr(p, ':');
  if (!p) return false;
  *pin = atoi(p + 1);

  p = strstr(json, "\"state\"");
  if (!p) return false;
  p = strchr(p, ':');
  if (!p) return false;
  *state = atoi(p + 1) != 0;

  return true;
}

// ==================== ESP-NOW SEND ====================

void sendToBridge(const char* json) {
  if (!bridgeKnown) return;
  esp_now_send(bridgePeer.peer_addr, (uint8_t*)json, strlen(json));
}

void sendState(int pin, bool on) {
  char buf[64];
  snprintf(buf, sizeof(buf), "{\"type\":\"state\",\"pin\":%d,\"state\":%d}", pin, on);
  sendToBridge(buf);
}

void sendStatus() {
  char buf[160];
  snprintf(buf, sizeof(buf),
    "{\"type\":\"status\",\"uptime\":%lu,\"relays\":{\"5\":%d,\"6\":%d,\"7\":%d}}",
    millis() / 1000, relayStates[0], relayStates[1], relayStates[2]);
  sendToBridge(buf);
}

// ==================== ESP-NOW RECV ====================

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  char msg[128] = {0};
  int n = len < 127 ? len : 127;
  memcpy(msg, data, n);

  if (!bridgeKnown) {
    memcpy(bridgePeer.peer_addr, info->src_addr, 6);
    bridgePeer.channel = 0;
    bridgePeer.encrypt = false;
    if (esp_now_add_peer(&bridgePeer) == ESP_OK) {
      bridgeKnown = true;
      Serial.print("Bridge learned: ");
      for (int i = 0; i < 6; i++) {
        if (info->src_addr[i] < 0x10) Serial.print("0");
        Serial.print(info->src_addr[i], HEX);
        if (i < 5) Serial.print(":");
      }
      Serial.println();
    }
  }

  if (strstr(msg, "\"cmd\":\"set\"")) {
    int pin;
    bool state;
    if (parseSet(msg, &pin, &state)) {
      int idx = relayIdx(pin);
      if (idx >= 0) {
        setRelay(idx, state);
        sendState(pin, state);
        Serial.print("GPIO "); Serial.print(pin);
        Serial.print(" -> "); Serial.println(state ? "ON" : "OFF");
      }
    }
  } else if (strstr(msg, "\"cmd\":\"status\"")) {
    sendStatus();
  }
}

// ==================== SETUP & LOOP ====================

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== Garden ESP-NOW v3 ===");

  for (int i = 0; i < RELAY_COUNT; i++) {
    pinMode(RELAY_PINS[i], OUTPUT);
    setRelay(i, false);
  }

  WiFi.mode(WIFI_STA);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init FAILED");
    return;
  }
  esp_now_register_recv_cb(onRecv);

  lastStatus = millis();
  Serial.println("Ready — waiting for bridge.\n");
}

void loop() {
  unsigned long now = millis();
  if (bridgeKnown && now - lastStatus >= STATUS_INTERVAL) {
    lastStatus = now;
    sendStatus();
  }
  delay(100);
}
