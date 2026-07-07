#include <WiFi.h>
#include <PubSubClient.h>
#include <esp_now.h>

// ==================== CONFIG ====================

const char* WIFI_SSID  = "YOUR_WIFI_SSID";
const char* WIFI_PASS  = "YOUR_WIFI_PASSWORD";

const char* MQTT_BROKER = "192.168.178.54";
const int   MQTT_PORT   = 1883;
const char* MQTT_ID     = "garden_bridge";

const char* TOPIC_SET    = "garden/relay/set";
const char* TOPIC_STATE  = "garden/relay/state";
const char* TOPIC_STATUS = "garden/status";

uint8_t gardenMAC[] = {0xE8, 0x3D, 0xC1, 0x9E, 0x1D, 0x90};

const unsigned long RETRY_MS = 10000;

// ==================== STATE ====================

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

bool gardenSeen  = false;
unsigned long lastGardenMsg = 0;
int  lastGardenRssi = 0;

unsigned long lastMqttRetry = 0;
unsigned long lastWiFiRetry = 0;

// ==================== ESP-NOW CALLBACKS ====================

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  char msg[160] = {0};
  int n = len < 159 ? len : 159;
  memcpy(msg, data, n);

  lastGardenRssi = info->rx_ctrl->rssi;
  gardenSeen = true;
  lastGardenMsg = millis();

  if (strstr(msg, "\"type\":\"state\"")) {
    mqtt.publish(TOPIC_STATE, msg);
  } else if (strstr(msg, "\"type\":\"status\"")) {
    const char* brace = strchr(msg, '}');
    if (brace) {
      char enriched[200];
      int prefixLen = brace - msg;
      snprintf(enriched, sizeof(enriched),
        "%.*s,\"rssi\":%d}", prefixLen, msg, lastGardenRssi);
      mqtt.publish(TOPIC_STATUS, enriched, true);
    } else {
      mqtt.publish(TOPIC_STATUS, msg, true);
    }
  }

  Serial.print("Garden("); Serial.print(lastGardenRssi); Serial.print("dBm): ");
  Serial.println(msg);
}

// ==================== MQTT CALLBACK ====================

void mqttCallback(char* topic, byte* payload, unsigned int len) {
  char msg[128] = {0};
  int n = len < 127 ? len : 127;
  memcpy(msg, payload, n);

  char cmd[160];
  snprintf(cmd, sizeof(cmd), "{\"cmd\":\"set\",%s", msg + 1);
  // {"pin":5,"state":1} → {"cmd":"set","pin":5,"state":1}

  esp_err_t err = esp_now_send(gardenMAC, (uint8_t*)cmd, strlen(cmd));
  if (err != ESP_OK) {
    Serial.print("ESP-NOW send failed: "); Serial.println(err);
  }
  Serial.print("MQTT -> Garden: "); Serial.println(cmd);
}

// ==================== CONNECTION ====================

bool connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  if (millis() - lastWiFiRetry < RETRY_MS) return false;
  lastWiFiRetry = millis();

  Serial.print("WiFi connecting...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(300); Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(); Serial.print("WiFi OK — "); Serial.println(WiFi.localIP());
    lastMqttRetry = 0;
    return true;
  }
  Serial.println(" FAILED");
  return false;
}

void connectMQTT() {
  if (mqtt.connected()) return;
  if (millis() - lastMqttRetry < RETRY_MS) return;
  lastMqttRetry = millis();

  Serial.print("MQTT connecting...");
  if (mqtt.connect(MQTT_ID, TOPIC_STATUS, 0, false, "{\"status\":\"offline\"}")) {
    Serial.println(" OK");
    mqtt.subscribe(TOPIC_SET);
  } else {
    Serial.print(" FAILED rc="); Serial.println(mqtt.state());
  }
}

// ==================== SETUP ====================

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== Bridge ESP-NOW → MQTT v3 ===");

  WiFi.mode(WIFI_STA);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.setSleep(false);
  connectWiFi();

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  connectMQTT();

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init FAILED");
    return;
  }
  esp_now_register_recv_cb(onRecv);

  esp_now_peer_info_t peer;
  memset(&peer, 0, sizeof(peer));
  memcpy(peer.peer_addr, gardenMAC, 6);
  peer.channel = 0;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) == ESP_OK) {
    Serial.println("Garden peer added.");
  } else {
    Serial.println("Failed to add garden peer.");
  }

  Serial.println("Ready.\n");
}

void loop() {
  connectWiFi();
  connectMQTT();
  mqtt.loop();
  delay(100);
}
