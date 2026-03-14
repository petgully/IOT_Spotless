/**
 * =============================================================================
 * ESP32 Node 1 - Configuration - Project Spotless
 * =============================================================================
 * IMPORTANT: Edit WiFi and MQTT settings before uploading!
 * 
 * Relay Configuration (7 Relays):
 *   Relay 1: S1 (220V)    - GPIO 9   - No LED link
 *   Relay 2: P1&P2        - GPIO 10  - No LED link
 *   Relay 3: FP1          - GPIO 11  - Linked to LED_SHAMPOO (GPIO 37)
 *   Relay 4: RS1&DS2      - GPIO 12  - Linked to LED_WATER (GPIO 38)
 *   Relay 5: RS2&DS1      - GPIO 13  - Linked to LED_RESETCLEAN (GPIO 39)
 *   Relay 6: BACK1        - GPIO 14  - Linked to PRE-MIX1 (GPIO 40)
 *   Relay 7: BACK2        - GPIO 21  - Linked to PRE-MIX2 (GPIO 42)
 * 
 * LED Indicator Pins:
 *   LED_SHAMPOO     - GPIO 37  (mirrors FP1)
 *   LED_WATER       - GPIO 38  (mirrors RS1&DS2)
 *   LED_RESETCLEAN  - GPIO 39  (mirrors RS2&DS1)
 *   PRE-MIX1        - GPIO 40  (mirrors BACK1)
 *   PRE-MIX2        - GPIO 42  (mirrors BACK2)
 * =============================================================================
 */

#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
// WiFi Configuration
// =============================================================================
#define WIFI_SSID     "ACT-ai_101776422204"    // Change this!
#define WIFI_PASSWORD "88324738"   // Upated!

// =============================================================================
// MQTT Configuration
// =============================================================================
// IP address of Raspberry Pi running the MQTT broker
#define MQTT_BROKER   "192.168.0.16"         // Raspberry Pi IP - Change this!
#define MQTT_PORT     1883

// Unique identifier for this ESP32 node
#define NODE_ID       "spotless_node1"

// MQTT Topics
#define TOPIC_BASE    "spotless/nodes"

// =============================================================================
// Relay Configuration - 7 Relays per Node
// =============================================================================
#define RELAY_COUNT   7

// GPIO Pin Assignments for Relays (from schematic)
#define RELAY_1_PIN   9     // S1 (220V Solenoid) - No LED
#define RELAY_2_PIN   10    // P1&P2 (Pumps) - No LED
#define RELAY_3_PIN   11    // FP1 (Flow Pump 1) - LED: LED_SHAMPOO
#define RELAY_4_PIN   12    // RS1&DS2 - LED: LED_WATER
#define RELAY_5_PIN   13    // RS2&DS1 - LED: LED_RESETCLEAN
#define RELAY_6_PIN   14    // BACK1 - LED: PRE-MIX1
#define RELAY_7_PIN   21    // BACK2 - LED: PRE-MIX2

// =============================================================================
// LED Indicator Configuration - Linked to Relays
// =============================================================================
#define LED_COUNT     5

// LED GPIO Pins (from schematic)
#define LED_SHAMPOO_PIN     37    // Mirrors FP1 (Relay 3)
#define LED_WATER_PIN       38    // Mirrors RS1&DS2 (Relay 4)
#define LED_RESETCLEAN_PIN  39    // Mirrors RS2&DS1 (Relay 5)
#define LED_PREMIX1_PIN     40    // Mirrors BACK1 (Relay 6)
#define LED_PREMIX2_PIN     42    // Mirrors BACK2 (Relay 7)

// Relay to LED Mapping
// -1 means no LED linked to that relay
#define RELAY_1_LED   -1              // S1 - No LED
#define RELAY_2_LED   -1              // P1&P2 - No LED
#define RELAY_3_LED   LED_SHAMPOO_PIN     // FP1 → LED_SHAMPOO
#define RELAY_4_LED   LED_WATER_PIN       // RS1&DS2 → LED_WATER
#define RELAY_5_LED   LED_RESETCLEAN_PIN  // RS2&DS1 → LED_RESETCLEAN
#define RELAY_6_LED   LED_PREMIX1_PIN     // BACK1 → PRE-MIX1
#define RELAY_7_LED   LED_PREMIX2_PIN     // BACK2 → PRE-MIX2

// =============================================================================
// Active States
// =============================================================================
// Relay active state
#define RELAY_ACTIVE_STATE HIGH

// LED active state (HIGH = LED ON when GPIO is HIGH)
#define LED_ACTIVE_STATE HIGH

// =============================================================================
// Status LED
// =============================================================================
#define STATUS_LED_PIN 2

// =============================================================================
// Timing Configuration
// =============================================================================
#define STATUS_INTERVAL           30000   // Status update interval (ms)
#define CONNECTION_CHECK_INTERVAL 5000    // Connection check interval (ms)
#define MQTT_RECONNECT_DELAY      5000    // MQTT reconnect delay (ms)

#endif // CONFIG_H
