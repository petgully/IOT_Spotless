const socket = io();
let nodesData = {};

// =========================================================================
// Socket.IO Events
// =========================================================================
socket.on("connect", () => {
    updateMqttBadge(true);
    loadConfig();
});

socket.on("disconnect", () => {
    updateMqttBadge(false);
});

socket.on("connected", (data) => {
    updateMqttBadge(data.mqtt);
});

socket.on("node_status", (data) => {
    const nid = data.node_id;
    if (nodesData[nid]) {
        nodesData[nid].online = data.online;
        nodesData[nid].ip = data.ip || "—";
        nodesData[nid].rssi = data.rssi || 0;
        nodesData[nid].uptime = data.uptime || 0;
    }
    updateNodeUI(nid);
    updateTimestamp();
});

socket.on("relay_state", (data) => {
    const { node_id, relay_num, state } = data;
    const key = `${node_id}_relay_${relay_num}`;
    if (nodesData[node_id]) {
        const relay = nodesData[node_id].relays.find(r => r.num === relay_num);
        if (relay) relay.state = state;
    }
    updateRelayUI(node_id, relay_num, state);
    updateTimestamp();
});

// =========================================================================
// Load Config & Build UI
// =========================================================================
function loadConfig() {
    fetch("/api/config")
        .then(r => r.json())
        .then(data => {
            document.getElementById("pi-info").textContent = `Pi IP: ${data.pi_ip}`;
            updateMqttBadge(data.mqtt_connected);
            nodesData = data.nodes;
            buildUI(data.nodes);
            updateTimestamp();
        })
        .catch(err => {
            console.error("Failed to load config:", err);
        });
}

function buildUI(nodes) {
    const container = document.getElementById("nodes-container");
    container.innerHTML = "";

    const nodeIds = Object.keys(nodes).sort();
    for (const nid of nodeIds) {
        const node = nodes[nid];
        container.appendChild(createNodeCard(nid, node));
    }
}

function createNodeCard(nid, node) {
    const card = document.createElement("div");
    card.className = `node-card ${node.online ? "online" : "offline"}`;
    card.id = `card-${nid}`;

    const onlineClass = node.online ? "online" : "offline";
    const uptime = formatUptime(node.uptime);

    card.innerHTML = `
        <div class="node-header">
            <div class="node-title">
                <div class="node-dot ${onlineClass}" id="dot-${nid}"></div>
                <span class="node-name">${node.name}</span>
            </div>
            <span class="node-status-text ${onlineClass}" id="status-${nid}">
                ${node.online ? "ONLINE" : "OFFLINE"}
            </span>
        </div>
        <div class="node-meta" id="meta-${nid}">
            <span>IP: <strong>${node.ip}</strong></span>
            <span>WiFi: <strong>${node.rssi} dBm</strong></span>
            <span>Uptime: <strong>${uptime}</strong></span>
        </div>
        <div class="node-actions">
            <button class="btn btn-all-on" onclick="allRelays('${nid}', 'ON')">All ON</button>
            <button class="btn btn-all-off" onclick="allRelays('${nid}', 'OFF')">All OFF</button>
        </div>
        <div class="relay-list" id="relays-${nid}">
            ${node.relays.map(r => createRelayRow(nid, r, node.online)).join("")}
        </div>
    `;

    return card;
}

function createRelayRow(nid, relay, nodeOnline) {
    const isOn = relay.state === "ON";
    const stateClass = isOn ? "on" : "off";
    const checked = isOn ? "checked" : "";
    const disabled = nodeOnline ? "" : "disabled";
    const ledBadge = relay.has_led
        ? `<span class="relay-led-badge">${relay.led}</span>`
        : "";

    return `
        <div class="relay-row" id="relay-row-${nid}-${relay.num}">
            <div class="relay-num">${relay.num}</div>
            <div class="relay-info">
                <div class="relay-label">${relay.label}</div>
                <div class="relay-desc">${relay.description}</div>
                <div class="relay-device">${relay.device}</div>
            </div>
            ${ledBadge}
            <div class="toggle-wrap">
                <label class="toggle">
                    <input type="checkbox" ${checked} ${disabled}
                           id="toggle-${nid}-${relay.num}"
                           onchange="toggleRelay('${nid}', ${relay.num}, this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <span class="relay-state-label ${stateClass}" id="state-${nid}-${relay.num}">
                ${isOn ? "ON" : "OFF"}
            </span>
        </div>
    `;
}

