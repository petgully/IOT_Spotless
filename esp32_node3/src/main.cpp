/**
 * =============================================================================
 * ESP32 Node 3 - Main Program - Project Spotless
 * =============================================================================
 * This program runs on the ESP32 and:
 * 1. Connects to WiFi
 * 2. Connects to the Raspberry Pi MQTT broker
 * 3. Listens for relay control commands
 * 4. Controls relay outputs based on received commands
 * 5. Controls linked LED indicators when relays are toggled
 * 6. Reports relay states back to the Raspberry Pi
 * 
 * Relay Configuration (7 Relays) with LED Links:
 *   Relay 1: S1 (220V)    - GPIO 9   - No LED
 *   Relay 2: P1&P2        - GPIO 10  - No LED
 *   Relay 3: FP1          - GPIO 11  → LED_SHAMPOO (GPIO 37)
 *   Relay 4: RS1&DS2      - GPIO 12  → LED_WATER (GPIO 38)
 *   Relay 5: RS2&DS1      - GPIO 13  → LED_RESETCLEAN (GPIO 39)
 *   Relay 6: BACK1        - GPIO 14  → PRE-MIX1 (GPIO 40)
 *   Relay 7: BACK2        - GPIO 21  → PRE-MIX2 (GPIO 42)
 * 
 * MQTT Topics:
 *   Subscribe: spotless/nodes/{NODE_ID}/relays/{n}/command
 *   Publish:   spotless/nodes/{NODE_ID}/relays/{n}/state
 *   Publish:   spotless/nodes/{NODE_ID}/status
 * 
 * =============================================================================
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "config.h"

// =============================================================================
// Global Variables
// =============================================================================

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// Relay GPIO pins array (for easy iteration)
const int relayPins[RELAY_COUNT] = {
    RELAY_1_PIN,   // 9  - S1 (220V)
    RELAY_2_PIN,   // 10 - P1&P2
    RELAY_3_PIN,   // 11 - FP1
    RELAY_4_PIN,   // 12 - RS1&DS2
    RELAY_5_PIN,   // 13 - RS2&DS1
    RELAY_6_PIN,   // 14 - BACK1
    RELAY_7_PIN    // 21 - BACK2
};

// LED pins linked to each relay (-1 = no LED linked)
const int relayLedPins[RELAY_COUNT] = {
    RELAY_1_LED,   // -1 - S1 has no LED
    RELAY_2_LED,   // -1 - P1&P2 has no LED
    RELAY_3_LED,   // 37 - FP1 → LED_SHAMPOO
    RELAY_4_LED,   // 38 - RS1&DS2 → LED_WATER
    RELAY_5_LED,   // 39 - RS2&DS1 → LED_RESETCLEAN
    RELAY_6_LED,   // 40 - BACK1 → PRE-MIX1
    RELAY_7_LED    // 42 - BACK2 → PRE-MIX2
};

// Relay labels for debugging and state reporting
const char* relayLabels[RELAY_COUNT] = {
    "S1_220V",
    "P1_P2",
    "FP1",
    "RS1_DS2",
    "RS2_DS1",
    "BACK1",
    "BACK2"
};

// LED labels for debugging
const char* ledLabels[RELAY_COUNT] = {
    "NONE",
    "NONE",
    "LED_SHAMPOO",
    "LED_WATER",
    "LED_RESETCLEAN",
    "PRE-MIX1",
    "PRE-MIX2"
};

// Relay states (true = ON, false = OFF)
bool relayStates[RELAY_COUNT] = {false, false, false, false, false, false, false};

// Timing variables
unsigned long lastStatusUpdate = 0;
unsigned long lastConnectionCheck = 0;

// =============================================================================
// Function Prototypes
// =============================================================================

void setupWiFi();
void setupMQTT();
void reconnectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void setupRelays();
void setupLeds();
void setRelay(int relayNum, bool state);
void setAllRelays(bool state);
void setLinkedLed(int relayIndex, bool state);
void publishRelayState(int relayNum);
void publishStatus();
void subscribeToTopics();
void blinkLED(int times, int delayMs);

// =============================================================================
// Setup
// =============================================================================

void setup() {
    // Initialize Serial for debugging
    Serial.begin(115200);
    delay(1000);
    
    Serial.println();
    Serial.println("===========================================");
    Serial.println("   Project Spotless - ESP32 Node 3");
    Serial.println("===========================================");
    Serial.printf("Node ID: %s\n", NODE_ID);
    Serial.printf("Relay Count: %d\n", RELAY_COUNT);
    Serial.println("Relay to LED Mapping:");
    for (int i = 0; i < RELAY_COUNT; i++) {
        if (relayLedPins[i] >= 0) {
            Serial.printf("  Relay %d (%s) GPIO %d → %s GPIO %d\n", 
                         i + 1, relayLabels[i], relayPins[i], 
                         ledLabels[i], relayLedPins[i]);
        } else {
            Serial.printf("  Relay %d (%s) GPIO %d → No LED\n", 
                         i + 1, relayLabels[i], relayPins[i]);
        }
    }
    Serial.println("===========================================");
    
    // Initialize status LED
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, LOW);
    
    // Initialize relays
    setupRelays();
    
    // Initialize LEDs
    setupLeds();
    
    // Connect to WiFi
    setupWiFi();
    
    // Setup MQTT
    setupMQTT();
    
    Serial.println("Setup complete!");
    blinkLED(3, 200);  // Signal ready
}

// =============================================================================
// Main Loop
// =============================================================================

void loop() {
    // Ensure MQTT is connected
    if (!mqttClient.connected()) {
        reconnectMQTT();
    }
    
    // Process MQTT messages
    mqttClient.loop();
    
    // Periodic status update
    unsigned long now = millis();
    if (now - lastStatusUpdate >= STATUS_INTERVAL) {
        lastStatusUpdate = now;
        publishStatus();
        
        // Also publish all relay states
        for (int i = 0; i < RELAY_COUNT; i++) {
            publishRelayState(i + 1);
        }
    }
    
    // Brief delay to prevent watchdog issues
    delay(10);
}

// =============================================================================
// WiFi Functions
// =============================================================================

void setupWiFi() {
    Serial.printf("Connecting to WiFi: %s", WIFI_SSID);
    
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN));  // Blink while connecting
        attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println(" Connected!");
        Serial.printf("IP Address: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("Signal Strength (RSSI): %d dBm\n", WiFi.RSSI());
        digitalWrite(STATUS_LED_PIN, HIGH);  // Solid LED when connected
    } else {
        Serial.println(" FAILED!");
        Serial.println("Restarting in 5 seconds...");
        delay(5000);
        ESP.restart();
    }
}

// =============================================================================
// MQTT Functions
// =============================================================================

void setupMQTT() {
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setBufferSize(512);  // Increase buffer for JSON messages
    
    Serial.printf("MQTT Broker: %s:%d\n", MQTT_BROKER, MQTT_PORT);
}

void reconnectMQTT() {
    while (!mqttClient.connected()) {
        Serial.print("Connecting to MQTT broker...");
        
        // Create client ID
        String clientId = "ESP32_";
        clientId += NODE_ID;
        
        // Last Will and Testament (LWT) - sent when disconnected unexpectedly
        String statusTopic = String(TOPIC_BASE) + "/" + NODE_ID + "/status";
        String offlineMsg = "{\"online\":false}";
        
        if (mqttClient.connect(clientId.c_str(), statusTopic.c_str(), 1, true, offlineMsg.c_str())) {
            Serial.println(" Connected!");
            
            // Subscribe to command topics
            subscribeToTopics();
            
            // Publish online status
            publishStatus();
            
            // Publish current relay states
            for (int i = 0; i < RELAY_COUNT; i++) {
                publishRelayState(i + 1);
            }
            
            digitalWrite(STATUS_LED_PIN, HIGH);
        } else {
            Serial.printf(" Failed (rc=%d)\n", mqttClient.state());
            Serial.printf("Retrying in %d seconds...\n", MQTT_RECONNECT_DELAY / 1000);
            digitalWrite(STATUS_LED_PIN, LOW);
            delay(MQTT_RECONNECT_DELAY);
        }
    }
}

void subscribeToTopics() {
    // Subscribe to command topics for each relay
    for (int i = 1; i <= RELAY_COUNT; i++) {
        String topic = String(TOPIC_BASE) + "/" + NODE_ID + "/relays/" + i + "/command";
        mqttClient.subscribe(topic.c_str(), 1);  // QoS 1
        Serial.printf("Subscribed to: %s\n", topic.c_str());
    }
    
    // Subscribe to general request topic (for status requests)
    String requestTopic = String(TOPIC_BASE) + "/" + NODE_ID + "/request";
    mqttClient.subscribe(requestTopic.c_str(), 1);
    Serial.printf("Subscribed to: %s\n", requestTopic.c_str());
    
    // Subscribe to "all" command topic (control all relays at once)
    String allTopic = String(TOPIC_BASE) + "/" + NODE_ID + "/relays/all/command";
    mqttClient.subscribe(allTopic.c_str(), 1);
    Serial.printf("Subscribed to: %s\n", allTopic.c_str());
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    // Convert payload to string
    char message[length + 1];
    memcpy(message, payload, length);
    message[length] = '\0';
    
    Serial.printf("Message received on topic: %s\n", topic);
    Serial.printf("Payload: %s\n", message);
    
    // Parse JSON payload
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, message);
    
    if (error) {
        Serial.printf("JSON parse error: %s\n", error.c_str());
        return;
    }
    
    String topicStr = String(topic);
    
    // Handle "all" relay command
    if (topicStr.indexOf("/relays/all/command") > 0) {
        const char* stateStr = doc["state"];
        if (stateStr) {
            bool newState = (String(stateStr) == "ON");
            setAllRelays(newState);
        }
        return;
    }
    
    // Handle individual relay commands
    // Topic format: spotless/nodes/{NODE_ID}/relays/{n}/command
    if (topicStr.indexOf("/relays/") > 0 && topicStr.endsWith("/command")) {
        // Extract relay number from topic
        int relayStart = topicStr.indexOf("/relays/") + 8;
        int relayEnd = topicStr.indexOf("/command");
        String relayNumStr = topicStr.substring(relayStart, relayEnd);
        int relayNum = relayNumStr.toInt();
        
        if (relayNum >= 1 && relayNum <= RELAY_COUNT) {
            // Get state from JSON
            const char* stateStr = doc["state"];
            if (stateStr) {
                bool newState = (String(stateStr) == "ON");
                setRelay(relayNum, newState);
            }
        } else {
            Serial.printf("Invalid relay number: %d\n", relayNum);
        }
    }
    
    // Handle status request
    else if (topicStr.endsWith("/request")) {
        const char* command = doc["command"];
        if (command && String(command) == "status") {
            publishStatus();
            for (int i = 0; i < RELAY_COUNT; i++) {
                publishRelayState(i + 1);
            }
        }
    }
}

void publishStatus() {
    String topic = String(TOPIC_BASE) + "/" + NODE_ID + "/status";
    
    JsonDocument doc;
    doc["online"] = true;
    doc["ip"] = WiFi.localIP().toString();
    doc["rssi"] = WiFi.RSSI();
    doc["node_id"] = NODE_ID;
    doc["relay_count"] = RELAY_COUNT;
    doc["uptime"] = millis() / 1000;
    
    String output;
    serializeJson(doc, output);
    
    mqttClient.publish(topic.c_str(), output.c_str(), true);  // Retained message
    Serial.printf("Published status to: %s\n", topic.c_str());
}

void publishRelayState(int relayNum) {
    if (relayNum < 1 || relayNum > RELAY_COUNT) return;
    
    int index = relayNum - 1;
    String topic = String(TOPIC_BASE) + "/" + NODE_ID + "/relays/" + relayNum + "/state";
    
    JsonDocument doc;
    doc["state"] = relayStates[index] ? "ON" : "OFF";
    doc["relay"] = relayNum;
    doc["label"] = relayLabels[index];
    doc["gpio"] = relayPins[index];
    doc["led_gpio"] = relayLedPins[index];
    doc["led_label"] = ledLabels[index];
    doc["timestamp"] = millis();
    
    String output;
    serializeJson(doc, output);
    
    mqttClient.publish(topic.c_str(), output.c_str(), true);  // Retained message
    Serial.printf("Relay %d (%s): %s", relayNum, relayLabels[index], relayStates[index] ? "ON" : "OFF");
    if (relayLedPins[index] >= 0) {
        Serial.printf(" → LED %s\n", ledLabels[index]);
    } else {
        Serial.println();
    }
}

// =============================================================================
// Relay Functions
// =============================================================================

void setupRelays() {
    Serial.println("Initializing relays...");
    
    for (int i = 0; i < RELAY_COUNT; i++) {
        pinMode(relayPins[i], OUTPUT);
        
        // Initialize all relays to OFF state
        if (RELAY_ACTIVE_STATE == LOW) {
            digitalWrite(relayPins[i], HIGH);  // Active LOW: HIGH = OFF
        } else {
            digitalWrite(relayPins[i], LOW);   // Active HIGH: LOW = OFF
        }
        
        relayStates[i] = false;
        Serial.printf("  Relay %d: GPIO %d (%s) - OFF\n", i + 1, relayPins[i], relayLabels[i]);
    }
    
    Serial.println("All relays initialized to OFF state");
}

void setupLeds() {
    Serial.println("Initializing linked LEDs...");
    
    for (int i = 0; i < RELAY_COUNT; i++) {
        if (relayLedPins[i] >= 0) {
            pinMode(relayLedPins[i], OUTPUT);
            
            // Initialize LED to OFF state
            if (LED_ACTIVE_STATE == HIGH) {
                digitalWrite(relayLedPins[i], LOW);   // Active HIGH: LOW = OFF
            } else {
                digitalWrite(relayLedPins[i], HIGH);  // Active LOW: HIGH = OFF
            }
            
            Serial.printf("  LED %s: GPIO %d - OFF (linked to %s)\n", 
                         ledLabels[i], relayLedPins[i], relayLabels[i]);
        }
    }
    
    Serial.println("All linked LEDs initialized to OFF state");
}

void setLinkedLed(int relayIndex, bool state) {
    // Check if this relay has a linked LED
    if (relayIndex < 0 || relayIndex >= RELAY_COUNT) return;
    
    int ledPin = relayLedPins[relayIndex];
    if (ledPin < 0) return;  // No LED linked to this relay
    
    // Set the LED state to match the relay state
    if (LED_ACTIVE_STATE == HIGH) {
        digitalWrite(ledPin, state ? HIGH : LOW);
    } else {
        digitalWrite(ledPin, state ? LOW : HIGH);
    }
    
    Serial.printf("  → LED %s (GPIO %d): %s\n", ledLabels[relayIndex], ledPin, state ? "ON" : "OFF");
}

void setRelay(int relayNum, bool state) {
    if (relayNum < 1 || relayNum > RELAY_COUNT) {
        Serial.printf("Invalid relay number: %d\n", relayNum);
        return;
    }
    
    int index = relayNum - 1;
    int pin = relayPins[index];
    
    // Set the relay
    if (RELAY_ACTIVE_STATE == LOW) {
        digitalWrite(pin, state ? LOW : HIGH);  // Active LOW
    } else {
        digitalWrite(pin, state ? HIGH : LOW);  // Active HIGH
    }
    
    relayStates[index] = state;
    
    Serial.printf("Relay %d (%s) GPIO %d: %s\n", relayNum, relayLabels[index], pin, state ? "ON" : "OFF");
    
    // Set the linked LED to mirror the relay state
    setLinkedLed(index, state);
    
    // Publish the new state
    publishRelayState(relayNum);
}

void setAllRelays(bool state) {
    Serial.printf("Setting ALL relays to: %s\n", state ? "ON" : "OFF");
    for (int i = 1; i <= RELAY_COUNT; i++) {
        setRelay(i, state);
        delay(50);  // Small delay between relays
    }
}

// =============================================================================
// Utility Functions
// =============================================================================

void blinkLED(int times, int delayMs) {
    for (int i = 0; i < times; i++) {
        digitalWrite(STATUS_LED_PIN, HIGH);
        delay(delayMs);
        digitalWrite(STATUS_LED_PIN, LOW);
        delay(delayMs);
    }
}
