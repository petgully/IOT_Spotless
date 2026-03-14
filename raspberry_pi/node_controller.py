"""
=============================================================================
Node Controller for Raspberry Pi Master - Project Spotless
=============================================================================
High-level controller for managing ESP32 nodes and their relays.
Provides abstracted methods for controlling the Spotless system.

Relay Configuration (7 Relays per Node):
    Relay 1: S1 (220V)    - GPIO 9   - 220V Solenoid
    Relay 2: P1&P2        - GPIO 10  - Pumps
    Relay 3: FP1          - GPIO 11  - Flow Pump 1
    Relay 4: RS1&DS2      - GPIO 12  - RO Solenoid 1 & Diaphragm Solenoid 2
    Relay 5: RS2&DS1      - GPIO 13  - RO Solenoid 2 & Diaphragm Solenoid 1
    Relay 6: BACK1        - GPIO 14  - Backflow 1
    Relay 7: BACK2        - GPIO 21  - Backflow 2
=============================================================================
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from mqtt_client import SpotlessMQTTClient
from config import NODES, RELAY_LABELS, RELAY_CONFIG, Relay

# Setup logging
logger = logging.getLogger(__name__)


class NodeState(Enum):
    """Node connection states."""
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass
class RelayState:
    """Represents the state of a single relay."""
    node_id: str
    relay_num: int
    state: bool
    label: str = ""
    last_changed: float = 0


class NodeController:
    """
    High-level controller for all ESP32 nodes in the Spotless system.
    """
    
    # Relay constants for easy access
    S1_220V = Relay.S1_220V
    P1_P2 = Relay.P1_P2
    FP1 = Relay.FP1
    RS1_DS2 = Relay.RS1_DS2
    RS2_DS1 = Relay.RS2_DS1
    BACK1 = Relay.BACK1
    BACK2 = Relay.BACK2
    
    def __init__(self):
        self.mqtt = SpotlessMQTTClient()
        self.nodes = NODES
        self.relay_labels = RELAY_LABELS
        self.relay_config = RELAY_CONFIG
        self._relay_states: Dict[str, Dict[int, RelayState]] = {}
        
        # Initialize relay state tracking
        for node_id in self.nodes:
            self._relay_states[node_id] = {}
            
    def start(self) -> bool:
        """Start the controller and connect to MQTT."""
        logger.info("Starting Node Controller...")
        
        if not self.mqtt.connect():
            logger.error("Failed to connect to MQTT broker")
            return False
            
        logger.info("Node Controller started successfully")
        return True
        
    def stop(self):
        """Stop the controller and disconnect from MQTT."""
        logger.info("Stopping Node Controller...")
        self.mqtt.disconnect()
        
    def get_node_state(self, node_id: str) -> NodeState:
        """Get the current state of a node."""
        if node_id not in self.nodes:
            return NodeState.UNKNOWN
            
        if self.mqtt.is_node_online(node_id):
            return NodeState.ONLINE
        else:
            return NodeState.OFFLINE
            
    def get_all_node_states(self) -> Dict[str, NodeState]:
        """Get states of all configured nodes."""
        states = {}
        for node_id in self.nodes:
            states[node_id] = self.get_node_state(node_id)
        return states
        
    def set_relay(self, node_id: str, relay_num: int, state: bool) -> bool:
        """
        Set a specific relay on a node.
        
        Args:
            node_id: Node identifier (e.g., "spotless_node1")
            relay_num: Relay number (1-7)
            state: True for ON, False for OFF
            
        Returns:
            True if successful
        """
        if node_id not in self.nodes:
            logger.error(f"Unknown node: {node_id}")
            return False
            
        max_relays = self.nodes[node_id].get("relay_count", 7)
        if relay_num < 1 or relay_num > max_relays:
            logger.error(f"Invalid relay number {relay_num} for {node_id}")
            return False
            
        success = self.mqtt.set_relay(node_id, relay_num, state)
        
        if success:
            # Update local state tracking
            label = self.relay_labels.get(node_id, {}).get(relay_num, "")
            self._relay_states[node_id][relay_num] = RelayState(
                node_id=node_id,
                relay_num=relay_num,
                state=state,
                label=label,
                last_changed=time.time()
            )
            
        return success
        
    def set_relay_by_label(self, node_id: str, label: str, state: bool) -> bool:
        """
        Set a relay by its label name.
        
        Args:
            node_id: Node identifier
            label: Relay label (e.g., "S1_220V", "P1_P2")
            state: True for ON, False for OFF
            
        Returns:
            True if successful
        """
        labels = self.relay_labels.get(node_id, {})
        for relay_num, relay_label in labels.items():
            if relay_label == label:
                return self.set_relay(node_id, relay_num, state)
                
        logger.error(f"Label '{label}' not found on {node_id}")
        return False
        
    def set_all_relays(self, node_id: str, state: bool) -> bool:
        """Set all relays on a node to the same state."""
        if node_id not in self.nodes:
            logger.error(f"Unknown node: {node_id}")
            return False
            
        return self.mqtt.set_all_relays(node_id, state)
        
    def all_off(self) -> bool:
        """Turn off all relays on all nodes (emergency stop)."""
        logger.warning("ALL OFF - Turning off all relays on all nodes")
        success = True
        
        for node_id in self.nodes:
            if not self.mqtt.set_all_relays(node_id, False):
                success = False
                
        return success
        
    def pulse_relay(self, node_id: str, relay_num: int, duration: float) -> bool:
        """
        Pulse a relay ON for a specified duration, then OFF.
        
        Args:
            node_id: Node identifier
            relay_num: Relay number
            duration: Duration in seconds
            
        Returns:
            True if successful
        """
        if not self.set_relay(node_id, relay_num, True):
            return False
            
        time.sleep(duration)
        return self.set_relay(node_id, relay_num, False)
        
    def toggle_relays(self, node_id: str, relay_nums: List[int], state: bool) -> bool:
        """
        Set multiple relays to the same state.
        
        Args:
            node_id: Node identifier
            relay_nums: List of relay numbers
            state: True for ON, False for OFF
            
        Returns:
            True if all successful
        """
        success = True
        for relay_num in relay_nums:
            if not self.set_relay(node_id, relay_num, state):
                success = False
        return success
        
    # -------------------------------------------------------------------------
    # Convenience Methods for Specific Relays
    # -------------------------------------------------------------------------
    
    def set_s1_220v(self, node_id: str, state: bool) -> bool:
        """Control S1 (220V Solenoid) relay."""
        return self.set_relay(node_id, Relay.S1_220V, state)
        
    def set_pumps(self, node_id: str, state: bool) -> bool:
        """Control P1&P2 (Pumps) relay."""
        return self.set_relay(node_id, Relay.P1_P2, state)
        
    def set_flow_pump(self, node_id: str, state: bool) -> bool:
        """Control FP1 (Flow Pump 1) relay."""
        return self.set_relay(node_id, Relay.FP1, state)
        
    def set_rs1_ds2(self, node_id: str, state: bool) -> bool:
        """Control RS1&DS2 relay."""
        return self.set_relay(node_id, Relay.RS1_DS2, state)
        
    def set_rs2_ds1(self, node_id: str, state: bool) -> bool:
        """Control RS2&DS1 relay."""
        return self.set_relay(node_id, Relay.RS2_DS1, state)
        
    def set_back1(self, node_id: str, state: bool) -> bool:
        """Control BACK1 (Backflow 1) relay."""
        return self.set_relay(node_id, Relay.BACK1, state)
        
    def set_back2(self, node_id: str, state: bool) -> bool:
        """Control BACK2 (Backflow 2) relay."""
        return self.set_relay(node_id, Relay.BACK2, state)
        
    # -------------------------------------------------------------------------
    # Status and Info Methods
    # -------------------------------------------------------------------------
        
    def get_relay_state(self, node_id: str, relay_num: int) -> Optional[RelayState]:
        """Get the current state of a relay."""
        return self._relay_states.get(node_id, {}).get(relay_num)
        
    def get_node_info(self, node_id: str) -> Optional[Dict]:
        """Get configuration info for a node."""
        if node_id not in self.nodes:
            return None
            
        info = self.nodes[node_id].copy()
        info["state"] = self.get_node_state(node_id).value
        info["status"] = self.mqtt.get_node_status(node_id)
        return info
        
    def list_nodes(self) -> List[Dict]:
        """List all configured nodes with their states."""
        nodes_list = []
        for node_id, config in self.nodes.items():
            nodes_list.append({
                "id": node_id,
                "name": config.get("name"),
                "state": self.get_node_state(node_id).value,
                "relay_count": config.get("relay_count", 7),
                "description": config.get("description")
            })
        return nodes_list
        
    def list_relays(self) -> List[Dict]:
        """List all relay configurations."""
        relays_list = []
        for relay_num, config in self.relay_config.items():
            relays_list.append({
                "num": relay_num,
                "label": config["label"],
                "gpio": config["gpio"],
                "description": config["description"]
            })
        return relays_list
        
    def wait_for_nodes(self, timeout: int = 30) -> Dict[str, bool]:
        """
        Wait for all nodes to come online.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            Dict mapping node_id to online status
        """
        logger.info(f"Waiting for nodes to come online (timeout: {timeout}s)...")
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            all_online = True
            for node_id in self.nodes:
                if not self.mqtt.is_node_online(node_id):
                    all_online = False
                    break
                    
            if all_online:
                logger.info("All nodes are online")
                break
                
            time.sleep(1)
            
        # Return final status
        return {
            node_id: self.mqtt.is_node_online(node_id) 
            for node_id in self.nodes
        }
        
    def print_relay_mapping(self):
        """Print the relay mapping for reference."""
        print("\n" + "=" * 60)
        print("  RELAY MAPPING - Project Spotless")
        print("=" * 60)
        print(f"  {'Relay':<8} {'Label':<12} {'GPIO':<6} {'Description'}")
        print("-" * 60)
        for relay_num, config in self.relay_config.items():
            print(f"  {relay_num:<8} {config['label']:<12} {config['gpio']:<6} {config['description']}")
        print("=" * 60 + "\n")