// =========================================================================
// UI Updates
// =========================================================================
function updateNodeUI(nid) {
    const node = nodesData[nid];
    if (!node) return;

    const card = document.getElementById(`card-${nid}`);
    const dot = document.getElementById(`dot-${nid}`);
    const statusText = document.getElementById(`status-${nid}`);
    const meta = document.getElementById(`meta-${nid}`);

    if (!card) return;

    const online = node.online;
    card.className = `node-card ${online ? "online" : "offline"}`;
    dot.className = `node-dot ${online ? "online" : "offline"}`;
    statusText.className = `node-status-text ${online ? "online" : "offline"}`;
    statusText.textContent = online ? "ONLINE" : "OFFLINE";

    meta.innerHTML = `
        <span>IP: <strong>${node.ip}</strong></span>
        <span>WiFi: <strong>${node.rssi} dBm</strong></span>
        <span>Uptime: <strong>${formatUptime(node.uptime)}</strong></span>
    `;

    // Enable/disable toggles
    const relayContainer = document.getElementById(`relays-${nid}`);
    if (relayContainer) {
        const toggles = relayContainer.querySelectorAll("input[type=checkbox]");
        toggles.forEach(t => { t.disabled = !online; });
    }
}

function updateRelayUI(nid, relayNum, state) {
    const toggle = document.getElementById(`toggle-${nid}-${relayNum}`);
    const label = document.getElementById(`state-${nid}-${relayNum}`);

    if (toggle) {
        toggle.checked = state === "ON";
    }
    if (label) {
        const isOn = state === "ON";
        label.textContent = isOn ? "ON" : "OFF";
        label.className = `relay-state-label ${isOn ? "on" : "off"}`;
    }
}

function updateMqttBadge(connected) {
    const dot = document.getElementById("mqtt-dot");
    const label = document.getElementById("mqtt-label");
    if (connected) {
        dot.className = "dot online";
        label.textContent = "MQTT: Connected";
    } else {
        dot.className = "dot offline";
        label.textContent = "MQTT: Disconnected";
    }
}

function updateTimestamp() {
    const el = document.getElementById("last-update");
    const now = new Date();
    el.textContent = `Last update: ${now.toLocaleTimeString()}`;
}

// =========================================================================
// Actions
// =========================================================================
function toggleRelay(nid, relayNum, isOn) {
    const state = isOn ? "ON" : "OFF";
    socket.emit("toggle_relay", {
        node_id: nid,
        relay_num: relayNum,
        state: state,
    });
    showToast(`${nid} Relay ${relayNum} → ${state}`, "success");
}

function allRelays(nid, state) {
    socket.emit("all_relays", { node_id: nid, state: state });

    // Optimistically update UI
    if (nodesData[nid]) {
        nodesData[nid].relays.forEach(r => {
            r.state = state;
            updateRelayUI(nid, r.num, state);
        });
    }
    showToast(`${nid} ALL → ${state}`, "success");
}

// =========================================================================
// Refresh
// =========================================================================
document.getElementById("btn-refresh").addEventListener("click", () => {
    socket.emit("refresh");
    showToast("Requesting status from all nodes...", "success");
    setTimeout(loadConfig, 2000);
});

// Auto-refresh every 30 seconds
setInterval(() => {
    socket.emit("refresh");
    setTimeout(loadConfig, 2000);
}, 30000);

// =========================================================================
// Helpers
// =========================================================================
function formatUptime(seconds) {
    if (!seconds || seconds === 0) return "—";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function showToast(message, type = "success") {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
}
