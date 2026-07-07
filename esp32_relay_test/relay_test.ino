// ESP32-C3 Relay Test Sketch
// Adjust RELAY_PINS to the actual GPIO numbers for your board.
// Set RELAY_ACTIVE_LOW to true if your relay module activates when the pin is LOW.
// SENSE_PIN monitors an external voltage; when it reads HIGH all relays will be forced ON.
// SAFETY: Do NOT connect 5V directly to the ESP32 GPIO. Use a proper voltage divider
// or optocoupler to bring the sense voltage to 3.3V.

const int RELAY_PINS[] = {1, 2, 3}; // <-- change these to your GPIO numbers
const bool RELAY_ACTIVE_LOW = true; // true if relays are active LOW
const int RELAY_COUNT = sizeof(RELAY_PINS) / sizeof(RELAY_PINS[0]);

const int SENSE_PIN = 21; // when this pin reads HIGH, all relays will be ON
const bool SENSE_ACTIVE_HIGH = true; // set to false if sense is active LOW

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("Relay test starting...");
  // configure relay pins
  for (int i = 0; i < RELAY_COUNT; ++i) {
    pinMode(RELAY_PINS[i], OUTPUT);
    // ensure relays start OFF
    digitalWrite(RELAY_PINS[i], RELAY_ACTIVE_LOW ? HIGH : LOW);
  }
  // configure sense pin with pull-down so default is LOW
  pinMode(SENSE_PIN, INPUT_PULLDOWN);
}

void setAllRelays(bool on) {
  for (int i = 0; i < RELAY_COUNT; ++i) {
    digitalWrite(RELAY_PINS[i], on ? (RELAY_ACTIVE_LOW ? LOW : HIGH) : (RELAY_ACTIVE_LOW ? HIGH : LOW));
  }
}

void loop() {
  int sense = digitalRead(SENSE_PIN);
  bool senseOn = (sense == HIGH) == SENSE_ACTIVE_HIGH;

  if (senseOn) {
    Serial.println("Sense HIGH — forcing all relays ON");
    setAllRelays(true);
    delay(200);
    return;
  }

  // Sense is LOW — ensure all relays are OFF
  setAllRelays(false);
  delay(200);
}
