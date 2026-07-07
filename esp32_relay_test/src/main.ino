static const int MIN_GPIO = 0;
static const int MAX_GPIO = 21;
static const int BLACKLIST[] = {8, 9, 18, 19};
static const int BLACKLIST_COUNT = sizeof(BLACKLIST) / sizeof(BLACKLIST[0]);

static const bool RELAY_ACTIVE_LOW = false;
static const unsigned long STATUS_INTERVAL = 60000;

static bool relayStates[MAX_GPIO + 1] = {false};
static bool pinConfigured[MAX_GPIO + 1] = {false};
unsigned long lastStatus = 0;

bool isBlacklisted(int pin) {
  for (int i = 0; i < BLACKLIST_COUNT; i++)
    if (BLACKLIST[i] == pin) return true;
  return false;
}

void configurePin(int pin) {
  if (pinConfigured[pin]) return;
  pinMode(pin, OUTPUT);
  pinConfigured[pin] = true;
}

void setRelay(int pin, bool on) {
  relayStates[pin] = on;
  digitalWrite(pin, (RELAY_ACTIVE_LOW ? !on : on) ? HIGH : LOW);
}

bool parseCmd(const char* json, int* pin, bool* state) {
  const char* p = strstr(json, "\"pin\"");
  if (!p) return false;
  p = strchr(p, ':'); if (!p) return false;
  *pin = atoi(p + 1);
  p = strstr(json, "\"state\"");
  if (!p) return false;
  p = strchr(p, ':'); if (!p) return false;
  *state = atoi(p + 1) != 0;
  return true;
}

void sendLine(const char* json) { Serial.println(json); }

void sendState(int pin, bool on) {
  char buf[64];
  snprintf(buf, sizeof(buf), "{\"type\":\"state\",\"pin\":%d,\"state\":%d}", pin, on);
  sendLine(buf);
}

void sendStatus() {
  char buf[320];
  int pos = snprintf(buf, sizeof(buf),
    "{\"type\":\"status\",\"uptime\":%lu,\"relays\":{", millis() / 1000);

  bool first = true;
  for (int p = MIN_GPIO; p <= MAX_GPIO; p++) {
    if (isBlacklisted(p)) continue;
    if (!pinConfigured[p]) continue;
    if (!first) { buf[pos++] = ','; }
    pos += snprintf(buf + pos, sizeof(buf) - pos, "\"%d\":%d", p, relayStates[p]);
    first = false;
  }
  pos += snprintf(buf + pos, sizeof(buf) - pos, "}}");
  sendLine(buf);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== Garden USB v5 (dynamic GPIO) ===");

  lastStatus = millis();
  Serial.println("Ready");
}

void loop() {
  static String buffer = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      buffer.trim();
      if (buffer.length() > 0) {
        int pin; bool state;
        if (parseCmd(buffer.c_str(), &pin, &state)) {
          if (pin >= MIN_GPIO && pin <= MAX_GPIO && !isBlacklisted(pin)) {
            configurePin(pin);
            setRelay(pin, state);
            sendState(pin, state);
          }
        }
      }
      buffer = "";
    } else {
      buffer += c;
    }
  }

  unsigned long now = millis();
  if (now - lastStatus >= STATUS_INTERVAL) {
    lastStatus = now;
    sendStatus();
  }

  delay(10);
}
