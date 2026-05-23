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


def _health_snapshot() -> Dict[str, Any]:
    """Live system health for the dashboard. All probes are best-effort —
    a missing controller in dev mode must NOT 500 the page."""
    app = _spotless_app()
    health: Dict[str, Any] = {
        "nodes": {},
        "nodes_online": 0,
        "nodes_total": 0,
        "session_active": False,
        "current_session": None,
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
        if controller is not None:
            states = controller.get_all_node_states() if hasattr(controller, "get_all_node_states") else {}
            health["nodes"] = states or {}
            health["nodes_total"] = len(states or {}) or 3
            health["nodes_online"] = sum(
                1 for v in (states or {}).values()
                if (v is True) or (isinstance(v, dict) and v.get("online"))
            )
    except Exception as e:
        logger.warning(f"admin health: node states unavailable: {e}")

    try:
        runner = getattr(app, "runner", None)
        if runner is not None:
            health["session_active"] = bool(runner.is_active)
            health["current_session"] = runner.current_session
    except Exception:
        pass

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
