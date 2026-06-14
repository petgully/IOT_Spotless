"""
=============================================================================
Kiosk Web Server - Project Spotless (Contract v1.1)
=============================================================================
Flask + Flask-SocketIO server for the kiosk UI.

The web server is THIN — it only does HTTP/WS plumbing. All decision logic
lives in:
    qr_validator.py      - 7-gate QR validation (returns start | resume | refuse)
    session_runner.py    - Background session execution
    config_manager.py    - Size profiles A/B + peripheral configs
    spotless_controller.py - StageExecutor with per-second accounting
    db_manager.py        - Database connection

New endpoints in v1.1:
    POST /api/session/start    - existing; now wires booking/resume/test paths
    GET  /api/recovery_pending - lets the UI show a "scan QR to resume Milo's bath"
                                 banner after a power loss (contract §9.1)
    GET  /api/status           - now exposes cloud_sync degraded flag
=============================================================================
"""

import logging
import os
import sys

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import NODES
from qr_validator import validate_qr  # contract v1.1 dispatcher
from session_runner import SessionRunner
from session_stages import (
    get_known_session_types,
    get_stage_summary,
    get_stages,
)
from spotless_controller import ResumeState

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "spotless-kiosk-secret-key"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_spotless_app = None
_session_runner: SessionRunner = None
_db = None

# Fixed Node 1 / 2 / 3 ordering for the kiosk status indicators. Built once
# from config.NODES so the header order is stable across requests.
_NODE_CATALOG = list(NODES.items())


# =============================================================================
# Bootstrap
# =============================================================================

def create_app(spotless_app=None):
    """Wire up the Flask app, DB, and SessionRunner."""
    global _spotless_app, _session_runner, _db
    _spotless_app = spotless_app
    _db = _get_database()

    if spotless_app:
        _session_runner = spotless_app.create_session_runner(
            db=_db,
            emit_fn=lambda event, data: socketio.emit(event, data),
        )
    else:
        # Dev / no-hardware mode
        from config_manager import ConfigManager
        _session_runner = SessionRunner(
            executor=None,
            config_mgr=ConfigManager(),
            db=_db,
            emit=lambda event, data: socketio.emit(event, data),
        )

    # Mount the operator admin blueprint at /admin/*. Best-effort — a missing
    # admin module must not stop the kiosk from starting in production, but
    # should still surface in the logs.
    try:
        from admin.operator_routes import attach as attach_admin
        cfg_mgr = (
            spotless_app.config_mgr if spotless_app
            else _session_runner.config_mgr
        )
        admin_bp = attach_admin(spotless_app, cfg_mgr)
        if "operator_admin" not in app.blueprints:
            app.register_blueprint(admin_bp)
            logger.info("Operator admin mounted at /admin")
    except Exception as e:
        logger.error(f"Failed to mount operator admin blueprint: {e}")

    return app


# =============================================================================
# Helpers
# =============================================================================

def _machine_id() -> str:
    return _spotless_app.machine_id if _spotless_app else ""


def _profile_overrides():
    """Hand build_session() the live A/B timing values from config.json.

    We force-reload from disk on every QR scan so that admin UI saves (or
    manual JSON edits) take effect on the very next session — no service
    restart needed. The cost is a few-millisecond JSON parse per scan, which
    is negligible compared to MQTT round-trips.
    """
    if _spotless_app and _spotless_app.config_mgr:
        try:
            _spotless_app.config_mgr.reload()
            return _spotless_app.config_mgr.get_size_profile_overrides()
        except Exception as e:
            logger.warning(f"profile_overrides fetch failed: {e}")
    return None


def _kiosk_stage_preview(stages):
    """Convert the raw stage list into a lightweight summary for the UI.

    IMPORTANT: this returns ALL stages, in the same order the executor will
    run them. Do NOT filter by show_timer here — the executor emits
    stage_index events referring to the unfiltered list, and any divergence
    between what the kiosk thinks the stages are and what the executor
    actually iterates desyncs the timeline (the top label points one place,
    the timeline highlight points somewhere else).
    """
    return [
        {
            "name": s["name"],
            "label": s["label"],
            "duration": int(s.get("duration", 0)),
            "image": s.get("image", ""),
            "show_timer": bool(s.get("show_timer", True)),
        }
        for s in stages
    ]


# =============================================================================
# Routes
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html", machine_id=_machine_id())


@app.route("/session")
def session_page():
    return render_template("session.html")


@app.route("/api/status")
def get_status():
    cloud_degraded = False
    cloud_queue_depth = 0
    if _spotless_app and getattr(_spotless_app, "cloud_sync", None):
        try:
            cloud_degraded = _spotless_app.cloud_sync.is_degraded
            cloud_queue_depth = _spotless_app.cloud_sync.queue_depth
        except Exception:
            pass

    return jsonify({
        "ready": _spotless_app is not None,
        "machine_id": _machine_id(),
        "session_active": _session_runner.is_active if _session_runner else False,
        "current_session": _session_runner.current_session if _session_runner else None,
        "cloud_sync": {
            "degraded": cloud_degraded,
            "queue_depth": cloud_queue_depth,
        },
        "recovery_pending": _recovery_pending_summary(),
    })


