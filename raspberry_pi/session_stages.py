"""
=============================================================================
Session Stage Definitions - Project Spotless (Contract v1.1)
=============================================================================
Single source of truth for session stages. Implements the target spec in
docs/INTEGRATION_CONTRACT.md v1.1 sections 5, 6, 10.

There are TWO size profiles (SET A, SET B) and TWO machine modes
(FULL_SESSION, DRYER_ONLY). Packages route as follows:

  Packages -> mode
    bath_pkg / complete_pkg / diy_bath / indie_special -> FULL_SESSION
    just_dry                                           -> DRYER_ONLY (~5 min, NEW v1.1.1)
    addon_only + extra_dry                             -> DRYER_ONLY (legacy, kept for back-compat)
    trim_pkg                                           -> REFUSED (staff-only)
    addon_only without extra_dry                       -> REFUSED

  Add-on modifiers (only valid on FULL_SESSION packages):
    `med_bath`   swaps the **shampoo** stage pump from p1 -> p3.
    `extra_dry`  adds +300s to the dryer total in FULL_SESSION.
                 (Server-side guarantees `extra_dry` never appears on
                  just_dry per mg_addons.applicable_packages.)

Disinfectant is **always** part of FULL_SESSION (no `pr=10/20` flag any more).

Stage dict fields:
    name          - Internal identifier (unique within session)
    label         - Display label for the kiosk UI
    duration      - Stage budget in seconds (anti-fraud accounting)
    image         - Image filename for the kiosk UI
    devices_on    - List of device names to turn ON (from device_map).
                    Supports MQTT devices (p1, s8, pump, etc.) and
                    GPIO devices prefixed with "gpio:" (gpio:dry, gpio:roof).
    parallel_pump - Optional dict: {"device": "p1", "duration": 30}
                    Runs a peristaltic pump in parallel (non-blocking).
    audio         - Optional audio key to play at stage start.
    beep_end      - If True, play beep sequence at stage end.
    show_timer    - If True (default), show countdown on kiosk. False hides it.
    accounting    - "relays" (default for stages with devices_on) or
                    "wallclock" (default for prompt stages with devices_on=[]).
                    See contract section 6.4 + 6.6.

Public API:
    build_session(size, package, addons) -> {mode, profile, stages, ...}
    get_stages(session_type)             - legacy lookup for test prefix codes
    get_total_duration(session_type)     - sum of stage durations
    get_stage_summary(session_type)      - compact list for kiosk preview
=============================================================================
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Audio key reference (matches spotless_controller.py AUDIO_FILES)
# =============================================================================
# welcome, onboard, shampoo, water, conditioner, water2, towel, dryer,
# break, offboard, laststep, disinfect, thankyou, massage, beep, powerdown

# =============================================================================
# Size profiles (SET A, SET B) - contract section 6.1
# =============================================================================
# These are the DEFAULT values. config_manager.get_size_profile() may override
# any of them from config.json. Tuning never requires editing this file.

DEFAULT_PROFILES: Dict[str, Dict[str, int]] = {
    "A": {
        "sval":      80,    # shampoo spray
        "cval":      80,    # conditioner spray
        "wval":      60,    # water rinse (final rinse is 2 * wval)
        "dval":      60,    # disinfectant spray
        "dryval":   600,    # dryer total (split into two phases)
        "fval":      60,    # autoflush per phase
        "wt":        30,    # peristaltic pump run (~30 mL)
        "msgval":    30,    # massage / soak wait
        "tdry":      30,    # towel dry wait
        "prime_fill":   30,
        "prime_empty":   6,
        "prime_empty_2": 12,  # second prime is slightly longer
    },
    "B": {
        "sval":     120,
        "cval":     120,
        "wval":      90,
        "dval":      60,
        "dryval":   800,
        "fval":      60,
        "wt":        60,    # ~60 mL for XL pets
        "msgval":    30,
        "tdry":      30,
        "prime_fill":   30,
        "prime_empty":   6,
        "prime_empty_2": 12,
    },
}

# =============================================================================
# Size -> Profile mapping (contract section 5.2)
# =============================================================================
SIZE_TO_PROFILE: Dict[str, str] = {
    "small":        "A",
    "medium":       "A",
    "medium_large": "A",
    "large":        "A",
    "indie":        "A",
    "xl":           "B",
}


def size_to_profile(size: Optional[str]) -> str:
    """Map a pets.size value to a profile key. Falls back to 'A' + warning."""
    if not size:
        logger.warning("size_to_profile: empty/None size, defaulting to A")
        return "A"
    norm = size.strip().lower()
    profile = SIZE_TO_PROFILE.get(norm)
    if profile is None:
        logger.warning("size_to_profile: unknown size %r, defaulting to A", size)
        return "A"
    return profile


# =============================================================================
# Device groups (cached labels for fluid lines)
# =============================================================================
SHAMPOO_LINE_DEVICES  = ["s8", "s1", "s2", "s4", "d1", "pump"]
DISINFECT_LINE_DEVICES = ["s8", "s3", "s4", "s2", "d2", "pump"]
WATER_LINE_DEVICES    = ["s8", "s5", "s2", "s4", "pump"]


# =============================================================================
# Shared stage fragments (reusable building blocks)
# =============================================================================

def _prompt_stage(name: str, label: str, duration: int, image: str,
                  audio: Optional[str] = None) -> Dict:
    """Build a relays-off prompt stage. Accounting is wallclock (contract 6.6)."""
    s: Dict = {
        "name": name,
        "label": label,
        "duration": duration,
        "image": image,
        "devices_on": [],
        "accounting": "wallclock",
    }
    if audio:
        s["audio"] = audio
    return s


def _relay_stage(name: str, label: str, duration: int, image: str,
                 devices_on: List[str], audio: Optional[str] = None,
                 parallel_pump: Optional[Dict] = None,
                 beep_end: bool = False,
                 show_timer: bool = True) -> Dict:
    """Build a relay-tracked stage. Accounting is relays (contract 6.4)."""
    s: Dict = {
        "name": name,
        "label": label,
        "duration": duration,
        "image": image,
        "devices_on": devices_on,
        "accounting": "relays",
        "show_timer": show_timer,
    }
    if audio:
        s["audio"] = audio
    if parallel_pump:
        s["parallel_pump"] = parallel_pump
    if beep_end:
        s["beep_end"] = True
    return s


def _prime_shampoo_stages(fill_dur: int, empty_dur: int,
                           suffix: str = "") -> List[Dict]:
    """Priming stages for Container 1 (shampoo / conditioner line).

    `suffix` makes stage names unique when prime stages are repeated within
    the same session (e.g. before shampoo + before conditioner). The
    executor uses stage names as the resume / completion key.
    """
    return [
        _relay_stage(f"prime_fill{suffix}",  "Preparing System", fill_dur,
                     "preparing.png", ["s8", "s1", "ro1"], show_timer=False),
        _relay_stage(f"prime_empty{suffix}", "Preparing System", empty_dur,
                     "preparing.png", ["d1", "ro2"], show_timer=False),
    ]


def _prime_disinfectant_stages(fill_dur: int, empty_dur: int) -> List[Dict]:
    """Priming stages for Container 2 (disinfectant line)."""
    return [
        _relay_stage("prime_dis_fill",  "Preparing Disinfectant", fill_dur,
                     "preparing.png", ["s8", "s3", "ro3"], show_timer=False),
        _relay_stage("prime_dis_empty", "Preparing Disinfectant", empty_dur,
                     "preparing.png", ["d2", "ro4"], show_timer=False),
    ]


def _drain_stages(dur: int) -> List[Dict]:
    """Post-session tank drain."""
    return [
        _relay_stage("drain_tanks", "Draining Tanks", dur,
                     "preparing.png", ["d1", "ro2", "d2", "ro4"],
                     show_timer=False),
    ]


def _flush_stages(dur: int) -> List[Dict]:
    """Autoflush - bottom first, then top (contract section 6.2)."""
    return [
        _relay_stage("flush_bottom", "Cleaning Tub - Bottom", dur,
                     "flush.png", ["flushmain", "bottom", "pump"]),
        _relay_stage("flush_top",    "Cleaning Tub - Top", dur,
                     "flush.png", ["flushmain", "top", "pump"]),
    ]


# =============================================================================
# FULL_SESSION builder - contract section 6.2
# =============================================================================
# This is the ONLY full-bath builder. Packages bath_pkg / complete_pkg /
# diy_bath / indie_special all use it. Add-ons modify it via parameters.

def _full_session_stages(profile_values: Dict[str, int],
                         shampoo_pump: str = "p1",
                         dryer_extra_seconds: int = 0) -> List[Dict]:
    """Build the full stage list for a pet bath session.

    Args:
        profile_values:      SET A or SET B dict from DEFAULT_PROFILES.
        shampoo_pump:        "p1" (regular) or "p3" (medicated / tick).
        dryer_extra_seconds: 0, or +300 if `extra_dry` add-on is present.
    """
    p = profile_values
    dryer_total = p["dryval"] + dryer_extra_seconds
    dryer_half  = dryer_total // 2
    # Phase 2 gets the remainder so total is exact.
    dryer_phase2 = dryer_total - dryer_half

    stages: List[Dict] = []

    # --- Priming ---
    stages.extend(_prime_shampoo_stages(p["prime_fill"], p["prime_empty"]))

    # --- Onboarding ---
    stages.append(_prompt_stage(
        "onboard", "Welcome - Please Place Pet in Tub",
        15, "welcome.png", audio="onboard",
    ))

    # --- Shampoo ---
    shampoo_label = "Shampoo Stage" if shampoo_pump == "p1" else "Medicated / Tick Shampoo"
    stages.append(_relay_stage(
        "shampoo", shampoo_label, p["sval"], "shampoo.png",
        SHAMPOO_LINE_DEVICES,
        parallel_pump={"device": shampoo_pump, "duration": p["wt"]},
        audio="shampoo", beep_end=True,
    ))

    # --- Massage 1 ---
    stages.append(_prompt_stage(
        "massage_1", "Massage Time - Lather the Shampoo",
        p["msgval"], "massage.png", audio="massage",
    ))

    # --- Water Rinse 1 ---
    stages.append(_relay_stage(
        "water_1", "Water Rinse", p["wval"], "water.png",
        WATER_LINE_DEVICES, audio="water", beep_end=True,
    ))

    # --- Re-prime for conditioner ---
    stages.extend(_prime_shampoo_stages(
        p["prime_fill"], p["prime_empty_2"], suffix="_2",
    ))

    # --- Conditioner (always p2) ---
    stages.append(_relay_stage(
        "conditioner", "Conditioner Stage", p["cval"], "conditioner.png",
        SHAMPOO_LINE_DEVICES,
        parallel_pump={"device": "p2", "duration": p["wt"]},
        audio="conditioner", beep_end=True,
    ))

    # --- Massage 2 ---
    stages.append(_prompt_stage(
        "massage_2", "Massage Time - Work in the Product",
        p["msgval"], "massage.png", audio="massage",
    ))

    # --- Final Rinse (2x duration) ---
    stages.append(_relay_stage(
        "water_2", "Final Rinse", p["wval"] * 2, "water.png",
        WATER_LINE_DEVICES, audio="water2", beep_end=True,
    ))

    # --- Towel Dry ---
    stages.append(_prompt_stage(
        "towel_dry", "Towel Dry - Please Pat Your Pet Dry",
        p["tdry"], "toweldry.png", audio="towel",
    ))

    # --- Dryer Phase 1 ---
    stages.append(_relay_stage(
        "dryer_phase1", "Drying - Phase 1", dryer_half, "drying.png",
        ["gpio:dry"], audio="dryer",
    ))

    # --- Dryer Break (prompt) ---
    stages.append(_prompt_stage(
        "dryer_break", "Quick Break", 15, "drying.png", audio="break",
    ))

    # --- Dryer Phase 2 ---
    stages.append(_relay_stage(
        "dryer_phase2", "Drying - Phase 2", dryer_phase2, "drying.png",
        ["gpio:dry"], beep_end=True,
    ))

    # --- Offboard ---
    stages.append(_prompt_stage(
        "offboard", "Please Remove Your Pet from the Tub",
        20, "complete.png", audio="offboard",
    ))

    # --- Disinfectant (ALWAYS included in v1.1) ---
    stages.extend(_prime_disinfectant_stages(12, 6))
    stages.append(_relay_stage(
        "disinfectant", "Disinfecting Tub", p["dval"], "disinfect.png",
        DISINFECT_LINE_DEVICES,
        parallel_pump={"device": "p4", "duration": int(p["wt"] * 0.8)},
        audio="disinfect",
    ))
    stages.append(_relay_stage(
        "disinfect_rinse", "Rinsing Disinfectant", p["dval"], "water.png",
        WATER_LINE_DEVICES, beep_end=True,
    ))

    # --- Drain ---
    stages.extend(_drain_stages(8))

    # --- Autoflush ---
    stages.extend(_flush_stages(p["fval"]))

    # --- Complete ---
    stages.append(_prompt_stage(
        "complete", "Session Complete - Thank You!",
        10, "complete.png", audio="thankyou",
    ))

    return stages


# =============================================================================
# DRYER_ONLY builder - contract section 6.3
# =============================================================================

def _dryer_only_stages(dryer_total: int = 600) -> List[Dict]:
    """Standalone dryer-only mode (addon_only package + extra_dry add-on)."""
    half = dryer_total // 2
    phase2 = dryer_total - half - 15  # subtract the 15s break
    if phase2 < 30:
        # Safety net for absurdly small totals
        phase2 = max(30, dryer_total - half - 15)
    return [
        _prompt_stage("onboard", "Welcome - Please Place Pet in Tub",
                      15, "welcome.png", audio="onboard"),
        _relay_stage("dryer_phase1", "Drying - Phase 1", half, "drying.png",
                     ["gpio:dry"], audio="dryer"),
        _prompt_stage("dryer_break", "Quick Break", 15, "drying.png",
                      audio="break"),
        _relay_stage("dryer_phase2", "Drying - Phase 2", phase2, "drying.png",
                     ["gpio:dry"], beep_end=True),
        _prompt_stage("offboard", "Please Remove Your Pet from the Tub",
                      20, "complete.png", audio="offboard"),
        _prompt_stage("complete", "Session Complete - Thank You!",
                      10, "complete.png", audio="thankyou"),
    ]


# =============================================================================
# Public entrypoint - resolve a booking to a MachineRequest
# =============================================================================

# Add-on codes the machine recognises (contract section 4.3)
MACHINE_ADDONS = {"med_bath", "extra_dry"}

# Standalone dryer-only product (frontend handover §3.5):
# "Just Dry — Dryer stage only. ~5 min default."
JUST_DRY_DURATION_SECONDS = 300

# Standalone DRYER_ONLY duration for the legacy addon_only + extra_dry combo.
# Kept at 10 min to match the v1.0 contract; not exposed in the new UI.
ADDON_ONLY_DURATION_SECONDS = 600


def _normalize_addons(addons) -> List[str]:
    """Accept None, '', 'a,b', or list -> normalized list of lowercase codes."""
    if not addons:
        return []
    if isinstance(addons, str):
        items = [a.strip().lower() for a in addons.split(",") if a.strip()]
    else:
        items = [str(a).strip().lower() for a in addons if str(a).strip()]
    # De-duplicate while preserving order
    seen, out = set(), []
    for a in items:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def build_session(size: Optional[str],
                  package: Optional[str],
                  addons,
                  profile_overrides: Optional[Dict[str, Dict[str, int]]] = None,
                  ) -> Dict:
    """Resolve (size, package, addons) -> MachineRequest dict.

    Args:
        size:    pets.size value ('small', 'medium', 'medium_large', 'large',
                 'xl', 'indie', or empty/None).
        package: bookings.session_type value ('bath_pkg', 'complete_pkg',
                 'diy_bath', 'indie_special', 'just_dry', 'addon_only',
                 'trim_pkg').
        addons:  CSV string or list of mg_addons.addon_code values.
        profile_overrides: optional dict { 'A': {...}, 'B': {...} } merged on
                 top of DEFAULT_PROFILES per-key. Use to load values from
                 config.json without mutating defaults.

    Returns:
        dict with keys:
            mode                  - "FULL_SESSION" | "DRYER_ONLY" | None (refused)
            profile               - "A" | "B"
            shampoo_pump          - "p1" | "p3" | None (for DRYER_ONLY)
            dryer_extra_seconds   - 0 or 300
            stages                - list of stage dicts (None if refused)
            addons_raw            - normalized add-on list that drove decisions
            non_machine_addons    - list of add-ons the machine ignored
            refused               - False on success, True on refuse
            refuse_code           - machine-readable refuse reason
            refuse_message        - human-readable refuse message
    """
    addons_list = _normalize_addons(addons)
    machine_addons = [a for a in addons_list if a in MACHINE_ADDONS]
    non_machine_addons = [a for a in addons_list if a not in MACHINE_ADDONS]

    # --- Step 1: Package check (contract section 5.1) ---
    pkg = (package or "").strip().lower()
    if pkg == "trim_pkg":
        return _refuse(
            "machine_does_not_serve_trim",
            "Trim is staff-only. Please proceed to the attendant.",
            addons_list, non_machine_addons,
        )

    # ---- just_dry: standalone dryer-only product (v1.1.1) ----
    if pkg == "just_dry":
        # Per frontend handover §3.5: dryer stage only, ~5 min default.
        # Server-side enforces that `extra_dry` cannot accompany just_dry
        # (mg_addons.applicable_packages excludes it). Defensive: even if a
        # stale row slipped through, we ignore extra_dry here.
        profile_key = size_to_profile(size)
        stages = _dryer_only_stages(JUST_DRY_DURATION_SECONDS)
        return {
            "mode": "DRYER_ONLY",
            "profile": profile_key,
            "shampoo_pump": None,
            "dryer_extra_seconds": 0,
            "stages": stages,
            "addons_raw": addons_list,
            "non_machine_addons": non_machine_addons,
            "refused": False,
            "refuse_code": None,
            "refuse_message": None,
        }

    # ---- addon_only: legacy DRYER_ONLY trigger (back-compat) ----
    # Today's frontend doesn't issue addon_only bookings anymore (they use
    # just_dry instead). Kept here so any historical addon_only + extra_dry
    # bookings still in flight can complete.
    if pkg == "addon_only":
        if "extra_dry" not in machine_addons:
            return _refuse(
                "no_machine_addons_selected",
                "This booking has no machine service - please see staff.",
                addons_list, non_machine_addons,
            )
        profile_key = size_to_profile(size)
        stages = _dryer_only_stages(ADDON_ONLY_DURATION_SECONDS)
        return {
            "mode": "DRYER_ONLY",
            "profile": profile_key,
            "shampoo_pump": None,
            "dryer_extra_seconds": 0,
            "stages": stages,
            "addons_raw": addons_list,
            "non_machine_addons": non_machine_addons,
            "refused": False,
            "refuse_code": None,
            "refuse_message": None,
        }

    if pkg not in {"bath_pkg", "complete_pkg", "diy_bath", "indie_special"}:
        return _refuse(
            "unknown_package",
            "Unknown package - please contact support.",
            addons_list, non_machine_addons,
        )

    # --- Step 2: Size profile (contract 5.2) ---
    if pkg == "indie_special":
        profile_key = "A"  # indie_special forces A regardless of size
    else:
        profile_key = size_to_profile(size)

    profile_values = dict(DEFAULT_PROFILES[profile_key])
    if profile_overrides and profile_key in profile_overrides:
        profile_values.update(profile_overrides[profile_key])

    # --- Step 3: Add-on application (contract 5.3) ---
    shampoo_pump = "p3" if "med_bath" in machine_addons else "p1"
    dryer_extra = 300 if "extra_dry" in machine_addons else 0

    stages = _full_session_stages(
        profile_values=profile_values,
        shampoo_pump=shampoo_pump,
        dryer_extra_seconds=dryer_extra,
    )

    return {
        "mode": "FULL_SESSION",
        "profile": profile_key,
        "shampoo_pump": shampoo_pump,
        "dryer_extra_seconds": dryer_extra,
        "stages": stages,
        "addons_raw": addons_list,
        "non_machine_addons": non_machine_addons,
        "refused": False,
        "refuse_code": None,
        "refuse_message": None,
    }


def _refuse(code: str, message: str, addons_list: List[str],
            non_machine_addons: List[str]) -> Dict:
    return {
        "mode": None,
        "profile": None,
        "shampoo_pump": None,
        "dryer_extra_seconds": 0,
        "stages": None,
        "addons_raw": addons_list,
        "non_machine_addons": non_machine_addons,
        "refused": True,
        "refuse_code": code,
        "refuse_message": message,
    }


# =============================================================================
# Legacy session types - kept for test-prefix codes and operator service mode
# =============================================================================
# These do NOT touch booking_sessions. They are debug / smoke-test sessions.
# Test prefix codes: SM, LG, TEST, DRY, WATER, FLUSH, SHAMP, DEMO, EMPTY.

def _wallclock_stage(name: str, label: str, duration: int, image: str,
                     devices_on: Optional[List[str]] = None,
                     audio: Optional[str] = None,
                     special_handler: Optional[str] = None) -> Dict:
    """Test-mode stage with wallclock accounting (do not use for real sessions)."""
    s: Dict = {
        "name": name,
        "label": label,
        "duration": duration,
        "image": image,
        "devices_on": devices_on or [],
        "accounting": "wallclock",
    }
    if audio:
        s["audio"] = audio
    if special_handler:
        s["special_handler"] = special_handler
    return s


SESSION_STAGES: Dict[str, List[Dict]] = {
    # ----- Real booking sessions exposed as test prefix codes -----
    "small":  _full_session_stages(DEFAULT_PROFILES["A"], "p1", 0),
    "large":  _full_session_stages(DEFAULT_PROFILES["B"], "p1", 0),

    # ----- Operator service-mode test sessions -----
    "quicktest": [
        _wallclock_stage("testing", "Testing All Relays", 90, "testing.png",
                         special_handler="test_relays"),
        _wallclock_stage("complete", "Test Complete", 5, "complete.png"),
    ],
    "onlydrying": [
        _relay_stage("dryer_phase1", "Drying - Phase 1", 285, "drying.png",
                     ["gpio:dry"], audio="dryer"),
        _prompt_stage("dryer_break", "Quick Break", 15, "drying.png"),
        _relay_stage("dryer_phase2", "Drying - Phase 2", 300, "drying.png",
                     ["gpio:dry"], beep_end=True),
        _wallclock_stage("complete", "Drying Complete", 5, "complete.png"),
    ],
    "onlywater": [
        _relay_stage("water", "Water Rinse", 90, "water.png",
                     WATER_LINE_DEVICES, beep_end=True),
        _wallclock_stage("complete", "Rinse Complete", 5, "complete.png"),
    ],
    "onlyflush": (
        _flush_stages(60)
        + [_wallclock_stage("complete", "Flush Complete", 5, "complete.png")]
    ),
    "onlyshampoo": (
        _prime_shampoo_stages(12, 6)
        + [
            _relay_stage(
                "shampoo", "Shampoo Only", 60, "shampoo.png",
                SHAMPOO_LINE_DEVICES,
                parallel_pump={"device": "p1", "duration": 10},
                beep_end=True,
            ),
            _wallclock_stage("complete", "Shampoo Complete", 5, "complete.png"),
        ]
    ),
    "onlydisinfectant": (
        _prime_disinfectant_stages(12, 6)
        + [
            _relay_stage(
                "disinfectant", "Disinfecting Tub", 60, "disinfect.png",
                DISINFECT_LINE_DEVICES,
                parallel_pump={"device": "p4", "duration": 12},
                audio="disinfect",
            ),
            _relay_stage(
                "disinfect_rinse", "Rinsing Disinfectant", 60, "water.png",
                WATER_LINE_DEVICES, beep_end=True,
            ),
        ]
        + _drain_stages(8)
        + _flush_stages(60)
        + [_wallclock_stage("complete", "Cleanup Complete", 10, "complete.png",
                            audio="thankyou")]
    ),
    "empty001": [
        _relay_stage("emptying", "Emptying Tank", 180, "preparing.png",
                     ["d1", "ro2"]),
        _wallclock_stage("complete", "Tank Empty", 5, "complete.png"),
    ],
    "demo": [
        _wallclock_stage("demo", "Demo Mode - Testing Relays", 200,
                         "testing.png", special_handler="demo"),
        _wallclock_stage("complete", "Demo Complete", 5, "complete.png"),
    ],
}


# =============================================================================
# Legacy lookup API (used by test prefix codes + kiosk preview)
# =============================================================================

def get_stages(session_type: str) -> List[Dict]:
    """Get stage list for a session type. Falls back to 'small' if unknown."""
    return SESSION_STAGES.get(session_type, SESSION_STAGES["small"])


def get_known_session_types() -> List[str]:
    """Return all session types that have stage definitions."""
    return list(SESSION_STAGES.keys())


def is_known_session_type(session_type: str) -> bool:
    """Check if a session type has a stage definition."""
    return session_type in SESSION_STAGES


def get_total_duration(session_type_or_stages) -> int:
    """Get the total duration in seconds for a session type or stage list."""
    if isinstance(session_type_or_stages, str):
        stages = get_stages(session_type_or_stages)
    else:
        stages = session_type_or_stages or []
    return sum(int(s.get("duration", 0)) for s in stages)


def get_stage_summary(session_type_or_stages) -> List[Dict]:
    """Get a compact summary of stages for kiosk display."""
    if isinstance(session_type_or_stages, str):
        stages = get_stages(session_type_or_stages)
    else:
        stages = session_type_or_stages or []
    # Return ALL stages (no show_timer filter) so the kiosk timeline indices
    # stay aligned with the executor's stage_index emits. See the matching
    # comment in raspberry_pi/kiosk/web_server.py::_kiosk_stage_preview.
    return [
        {
            "name": s["name"],
            "label": s["label"],
            "duration": s["duration"],
            "image": s.get("image", ""),
            "show_timer": bool(s.get("show_timer", True)),
        }
        for s in stages
    ]
