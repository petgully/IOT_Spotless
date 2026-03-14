"""
=============================================================================
MQTT Client for Raspberry Pi Master Controller - Project Spotless
=============================================================================
Handles MQTT communication with all ESP32 nodes.
Provides methods to send commands and receive status updates.

Topic Structure:
    spotless/nodes/{node_id}/relays/{n}/command  - Send command to relay
    spotless/nodes/{node_id}/relays/{n}/state    - Receive state updates
    spotless/nodes/{node_id}/relays/all/command  - Control all relays
    spotless/nodes/{node_id}/status              - Node status
=============================================================================
"""

import json
import logging
import time
from typing import Callable, Dict, Optional, Any
import paho.mqtt.client as mqtt

from config import (
    MQTT_BROKER_HOST, 
    MQTT_BROKER_PORT, 
    MQTT_CLIENT_ID,
    MQTT_QOS,
    TOPIC_BASE,
    NODES
)

# Setup logging
logger = logging.getLogger(__name__)


class SpotlessMQTTClient:
    """
    MQTT Client for the Spotless master controller.
    Manages communication with all ESP32 nodes.
    """
    
    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.connected = False
        self.node_status: Dict[str, Dict] = {}
        self.callbacks: Dict[str, Callable] = {}
        
        # Setup MQTT callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
    def connect(self) -> bool:
        """Connect to the MQTT broker."""
        try:
            logger.info(f"Connecting to MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
            self.client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
            self.client.loop_start()
            
            # Wait for connection
            timeout = 10
            while not self.connected and timeout > 0:
                time.sleep(0.5)
                timeout -= 0.5
                
            return self.connected
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from the MQTT broker."""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        logger.info("Disconnected from MQTT broker")
        
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker."""
        if rc == 0:
            self.connected = True
            logger.info("Connected to MQTT broker successfully")
            
            # Subscribe to status updates from all nodes
            status_topic = f"{TOPIC_BASE}/+/status"
            self.client.subscribe(status_topic, MQTT_QOS)
            logger.info(f"Subscribed to: {status_topic}")
            
            # Subscribe to state updates from all nodes
            state_topic = f"{TOPIC_BASE}/+/relays/+/state"
            self.client.subscribe(state_topic, MQTT_QOS)
            logger.info(f"Subscribed to: {state_topic}")
            
        else:
            logger.error(f"Failed to connect to MQTT broker (rc={rc})")
            
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker."""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker (rc={rc})")
        else:
            logger.info("Disconnected from MQTT broker")
            
    def _on_message(self, client, userdata, msg):
        """Callback when a message is received."""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            logger.debug(f"Received [{topic}]: {payload}")
            
            # Parse status messages
            if "/status" in topic:
                self._handle_status_message(topic, payload)
                
            # Parse state messages
            elif "/state" in topic:
                self._handle_state_message(topic, payload)
                
            # Call any registered callbacks
            for pattern, callback in self.callbacks.items():
                if pattern in topic:
                    callback(topic, payload)
                    
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            
    def _handle_status_message(self, topic: str, payload: str):
        """Handle status update from a node."""
        try:
            status = json.loads(payload)
            node_id = status.get("node_id")
            
            if node_id:
                self.node_status[node_id] = {
                    "online": status.get("online", False),
                    "ip": status.get("ip"),
                    "rssi": status.get("rssi"),
                    "uptime": status.get("uptime"),
                    "relay_count": status.get("relay_count"),
                    "last_update": time.time()
                }
                logger.info(f"Status update from {node_id}: online={status.get('online')}")
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in status message: {payload}")
            
    def _handle_state_message(self, topic: str, payload: str):
        """Handle state update from a node relay."""
        try:
            # Parse topic: spotless/nodes/{node_id}/relays/{num}/state
            parts = topic.split("/")
            if len(parts) >= 5:
                node_id = parts[2]
                relay_num = parts[4]
                
                state_data = json.loads(payload)
                state = state_data.get("state", "OFF")
                label = state_data.get("label", "")
                
                logger.debug(f"State update: {node_id} relay {relay_num} ({label}) = {state}")
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in state message: {payload}")
            
    def set_relay(self, node_id: str, relay_num: int, state: bool) -> bool:
        """
        Set the state of a specific relay on a node.
        
        Args:
            node_id: The node identifier (e.g., "spotless_node1")
            relay_num: The relay number (1-7)
            state: True for ON, False for OFF
            
        Returns:
            True if command was sent successfully
        """
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return False
            
        topic = f"{TOPIC_BASE}/{node_id}/relays/{relay_num}/command"
        payload = json.dumps({"state": "ON" if state else "OFF"})
        
        result = self.client.publish(topic, payload, qos=MQTT_QOS)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Command sent: {node_id} relay {relay_num} = {'ON' if state else 'OFF'}")
            return True
        else:
            logger.error(f"Failed to send command (rc={result.rc})")
            return False
            
    def set_all_relays(self, node_id: str, state: bool) -> bool:
        """
        Set all relays on a node to the same state.
        
        Args:
            node_id: The node identifier
            state: True for ON, False for OFF
            
        Returns:
            True if command was sent successfully
        """
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return False
            
        topic = f"{TOPIC_BASE}/{node_id}/relays/all/command"
        payload = json.dumps({"state": "ON" if state else "OFF"})
        
        result = self.client.publish(topic, payload, qos=MQTT_QOS)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Command sent: {node_id} ALL relays = {'ON' if state else 'OFF'}")
            return True
        else:
            logger.error(f"Failed to send command (rc={result.rc})")
            return False
            
    def request_status(self, node_id: str) -> bool:
        """Request status update from a node."""
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return False
            
        topic = f"{TOPIC_BASE}/{node_id}/request"
        payload = json.dumps({"command": "status"})
        
        result = self.client.publish(topic, payload, qos=MQTT_QOS)
        return result.rc == mqtt.MQTT_ERR_SUCCESS
        
    def get_node_status(self, node_id: str) -> Optional[Dict]:
        """Get the latest status of a node."""
        return self.node_status.get(node_id)
        
    def get_all_node_status(self) -> Dict[str, Dict]:
        """Get status of all nodes."""
        return self.node_status.copy()
        
    def is_node_online(self, node_id: str, timeout: int = 60) -> bool:
        """
        Check if a node is online (received status within timeout).
        
        Args:
            node_id: The node identifier
            timeout: Seconds since last status update to consider node offline
            
        Returns:
            True if node is online
        """
        status = self.node_status.get(node_id)
        if not status:
            return False
            
        last_update = status.get("last_update", 0)
        return (time.time() - last_update) < timeout
        
    def register_callback(self, topic_pattern: str, callback: Callable):
        """Register a callback for messages matching a topic pattern."""
        self.callbacks[topic_pattern] = callback
        logger.debug(f"Registered callback for pattern: {topic_pattern}")
        
    def unregister_callback(self, topic_pattern: str):
        """Unregister a callback."""
        if topic_pattern in self.callbacks:
            del self.callbacks[topic_pattern]
            logger.debug(f"Unregistered callback for pattern: {topic_pattern}")
