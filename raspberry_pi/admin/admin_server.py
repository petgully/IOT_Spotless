"""
=============================================================================
Admin Dashboard - Project Spotless
=============================================================================
Standalone Flask server for testing and controlling ESP32 nodes.
Shows real-time node status and provides relay toggle controls.

Run:
    cd raspberry_pi
    source venv/bin/activate
    python -m admin.admin_server

Or:
    python admin/admin_server.py

Opens on http://<pi-ip>:8080
=============================================================================
"""

import os
import sys
import json
import time
import logging
import threading
import socket
from datetime import datetime

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'spotless-admin-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC_BASE = "spotless/nodes"

NODES_CONFIG = {
    "spotless_node1": {
        "name": "ESP32 Node 1",
        "relays": {
            1: {"label": "S1_220V", "description": "220V Solenoid", "device": "pump", "has_led": False},
            2: {"label": "P1_P2", "description": "Pumps P1 & P2", "device": "p3", "has_led": False},
            3: {"label": "FP1", "description": "Flow Pump 1", "device": "d1", "has_led": True, "led": "LED_SHAMPOO"},
            4: {"label": "RS1_DS2", "description": "RO Sol 1 & Dia Sol 2", "device": "ro1", "has_led": True, "led": "LED_WATER"},
            5: {"label": "RS2_DS1", "description": "RO Sol 2 & Dia Sol 1", "device": "ro2", "has_led": True, "led": "LED_RESETCLEAN"},
            6: {"label": "BACK1", "description": "Backflow 1", "device": "p2", "has_led": True, "led": "PRE-MIX1"},
            7: {"label": "BACK2", "description": "Backflow 2", "device": "p1", "has_led": True, "led": "PRE-MIX2"},
        }
    },
    "spotless_node2": {
        "name": "ESP32 Node 2",
        "relays": {
            1: {"label": "S1_220V", "description": "220V Solenoid", "device": "s9", "has_led": False},
            2: {"label": "P1_P2", "description": "Pumps P1 & P2", "device": "s7", "has_led": False},
            3: {"label": "FP1", "description": "Flow Pump 1", "device": "d2", "has_led": True, "led": "LED_SHAMPOO"},
            4: {"label": "RS1_DS2", "description": "RO Sol 1 & Dia Sol 2", "device": "ro3", "has_led": True, "led": "LED_WATER"},
            5: {"label": "RS2_DS1", "description": "RO Sol 2 & Dia Sol 1", "device": "ro4", "has_led": True, "led": "LED_RESETCLEAN"},
            6: {"label": "BACK1", "description": "Backflow 1", "device": "p5", "has_led": True, "led": "PRE-MIX1"},
            7: {"label": "BACK2", "description": "Backflow 2", "device": "p4", "has_led": True, "led": "PRE-MIX2"},
        }
    },
    "spotless_node3": {
        "name": "ESP32 Node 3",
        "relays": {
            1: {"label": "S1_220V", "description": "220V Solenoid", "device": "s8", "has_led": False},
            2: {"label": "P1_P2", "description": "Pumps P1 & P2", "device": "s6", "has_led": False},
            3: {"label": "FP1", "description": "Flow Pump 1", "device": "s5", "has_led": True, "led": "LED_SHAMPOO"},
            4: {"label": "RS1_DS2", "description": "RO Sol 1 & Dia Sol 2", "device": "s3", "has_led": True, "led": "LED_WATER"},
            5: {"label": "RS2_DS1", "description": "RO Sol 2 & Dia Sol 1", "device": "s4", "has_led": True, "led": "LED_RESETCLEAN"},
            6: {"label": "BACK1", "description": "Backflow 1", "device": "s2", "has_led": True, "led": "PRE-MIX1"},
            7: {"label": "BACK2", "description": "Backflow 2", "device": "s1", "has_led": True, "led": "PRE-MIX2"},
        }
    },
}

NODE_TIMEOUT = 60

# Live state
node_status = {}
relay_states = {}
mqtt_client = None
mqtt_connected = False


def get_pi_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


# =========================================================================
# MQTT
# =========================================================================
def on_mqtt_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        logger.info("Admin MQTT connected")
        client.subscribe(f"{TOPIC_BASE}/+/status", 1)
        client.subscribe(f"{TOPIC_BASE}/+/relays/+/state", 1)
    else:
        logger.error(f"MQTT connect failed rc={rc}")


def on_mqtt_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    logger.warning("Admin MQTT disconnected")


def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode('utf-8'))

        if "/status" in topic and "/relays/" not in topic:
            handle_node_status(topic, payload)
        elif "/relays/" in topic and "/state" in topic:
            handle_relay_state(topic, payload)
    except Exception as e:
        logger.error(f"MQTT message error: {e}")


def handle_node_status(topic, data):
    nid = data.get("node_id")
    if not nid:
        parts = topic.split("/")
        if len(parts) >= 3:
            nid = parts[2]
    if not nid:
        return

    node_status[nid] = {
        "online": data.get("online", False),
        "ip": data.get("ip", "?"),
        "rssi": data.get("rssi", 0),
        "uptime": data.get("uptime", 0),
        "relay_count": data.get("relay_count", 7),
        "last_seen": time.time(),
    }

    socketio.emit("node_status", {
        "node_id": nid,
        **node_status[nid],
        "online": is_node_online(nid),
    })


