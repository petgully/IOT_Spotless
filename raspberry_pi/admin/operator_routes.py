"""
=============================================================================
Operator Admin — Flask Blueprint mounted on the kiosk app
=============================================================================
Lives at /admin/* on the same Flask process that serves the kiosk UI on
port 5000. NOT to be confused with admin_server.py which is the standalone
relay-test dashboard on port 8080 (engineering tool, not operator UI).

Key contract with the rest of the kiosk:
- All writes go through ConfigManager so atomic save + cache stay coherent.
- After every write we call config_mgr.reload() so the live cache reflects
  the new on-disk values for the very next session.
- Geyser/roof changes ALSO call apply_config() on the running controllers
  so scheduled behaviours (morning preheat, evening light) pick up the new
  values without a service restart.
- Read-only health probes pull from the same NodeController + cloud_sync +
  progress_store the kiosk uses, so dashboard numbers can never drift from
  reality.
=============================================================================
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template,
    request, url_for,
)

from admin.operator_auth import (
    is_using_default_password,
    require_admin,
)
from admin.operator_validators import (
    SIZE_PROFILE_FIELDS,
    validate_geyser,
    validate_machine_info,
    validate_roof_light,
    validate_size_profile,
)

logger = logging.getLogger(__name__)

# Templates and static assets ship next to this module so the operator admin
# is self-contained and the existing relay-test dashboard's templates aren't
# disturbed.
_HERE = Path(__file__).resolve().parent

operator_admin_bp = Blueprint(
    "operator_admin",
    __name__,
    url_prefix="/admin",
    template_folder=str(_HERE / "operator_templates"),
    static_folder=str(_HERE / "operator_static"),
    # static_url_path is relative to url_prefix, so the final path becomes
    # /admin/static/css/operator.css — exactly what base.html references via
    # url_for('operator_admin.static', filename='css/operator.css').
    static_url_path="/static",
)

# Bag of references to live application state, populated by attach().
_state: Dict[str, Any] = {
    "spotless_app": None,
    "config_mgr":   None,
}


# =============================================================================
# Wiring
# =============================================================================

def attach(spotless_app, config_mgr) -> Blueprint:
    """Wire the blueprint to the live SpotlessApplication.

    Called from kiosk/web_server.py create_app(). The blueprint then has
    access to config_mgr (for read/write of config.json) and spotless_app
    (for live geyser/roof_light controllers, MQTT NodeController, cloud
    sync, etc.).
    """
    _state["spotless_app"] = spotless_app
    _state["config_mgr"] = config_mgr
    return operator_admin_bp


def _spotless_app():
    return _state.get("spotless_app")


def _config_mgr():
    return _state.get("config_mgr")


# =============================================================================
# Common context for templates
# =============================================================================

def _machine_info(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "machine_id":   cfg.get("machine_id", ""),
        "machine_name": cfg.get("machine_name", ""),
        "location":     cfg.get("location", ""),
        "updated_at":   cfg.get("updated_at", ""),
        "config_source": _config_mgr().config_source.value if _config_mgr() else "?",
    }


def _node_state_label(v: Any) -> str:
    """Normalise node state from various shapes to 'online'/'offline'/'unknown'."""
    if v is True:
        return "online"
    if v is False:
        return "offline"
    if hasattr(v, "value"):  # NodeState enum
        return str(v.value)
    if isinstance(v, dict):
        if v.get("online"):
            return "online"
        return "offline"
    return str(v) if v is not None else "unknown"


def _summarize_session(s: Any) -> Optional[Dict[str, Any]]:
    """Compress the runner's session dict to a few human-friendly fields.

    runner.current_session can be ~50 KB of stage definitions; rendering it
    raw into the dashboard turns the System Health card into a wall of
    JSON. We only want the operator-facing essentials.
    """
    if not isinstance(s, dict):
        return None
    stages = s.get("stages") or []
    current_idx = s.get("current_stage")
    current_stage_name = ""
    if isinstance(current_idx, int) and 0 <= current_idx < len(stages):
        cs = stages[current_idx]
        if isinstance(cs, dict):
            current_stage_name = cs.get("label") or cs.get("name") or ""

    kind = s.get("kind") or "?"
    summary: Dict[str, Any] = {
        "kind": kind,
        "started_at": s.get("started_at", ""),
        "stage_count": len(stages),
        "current_stage_index": current_idx if isinstance(current_idx, int) else None,
        "current_stage_name": current_stage_name,
    }
    if kind == "booking":
        summary["label"] = (
            f"{s.get('pet_name') or '?'} "
            f"({s.get('pet_size') or '?'} / {s.get('package') or '?'})"
        )
        summary["booking_code"] = s.get("booking_code", "")
    else:  # test
        summary["label"] = f"Test: {s.get('session_type', '?')}"
        summary["booking_code"] = s.get("qr_code", "")
    return summary


def _health_snapshot() -> Dict[str, Any]:
    """Live system health for the dashboard. All probes are best-effort —
    a missing controller in dev mode must NOT 500 the page."""
    app = _spotless_app()
    health: Dict[str, Any] = {
        "nodes": {},                # node_id -> "online"/"offline"/"unknown"
        "nodes_online": 0,
        "nodes_total": 0,
        "session_active": False,
        "session_summary": None,    # compact dict, never the raw runner state
        "cloud_degraded": False,
        "cloud_queue_depth": 0,
        "geyser_heating": False,
        "roof_light_on": False,
        "recovery_pending": False,
    }
    if not app:
        return health

    try:
        controller = getattr(app, "controller", None)
        if controller is not None and hasattr(controller, "get_all_node_states"):
            states = controller.get_all_node_states() or {}
            normalised = {nid: _node_state_label(v) for nid, v in states.items()}
            health["nodes"] = normalised
            health["nodes_total"] = len(normalised) or 3
            health["nodes_online"] = sum(1 for v in normalised.values() if v == "online")
    except Exception as e:
        logger.warning(f"admin health: node states unavailable: {e}")

    try:
        runner = getattr(app, "runner", None)
        if runner is not None:
            health["session_active"] = bool(runner.is_active)
            health["session_summary"] = _summarize_session(runner.current_session)
    except Exception as e:
        logger.warning(f"admin health: runner snapshot failed: {e}")

    try:
        cs = getattr(app, "cloud_sync", None)
        if cs is not None:
            health["cloud_degraded"] = bool(cs.is_degraded)
            health["cloud_queue_depth"] = int(cs.queue_depth)
    except Exception:
        pass

    try:
        gc = getattr(app, "geyser_ctrl", None)
        if gc is not None:
            health["geyser_heating"] = bool(gc.is_heating)
    except Exception:
        pass

    try:
        rc = getattr(app, "roof_ctrl", None)
        if rc is not None:
            health["roof_light_on"] = bool(rc.is_on)
    except Exception:
        pass

    try:
        health["recovery_pending"] = getattr(app, "recovered_session", None) is not None
    except Exception:
        pass

    return health


def _all_settings() -> Dict[str, Any]:
    cfg = _config_mgr().reload() if _config_mgr() else {}
    return {
        "machine":     _machine_info(cfg),
        "profile_a":   _config_mgr().get_size_profile("A") if _config_mgr() else {},
        "profile_b":   _config_mgr().get_size_profile("B") if _config_mgr() else {},
        "geyser":      _config_mgr().get_geyser_config() if _config_mgr() else {},
        "roof_light":  _config_mgr().get_roof_light_config() if _config_mgr() else {},
    }


# =============================================================================
# Blueprint-wide guard
# =============================================================================

@operator_admin_bp.before_request
def _gate():
    # Static files are reachable through the blueprint's own static folder;
    # don't re-challenge them on every CSS request.
    if request.endpoint and request.endpoint.endswith(".static"):
        return None
    return None  # pass through; per-route @require_admin handles auth


# =============================================================================
# Health-check probe (no auth) — useful for monitoring / Phase 4 watchdog
# =============================================================================

@operator_admin_bp.route("/healthz")
def healthz():
    """Liveness check that the kiosk process is alive AND has booted past
    SpotlessApplication.start(). Returns 200 even before login so external
    monitoring (cron, uptime check, future watchdog) can poll it."""
    return jsonify({
        "status": "ok",
        "ready":  _spotless_app() is not None,
        "time":   datetime.now().isoformat(timespec="seconds"),
    })


# =============================================================================
# Pages
# =============================================================================

@operator_admin_bp.route("/")
@require_admin
def dashboard():
    settings = _all_settings()
    health = _health_snapshot()
    return render_template(
        "dashboard.html",
        settings=settings,
        health=health,
        using_default_password=is_using_default_password(),
        size_profile_fields=SIZE_PROFILE_FIELDS,
    )


@operator_admin_bp.route("/settings")
@require_admin
def settings_page():
    settings = _all_settings()
    return render_template(
        "settings.html",
        settings=settings,
        using_default_password=is_using_default_password(),
        size_profile_fields=SIZE_PROFILE_FIELDS,
    )


@operator_admin_bp.route("/equipment-test")
@require_admin
def equipment_test_page():
    settings = _all_settings()
    return render_template(
        "equipment_test.html",
        settings=settings,
        using_default_password=is_using_default_password(),
        plan=_equipment_test_plan(),
        seconds_each=_equipment_test_seconds(),
    )


@operator_admin_bp.route("/module-test")
@require_admin
def module_test_page():
    settings = _all_settings()
    return render_template(
        "module_test.html",
        settings=settings,
        using_default_password=is_using_default_password(),
        plan=_module_test_plan(),
    )


# =============================================================================
# Equipment self-test ("quick check") — runs every device ~5s, node by node,
# then the Pi-direct GPIO relays. Reuses the existing StageExecutor demo walk
# via the "equipment_test" session type so there is exactly one code path that
# drives the hardware.
# =============================================================================

def _runner():
    app = _spotless_app()
    return getattr(app, "runner", None) if app else None


def _equipment_test_plan():
    try:
        from spotless_controller import build_equipment_test_plan
        return build_equipment_test_plan()
    except Exception as e:
        logger.warning(f"admin: equipment-test plan unavailable: {e}")
        return []


def _equipment_test_seconds() -> int:
    try:
        from spotless_controller import EQUIPMENT_TEST_SECONDS
        return int(EQUIPMENT_TEST_SECONDS)
    except Exception:
        return 5


def _selftest_running(runner) -> bool:
    """True only when the currently-active session is the equipment self-test
    (so we never report someone's real bath as a running self-test)."""
    if runner is None or not getattr(runner, "is_active", False):
        return False
    s = getattr(runner, "current_session", None) or {}
    return isinstance(s, dict) and s.get("session_type") == "equipment_test"


@operator_admin_bp.route("/api/equipment-test/plan", methods=["GET"])
@require_admin
def api_equipment_test_plan():
    return jsonify({
        "plan": _equipment_test_plan(),
        "seconds_each": _equipment_test_seconds(),
    })


@operator_admin_bp.route("/api/equipment-test/status", methods=["GET"])
@require_admin
def api_equipment_test_status():
    runner = _runner()
    session_active = bool(getattr(runner, "is_active", False)) if runner else False
    return jsonify({
        "available": runner is not None,
        "session_active": session_active,
        "selftest_running": _selftest_running(runner),
    })


@operator_admin_bp.route("/api/equipment-test/start", methods=["POST"])
@require_admin
def api_equipment_test_start():
    runner = _runner()
    if runner is None:
        return jsonify({"ok": False,
                        "error": "Controller not available on this host."}), 503
    if getattr(runner, "is_active", False):
        return jsonify({"ok": False,
                        "error": "A session is already running. "
                                 "Stop it before starting the self-test."}), 409
    mc = _manual_controller()
    if mc is not None and mc.any_active:
        return jsonify({"ok": False,
                        "error": "Manual module test has devices ON. "
                                 "Turn them off before the self-test."}), 409
    try:
        ok = runner.start_test("equipment_test", "ADMIN_SELFTEST")
    except Exception as e:
        logger.exception("admin: equipment-test start failed")
        return jsonify({"ok": False, "error": f"Start failed: {e}"}), 500
    if not ok:
        return jsonify({"ok": False,
                        "error": "Could not start self-test "
                                 "(another session may be active)."}), 409
    logger.info("admin: equipment self-test started")
    return jsonify({"ok": True})


@operator_admin_bp.route("/api/equipment-test/stop", methods=["POST"])
@require_admin
def api_equipment_test_stop():
    runner = _runner()
    if runner is None:
        return jsonify({"ok": False,
                        "error": "Controller not available on this host."}), 503
    try:
        runner.stop(reason="admin-selftest-stop")
    except Exception as e:
        logger.exception("admin: equipment-test stop failed")
        return jsonify({"ok": False, "error": f"Stop failed: {e}"}), 500
    logger.info("admin: equipment self-test stopped by operator")
    return jsonify({"ok": True})


# =============================================================================
# Manual module test — latch individual modules ON/OFF (no timing). Drives
# DeviceController (MQTT) + GPIOController directly so the operator can watch
# each fluid line / motor in isolation and see which relays are energised.
# Mutually exclusive with timed sessions / the self-test.
# =============================================================================

def _manual_controller():
    """Lazily build (and cache) the ManualController on the live app.

    Returns None when no SpotlessApplication (dev host) or the hardware
    controllers aren't up yet.
    """
    app = _spotless_app()
    if app is None:
        return None
    mc = getattr(app, "manual_ctrl", None)
    if mc is not None:
        return mc
    devices = getattr(app, "devices", None)
    gpio = getattr(app, "gpio", None)
    if devices is None and gpio is None:
        return None
    try:
        from manual_control import ManualController
        mc = ManualController(devices, gpio)
        app.manual_ctrl = mc  # cache on the app so state persists across requests
        return mc
    except Exception as e:
        logger.warning(f"admin: manual controller unavailable: {e}")
        return None


def _module_test_plan():
    try:
        from manual_control import build_module_plan
        return build_module_plan()
    except Exception as e:
        logger.warning(f"admin: module-test plan unavailable: {e}")
        return []


@operator_admin_bp.route("/api/module-test/state", methods=["GET"])
@require_admin
def api_module_test_state():
    mc = _manual_controller()
    runner = _runner()
    return jsonify({
        "available": mc is not None,
        "session_active": bool(getattr(runner, "is_active", False)) if runner else False,
        "state": mc.state() if mc else {"modules": {}, "energized": [], "any_active": False},
    })


@operator_admin_bp.route("/api/module-test/toggle", methods=["POST"])
@require_admin
def api_module_test_toggle():
    mc = _manual_controller()
    if mc is None:
        return jsonify({"ok": False,
                        "error": "Controller not available on this host."}), 503

    data = _json_payload()
    key = str(data.get("module") or "").strip()
    on = bool(data.get("on"))
    if not key:
        return jsonify({"ok": False, "error": "Missing 'module'."}), 400

    # Refuse to drive relays while a timed bath / self-test owns the hardware.
    runner = _runner()
    if on and runner is not None and getattr(runner, "is_active", False):
        return jsonify({"ok": False,
                        "error": "A session is running. Stop it before "
                                 "testing modules."}), 409

    try:
        state = mc.set_module(key, on)
    except KeyError:
        return jsonify({"ok": False, "error": f"Unknown module {key!r}."}), 400
    except Exception as e:
        logger.exception("admin: module-test toggle failed")
        return jsonify({"ok": False, "error": f"Toggle failed: {e}"}), 500
    logger.info(f"admin: module {key} -> {'ON' if on else 'OFF'}")
    return jsonify({"ok": True, "state": state})


@operator_admin_bp.route("/api/module-test/all-off", methods=["POST"])
@require_admin
def api_module_test_all_off():
    mc = _manual_controller()
    if mc is None:
        return jsonify({"ok": False,
                        "error": "Controller not available on this host."}), 503
    try:
        state = mc.all_off()
    except Exception as e:
        logger.exception("admin: module-test all-off failed")
        return jsonify({"ok": False, "error": f"All-off failed: {e}"}), 500
    logger.info("admin: module-test ALL OFF by operator")
    return jsonify({"ok": True, "state": state})


# =============================================================================
# Form POST handlers (HTML browser flow)
# =============================================================================

def _redirect_back(anchor: str = ""):
    target = url_for("operator_admin.settings_page")
    if anchor:
        target = f"{target}#{anchor}"
    return redirect(target, code=303)


def _safe_save(do_save, success_msg: str, anchor: str):
    """Run a save closure, surface any disk failure as a flash error.

    Without this wrapper a write that fails (full SD card, permission
    error, ENOSPC) would silently log + flash "saved" — the operator would
    think the change took effect when it didn't.
    """
    try:
        do_save()
    except Exception as e:
        logger.exception("admin: save failed")
        flash(("error", f"Save failed: {e}. Old values are still in effect."))
        return _redirect_back(anchor)
    flash(("ok", success_msg))
    return _redirect_back(anchor)


@operator_admin_bp.route("/settings/machine_info", methods=["POST"])
@require_admin
def save_machine_info():
    payload = {k: v for k, v in request.form.items() if k in {"machine_name", "location"}}
    cleaned, err = validate_machine_info(payload)
    if err:
        flash(("error", err))
        return _redirect_back("machine")

    def _do():
        _config_mgr().update_machine_info(**cleaned)
        _config_mgr().reload()
        logger.info(f"admin: machine_info updated -> {cleaned}")

    return _safe_save(_do, "Machine info saved.", "machine")


@operator_admin_bp.route("/settings/profile/<profile_key>", methods=["POST"])
@require_admin
def save_profile(profile_key: str):
    profile_key = profile_key.upper()
    if profile_key not in {"A", "B"}:
        flash(("error", f"Unknown size profile {profile_key!r}."))
        return _redirect_back("profile-a")

    payload: Dict[str, Any] = {}
    for field, _label, _lo, _hi in SIZE_PROFILE_FIELDS:
        if field in request.form:
            payload[field] = request.form[field]
    cleaned, err = validate_size_profile(payload)
    if err:
        flash(("error", f"Profile {profile_key}: {err}"))
        return _redirect_back(f"profile-{profile_key.lower()}")

    def _do():
        _config_mgr().update_size_profile(profile_key, **cleaned)
        _config_mgr().reload()
        logger.info(f"admin: profile {profile_key} updated -> {cleaned}")

    return _safe_save(
        _do,
        f"Profile {profile_key} saved. Next QR scan picks up the new timings.",
        f"profile-{profile_key.lower()}",
    )


@operator_admin_bp.route("/settings/geyser", methods=["POST"])
@require_admin
def save_geyser():
    payload = {
        k: request.form[k]
        for k in ("morning_preheat_time", "heat_duration_sec", "safety_cutoff_sec")
        if k in request.form
    }
    cleaned, err = validate_geyser(payload)
    if err:
        flash(("error", err))
        return _redirect_back("geyser")

    def _do():
        _config_mgr().update_geyser_config(**cleaned)
        _config_mgr().reload()
        app = _spotless_app()
        if app and getattr(app, "geyser_ctrl", None) is not None:
            try:
                app.geyser_ctrl.apply_config(_config_mgr().get_geyser_config())
            except Exception as e:
                logger.warning(f"admin: geyser hot-reload failed: {e}")
        logger.info(f"admin: geyser updated -> {cleaned}")

    return _safe_save(_do, "Geyser settings saved and applied.", "geyser")


@operator_admin_bp.route("/settings/roof_light", methods=["POST"])
@require_admin
def save_roof_light():
    payload = {
        k: request.form[k]
        for k in ("evening_on_time", "evening_off_time")
        if k in request.form
    }
    cleaned, err = validate_roof_light(payload)
    if err:
        flash(("error", err))
        return _redirect_back("roof")

    def _do():
        _config_mgr().update_roof_light_config(**cleaned)
        _config_mgr().reload()
        app = _spotless_app()
        if app and getattr(app, "roof_ctrl", None) is not None:
            try:
                app.roof_ctrl.apply_config(_config_mgr().get_roof_light_config())
            except Exception as e:
                logger.warning(f"admin: roof_light hot-reload failed: {e}")
        logger.info(f"admin: roof_light updated -> {cleaned}")

    return _safe_save(_do, "Roof light settings saved and applied.", "roof")


# =============================================================================
# JSON API (same logic as form handlers, for future automation / scripts)
# =============================================================================

@operator_admin_bp.route("/api/settings", methods=["GET"])
@require_admin
def api_get_settings():
    return jsonify(_all_settings())


@operator_admin_bp.route("/api/health", methods=["GET"])
@require_admin
def api_health():
    return jsonify(_health_snapshot())


def _json_payload() -> Dict[str, Any]:
    data = request.get_json(silent=True) or {}
    return data if isinstance(data, dict) else {}


def _api_save_failure(e: Exception):
    logger.exception("admin api: save failed")
    return jsonify({"ok": False, "error": f"Save failed: {e}"}), 500


@operator_admin_bp.route("/api/settings/profile/<profile_key>", methods=["PUT"])
@require_admin
def api_save_profile(profile_key: str):
    profile_key = profile_key.upper()
    if profile_key not in {"A", "B"}:
        return jsonify({"ok": False, "error": "unknown profile"}), 400
    cleaned, err = validate_size_profile(_json_payload())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        _config_mgr().update_size_profile(profile_key, **cleaned)
        _config_mgr().reload()
    except Exception as e:
        return _api_save_failure(e)
    logger.info(f"admin api: profile {profile_key} updated -> {cleaned}")
    return jsonify({"ok": True, "profile": _config_mgr().get_size_profile(profile_key)})


@operator_admin_bp.route("/api/settings/geyser", methods=["PUT"])
@require_admin
def api_save_geyser():
    cleaned, err = validate_geyser(_json_payload())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        _config_mgr().update_geyser_config(**cleaned)
        _config_mgr().reload()
    except Exception as e:
        return _api_save_failure(e)
    app = _spotless_app()
    if app and getattr(app, "geyser_ctrl", None) is not None:
        try:
            app.geyser_ctrl.apply_config(_config_mgr().get_geyser_config())
        except Exception as e:
            logger.warning(f"admin api: geyser hot-reload failed: {e}")
    return jsonify({"ok": True, "geyser": _config_mgr().get_geyser_config()})


@operator_admin_bp.route("/api/settings/roof_light", methods=["PUT"])
@require_admin
def api_save_roof_light():
    cleaned, err = validate_roof_light(_json_payload())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        _config_mgr().update_roof_light_config(**cleaned)
        _config_mgr().reload()
    except Exception as e:
        return _api_save_failure(e)
    app = _spotless_app()
    if app and getattr(app, "roof_ctrl", None) is not None:
        try:
            app.roof_ctrl.apply_config(_config_mgr().get_roof_light_config())
        except Exception as e:
            logger.warning(f"admin api: roof_light hot-reload failed: {e}")
    return jsonify({"ok": True, "roof_light": _config_mgr().get_roof_light_config()})


@operator_admin_bp.route("/api/settings/machine_info", methods=["PUT"])
@require_admin
def api_save_machine_info():
    cleaned, err = validate_machine_info(_json_payload())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        _config_mgr().update_machine_info(**cleaned)
        cfg = _config_mgr().reload()
    except Exception as e:
        return _api_save_failure(e)
    return jsonify({"ok": True, "machine": _machine_info(cfg)})