@app.route("/api/db/status")
def get_db_status():
    """Live database connectivity for the header indicator.

    Uses DatabaseManager.ensure_connected(), which pings the DB and
    transparently reconnects a stale link, so the indicator reflects whether
    the database is actually reachable right now (not just whether we once
    connected at boot). Returns connected=False if the DB is unreachable or
    not configured.
    """
    connected = False
    if _db is not None:
        try:
            connected = bool(_db.ensure_connected())
        except Exception as e:
            logger.warning(f"db status check failed: {e}")
            connected = False
    return jsonify({"connected": connected})


@app.route("/api/nodes/status")
def get_nodes_status():
    """Online/offline status of each ESP32 node for the kiosk header.

    Reads live state from the NodeController (which derives online/offline
    from MQTT heartbeats on spotless/nodes/+/status). Returns a stable,
    ordered list so the UI can render fixed Node 1 / 2 / 3 indicators even
    when the controller is unavailable (e.g. dev / no-hardware mode).
    """
    nodes = []
    controller = getattr(_spotless_app, "controller", None) if _spotless_app else None

    states = {}
    if controller is not None:
        try:
            states = {
                node_id: state.value
                for node_id, state in controller.get_all_node_states().items()
            }
        except Exception as e:
            logger.warning(f"node status fetch failed: {e}")

    for idx, (node_id, cfg) in enumerate(_NODE_CATALOG, start=1):
        nodes.append({
            "node_id": node_id,
            "label": f"Node {idx}",
            "name": cfg.get("name", node_id),
            "state": states.get(node_id, "unknown"),
            "online": states.get(node_id) == "online",
        })

    return jsonify({
        "available": controller is not None,
        "nodes": nodes,
    })


@app.route("/api/recovery_pending")
def recovery_pending():
    """Returns the boot-recovered session, if any (contract §9.1)."""
    summary = _recovery_pending_summary()
    if summary is None:
        return jsonify({"pending": False})
    return jsonify({"pending": True, "session": summary})


def _recovery_pending_summary():
    if not _spotless_app:
        return None
    rec = getattr(_spotless_app, "recovered_session", None)
    if rec is None:
        return None
    return {
        "booking_code": rec.booking_code,
        "pet_name": rec.pet_name,
        "current_stage_name": rec.current_stage_name,
        "completed_stage_count": len(rec.completed_stages),
        "machine_id": rec.machine_id,
    }


@app.route("/api/session/start", methods=["POST"])
def start_session():
    data = request.json or {}
    qr_code = (data.get("qr_code") or "").strip()

    if not qr_code:
        return jsonify({"success": False, "error": "QR code is required"}), 400
    if _session_runner is None:
        return jsonify({"success": False, "error": "Kiosk not initialized"}), 500
    if _session_runner.is_active:
        return jsonify({"success": False, "error": "A session is already in progress"}), 400

    machine_id = _machine_id()
    if not machine_id:
        return jsonify({"success": False, "error": "Machine ID not configured"}), 500

    overrides = _profile_overrides()

    # ----- Dispatch through the unified validator -----
    decision = validate_qr(qr_code, machine_id, _db, profile_overrides=overrides)
    kind = decision.get("kind")

    if kind == "unknown":
        socketio.emit("scan_failed", {"message": decision.get("message")})
        return jsonify({
            "success": False,
            "error": decision.get("message", "Invalid QR code"),
        }), 400

    if kind == "test":
        session_type = decision["session_type"]
        stages_preview = _kiosk_stage_preview(get_stages(session_type))
        socketio.emit("scan_success", {
            "qr_code": qr_code,
            "kind": "test",
            "session_type": session_type,
            "stages": stages_preview,
        })
        logger.info(f"Starting service-mode session: {session_type} qr={qr_code}")
        ok = _session_runner.start_test(session_type, qr_code)
        return jsonify({
            "success": ok,
            "kind": "test",
            "session_type": session_type,
            "stages": stages_preview,
        })

    # ----- Booking flow (kind == 'booking') -----
    result_dict = decision.get("result", {})
    vr = decision.get("_obj")

    if result_dict.get("action") == "refuse":
        socketio.emit("scan_failed", {
            "message": result_dict.get("refuse_message"),
            "refuse_code": result_dict.get("refuse_code"),
            "refuse_gate": result_dict.get("refuse_gate"),
        })
        return jsonify({
            "success": False,
            "error": result_dict.get("refuse_message"),
            "refuse_code": result_dict.get("refuse_code"),
            "refuse_gate": result_dict.get("refuse_gate"),
        }), 400

    machine_request = vr.machine_request or {}
    stages = machine_request.get("stages") or []
    stages_preview = _kiosk_stage_preview(stages)
    is_resume = result_dict.get("action") == "resume"

    socketio.emit("scan_success", {
        "qr_code": qr_code,
        "kind": "booking",
        "action": result_dict.get("action"),
        "booking_code": vr.booking_code,
        "customer_name": vr.customer_name,
        "pet_name": vr.pet_name,
        "pet_size": vr.pet_size,
        "package": vr.package,
        "addons": vr.addons,
        "mode": machine_request.get("mode"),
        "profile": machine_request.get("profile"),
        "stages": stages_preview,
        "is_resume": is_resume,
        "resume_from": result_dict.get("resume_from"),
        "resume_count_cloud": result_dict.get("resume_count_cloud"),
    })

    if is_resume:
        rs = _build_resume_state(vr, stages)
        logger.info(
            f"Resuming booking session: code={vr.booking_code} "
            f"from_stage={rs.current_stage_name_at_idx(stages)} "
            f"completed={len(rs.completed_stages)}"
        )
        ok = _session_runner.start_resume(
            validation_result=vr,
            resume_state=rs,
            addons_raw=",".join(vr.addons or []),
        )
    else:
        logger.info(
            f"Starting fresh booking session: code={vr.booking_code} "
            f"pet={vr.pet_name!r} size={vr.pet_size} package={vr.package} "
            f"addons={vr.addons}"
        )
        ok = _session_runner.start_fresh(
            validation_result=vr,
            addons_raw=",".join(vr.addons or []),
        )

    return jsonify({
        "success": ok,
        "kind": "booking",
        "action": result_dict.get("action"),
        "booking_code": vr.booking_code,
        "pet_name": vr.pet_name,
        "stages": stages_preview,
        "is_resume": is_resume,
    })