def handle_relay_state(topic, data):
    parts = topic.split("/")
    if len(parts) < 5:
        return
    nid = parts[2]
    relay_num = int(parts[4])
    state = data.get("state", "OFF")

    key = f"{nid}_relay_{relay_num}"
    relay_states[key] = {
        "state": state,
        "label": data.get("label", ""),
        "gpio": data.get("gpio", 0),
        "led_gpio": data.get("led_gpio", -1),
        "led_label": data.get("led_label", ""),
        "timestamp": time.time(),
    }

    socketio.emit("relay_state", {
        "node_id": nid,
        "relay_num": relay_num,
        "state": state,
        "label": data.get("label", ""),
    })


def is_node_online(nid):
    s = node_status.get(nid)
    if not s:
        return False
    return s.get("online", False) and (time.time() - s.get("last_seen", 0)) < NODE_TIMEOUT


def send_relay_command(nid, relay_num, state_str):
    if not mqtt_client or not mqtt_connected:
        return False
    topic = f"{TOPIC_BASE}/{nid}/relays/{relay_num}/command"
    payload = json.dumps({"state": state_str})
    result = mqtt_client.publish(topic, payload, qos=1)
    logger.info(f"Command: {nid} relay {relay_num} -> {state_str}")
    return result.rc == mqtt.MQTT_ERR_SUCCESS


def send_all_relays_command(nid, state_str):
    if not mqtt_client or not mqtt_connected:
        return False
    topic = f"{TOPIC_BASE}/{nid}/relays/all/command"
    payload = json.dumps({"state": state_str})
    result = mqtt_client.publish(topic, payload, qos=1)
    logger.info(f"Command: {nid} ALL -> {state_str}")
    return result.rc == mqtt.MQTT_ERR_SUCCESS


def request_node_status(nid):
    if not mqtt_client or not mqtt_connected:
        return False
    topic = f"{TOPIC_BASE}/{nid}/request"
    payload = json.dumps({"command": "status"})
    result = mqtt_client.publish(topic, payload, qos=1)
    return result.rc == mqtt.MQTT_ERR_SUCCESS


def start_mqtt():
    global mqtt_client
    try:
        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="spotless_admin_dashboard"
        )
    except (AttributeError, TypeError):
        mqtt_client = mqtt.Client(client_id="spotless_admin_dashboard")

    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_disconnect = on_mqtt_disconnect
    mqtt_client.on_message = on_mqtt_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        logger.info(f"MQTT connecting to {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        logger.error(f"MQTT connection failed: {e}")


# =========================================================================
# Flask Routes
# =========================================================================
@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/config")
def get_config():
    pi_ip = get_pi_ip()
    config_data = {}
    for nid, ncfg in NODES_CONFIG.items():
        relays_list = []
        for rnum, rcfg in sorted(ncfg["relays"].items()):
            key = f"{nid}_relay_{rnum}"
            rs = relay_states.get(key, {})
            relays_list.append({
                "num": rnum,
                "label": rcfg["label"],
                "description": rcfg["description"],
                "device": rcfg["device"],
                "has_led": rcfg["has_led"],
                "led": rcfg.get("led", ""),
                "state": rs.get("state", "OFF"),
            })
        ns = node_status.get(nid, {})
        config_data[nid] = {
            "name": ncfg["name"],
            "node_id": nid,
            "online": is_node_online(nid),
            "ip": ns.get("ip", "—"),
            "rssi": ns.get("rssi", 0),
            "uptime": ns.get("uptime", 0),
            "relays": relays_list,
        }
    return jsonify({
        "pi_ip": pi_ip,
        "mqtt_connected": mqtt_connected,
        "nodes": config_data,
    })


@app.route("/api/relay", methods=["POST"])
def toggle_relay():
    data = request.json
    nid = data.get("node_id")
    relay_num = data.get("relay_num")
    state = data.get("state", "OFF")

    if not nid or relay_num is None:
        return jsonify({"success": False, "error": "Missing node_id or relay_num"}), 400

    ok = send_relay_command(nid, int(relay_num), state)
    return jsonify({"success": ok})


@app.route("/api/all_relays", methods=["POST"])
def toggle_all_relays():
    data = request.json
    nid = data.get("node_id")
    state = data.get("state", "OFF")

    if not nid:
        return jsonify({"success": False, "error": "Missing node_id"}), 400

    ok = send_all_relays_command(nid, state)
    return jsonify({"success": ok})


@app.route("/api/refresh", methods=["POST"])
def refresh_nodes():
    for nid in NODES_CONFIG:
        request_node_status(nid)
    return jsonify({"success": True})


# =========================================================================
# WebSocket Events
# =========================================================================
@socketio.on("connect")
def ws_connect():
    logger.info("Admin client connected")
    emit("connected", {"mqtt": mqtt_connected})


@socketio.on("toggle_relay")
def ws_toggle_relay(data):
    nid = data.get("node_id")
    relay_num = data.get("relay_num")
    state = data.get("state", "OFF")
    send_relay_command(nid, int(relay_num), state)


@socketio.on("all_relays")
def ws_all_relays(data):
    nid = data.get("node_id")
    state = data.get("state", "OFF")
    send_all_relays_command(nid, state)


@socketio.on("refresh")
def ws_refresh():
    for nid in NODES_CONFIG:
        request_node_status(nid)


# =========================================================================
# Main
# =========================================================================
def run_admin(host="0.0.0.0", port=8080):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger.info("Starting Admin Dashboard")
    start_mqtt()

    time.sleep(1)
    for nid in NODES_CONFIG:
        request_node_status(nid)

    pi_ip = get_pi_ip()
    logger.info(f"Admin Dashboard: http://{pi_ip}:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    run_admin()