@app.route("/api/session/stop", methods=["POST"])
def stop_session():
    if _session_runner:
        _session_runner.stop(reason="kiosk-stop-button")
    return jsonify({"success": True, "message": "Session stopped"})


@app.route("/api/session_types")
def get_session_types_endpoint():
    """List service-mode test types only. Real bookings use the QR scan flow."""
    all_types = get_known_session_types()
    bath_test = ["small", "large"]
    utility = [t for t in all_types if t not in bath_test]
    return jsonify({"bath_sessions": bath_test, "utility_sessions": utility})


# =============================================================================
# WebSocket
# =============================================================================

@socketio.on("connect")
def handle_connect():
    logger.info("Client connected")
    emit("connected", {"status": "connected"})


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("Client disconnected")


@socketio.on("scan_input")
def handle_scan_input(data):
    qr_code = (data or {}).get("qr_code", "").strip()
    logger.info(f"Received scan input: {qr_code}")


# =============================================================================
# Resume state builder (contract §9.2)
# =============================================================================

def _build_resume_state(vr, stages) -> ResumeState:
    """Construct ResumeState from local SQLite (preferred) or cloud Query B."""
    progress_store = getattr(_spotless_app, "progress_store", None)
    booking_code = vr.booking_code or ""

    # Preferred: local SQLite (precise per-second delivered ledger)
    if progress_store is not None and booking_code:
        sp = progress_store.load(booking_code)
        if sp is not None:
            # Find current stage idx by name
            current_idx = 0
            for i, st in enumerate(stages):
                if st["name"] == sp.current_stage_name:
                    current_idx = i
                    break
            rs = ResumeState(
                completed_stages=list(sp.completed_stages),
                delivered_seconds=dict(sp.stage_delivered),
                current_stage_idx=current_idx,
            )
            rs.current_stage_name_at_idx = (
                lambda stages_, _idx=current_idx: (
                    stages_[_idx]["name"] if 0 <= _idx < len(stages_) else ""
                )
            )
            logger.info(
                f"resume: local SQLite hit booking={booking_code} "
                f"idx={current_idx} completed={len(rs.completed_stages)}"
            )
            return rs

    # Fallback: cold recovery from cloud `completed_stages` CSV
    qb = vr.query_b or {}
    completed_csv = (qb.get("completed_stages") or "").strip()
    completed = [s.strip() for s in completed_csv.split(",") if s.strip()]
    # current_stage_idx = first stage in `stages` whose name is NOT in completed
    current_idx = 0
    for i, st in enumerate(stages):
        if st["name"] not in completed:
            current_idx = i
            break
    rs = ResumeState(
        completed_stages=completed,
        delivered_seconds={},
        current_stage_idx=current_idx,
    )
    rs.current_stage_name_at_idx = (
        lambda stages_, _idx=current_idx: (
            stages_[_idx]["name"] if 0 <= _idx < len(stages_) else ""
        )
    )
    logger.warning(
        f"resume: cold recovery from cloud booking={booking_code} "
        f"idx={current_idx} completed={len(rs.completed_stages)}"
    )
    return rs


# =============================================================================
# Database helper
# =============================================================================

def _get_database():
    try:
        from db_manager import DatabaseManager, DEFAULT_DB_CONFIG
        db = DatabaseManager(DEFAULT_DB_CONFIG)
        db.connect()
        logger.info(f"Database connected: {DEFAULT_DB_CONFIG.host}")
        return db
    except Exception as e:
        logger.warning(f"Database not available: {e}")
        return None


# =============================================================================
# Server bootstrap
# =============================================================================

def run_server(host="0.0.0.0", port=5000, debug=False):
    logger.info(f"Starting kiosk server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server(debug=True)
