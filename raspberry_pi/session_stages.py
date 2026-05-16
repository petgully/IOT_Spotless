"""
=============================================================================
Session Stage Definitions - Project Spotless
=============================================================================
Single source of truth for session stages.

Each stage defines BOTH the hardware relay pattern AND the UI display info.
The StageExecutor reads these and drives relays + kiosk timer from one loop.

Stage dict fields:
    name          - Internal identifier (unique within session)
    label         - Display label for the kiosk UI
    duration      - Duration in seconds
    image         - Image filename for the kiosk UI
    devices_on    - List of device names to turn ON (from device_map)
                    Supports both MQTT devices (p1, s8, pump, etc.) and
                    GPIO devices prefixed with "gpio:" (gpio:dry, gpio:roof)
    parallel_pump - Optional dict: {"device": "p1", "duration": 30}
                    Runs a peristaltic pump in parallel (non-blocking)
    audio         - Optional audio key to play at stage start
    beep_end      - If True, play beep sequence at stage end
    show_timer    - If True (default), show countdown on kiosk. False hides it.

To customize timings, edit the stage durations in the config or override
from the database. The code (StageExecutor) never changes — only the data.
=============================================================================
"""

# =============================================================================
# Audio key reference (matches spotless_controller.py AUDIO_FILES)
# =============================================================================
# welcome, onboard, shampoo, water, conditioner, water2, towel, dryer,
# break, offboard, laststep, disinfect, thankyou, massage, beep, powerdown

# =============================================================================
# Shared stage fragments (reusable building blocks)
# =============================================================================

def _prime_shampoo_stages(fill_dur=30, empty_dur=6):
    """Priming stages for Container 1 (shampoo/conditioner line)."""
    return [
        {
            "name": "prime_fill",
            "label": "Preparing System",
            "duration": fill_dur,
            "image": "preparing.png",
            "devices_on": ["s8", "s1", "ro1"],
            "show_timer": False,
        },
        {
            "name": "prime_empty",
            "label": "Preparing System",
            "duration": empty_dur,
            "image": "preparing.png",
            "devices_on": ["d1", "ro2"],
            "show_timer": False,
        },
    ]


def _prime_disinfectant_stages(fill_dur=12, empty_dur=6):
    """Priming stages for Container 2 (disinfectant line)."""
    return [
        {
            "name": "prime_dis_fill",
            "label": "Preparing Disinfectant",
            "duration": fill_dur,
            "image": "preparing.png",
            "devices_on": ["s8", "s3", "ro3"],
            "show_timer": False,
        },
        {
            "name": "prime_dis_empty",
            "label": "Preparing Disinfectant",
            "duration": empty_dur,
            "image": "preparing.png",
            "devices_on": ["d2", "ro4"],
            "show_timer": False,
        },
    ]


def _drain_stages(dur=8):
    """Post-session tank drain."""
    return [
        {
            "name": "drain_tanks",
            "label": "Draining Tanks",
            "duration": dur,
            "image": "preparing.png",
            "devices_on": ["d1", "ro2", "d2", "ro4"],
            "show_timer": False,
        },
    ]


def _flush_stages(dur=60):
    """Autoflush — bottom first, then top."""
    return [
        {
            "name": "flush_bottom",
            "label": "Cleaning Tub — Bottom",
            "duration": dur,
            "image": "flush.png",
            "devices_on": ["flushmain", "bottom", "pump"],
        },
        {
            "name": "flush_top",
            "label": "Cleaning Tub — Top",
            "duration": dur,
            "image": "flush.png",
            "devices_on": ["flushmain", "top", "pump"],
        },
    ]


# =============================================================================
# Full Bath Session Stages
# =============================================================================

SHAMPOO_LINE_DEVICES = ["s8", "s1", "s2", "s4", "d1", "pump"]
DISINFECT_LINE_DEVICES = ["s8", "s3", "s4", "s2", "d2", "pump"]
WATER_LINE_DEVICES = ["s8", "s5", "s2", "s4", "pump"]


def _full_bath_stages(
    sval, cval, dval, wval, dryval, fval,
    wt, msgval, tdry, pr,
    ctype=100, prime_fill=30, prime_empty=6,
):
    """
    Build the full stage list for a pet bath session.

    Args:
        sval:  Shampoo spray duration (seconds)
        cval:  Conditioner spray duration (seconds)
        dval:  Disinfectant spray duration (seconds)
        wval:  Water rinse duration (seconds)
        dryval: Dryer duration (seconds, split into two phases)
        fval:  Flush duration per phase (seconds)
        wt:    Peristaltic pump run time (seconds)
        msgval: Massage/soak wait time (seconds)
        tdry:  Towel dry wait time (seconds)
        pr:    Include disinfectant stage (10 = yes, 20 = no)
        ctype: Conditioner type (100 = normal, 200 = medicated)
        prime_fill: Priming fill duration
        prime_empty: Priming empty duration
    """
    cond_pump = "p2" if ctype == 100 else "p3"
    cond_label = "Conditioner Stage" if ctype == 100 else "Medicated Shampoo"
    cond_audio = "conditioner"
    dryer_half = int(dryval * 0.5)

    stages = []

    # --- Priming ---
    stages.extend(_prime_shampoo_stages(prime_fill, prime_empty))

    # --- Onboarding ---
    stages.append({
        "name": "onboard",
        "label": "Welcome — Please Place Pet in Tub",
        "duration": 15,
        "image": "welcome.png",
        "devices_on": [],
        "audio": "onboard",
    })

    # --- Shampoo ---
    stages.append({
        "name": "shampoo",
        "label": "Shampoo Stage",
        "duration": sval,
        "image": "shampoo.png",
        "devices_on": SHAMPOO_LINE_DEVICES,
        "parallel_pump": {"device": "p1", "duration": wt},
        "audio": "shampoo",
        "beep_end": True,
    })

    # --- Massage 1 ---
    stages.append({
        "name": "massage_1",
        "label": "Massage Time — Lather the Shampoo",
        "duration": msgval,
        "image": "massage.png",
        "devices_on": [],
        "audio": "massage",
    })

    # --- Water Rinse 1 ---
    stages.append({
        "name": "water_1",
        "label": "Water Rinse",
        "duration": wval,
        "image": "water.png",
        "devices_on": WATER_LINE_DEVICES,
        "audio": "water",
        "beep_end": True,
    })

    # --- Re-prime for conditioner ---
    stages.extend(_prime_shampoo_stages(prime_fill, 12))

    # --- Conditioner / Medicated Bath ---
    stages.append({
        "name": "conditioner",
        "label": cond_label,
        "duration": cval,
        "image": "conditioner.png",
        "devices_on": SHAMPOO_LINE_DEVICES,
        "parallel_pump": {"device": cond_pump, "duration": wt},
        "audio": cond_audio,
        "beep_end": True,
    })

    # --- Massage 2 ---
    stages.append({
        "name": "massage_2",
        "label": "Massage Time — Work in the Product",
        "duration": msgval,
        "image": "massage.png",
        "devices_on": [],
        "audio": "massage",
    })

    # --- Water Rinse 2 (double duration) ---
    stages.append({
        "name": "water_2",
        "label": "Final Rinse",
        "duration": wval * 2,
        "image": "water.png",
        "devices_on": WATER_LINE_DEVICES,
        "audio": "water2",
        "beep_end": True,
    })

    # --- Towel Dry ---
    stages.append({
        "name": "towel_dry",
        "label": "Towel Dry — Please Pat Your Pet Dry",
        "duration": tdry,
        "image": "toweldry.png",
        "devices_on": [],
        "audio": "towel",
    })

    # --- Dryer Phase 1 ---
    stages.append({
        "name": "dryer_phase1",
        "label": "Drying — Phase 1",
        "duration": dryer_half,
        "image": "drying.png",
        "devices_on": ["gpio:dry"],
        "audio": "dryer",
    })

    # --- Dryer Break ---
    stages.append({
        "name": "dryer_break",
        "label": "Quick Break",
        "duration": 15,
        "image": "drying.png",
        "devices_on": [],
        "audio": "break",
    })

    # --- Dryer Phase 2 ---
    stages.append({
        "name": "dryer_phase2",
        "label": "Drying — Phase 2",
        "duration": dryer_half,
        "image": "drying.png",
        "devices_on": ["gpio:dry"],
        "beep_end": True,
    })

    # --- Offboard ---
    stages.append({
        "name": "offboard",
        "label": "Please Remove Your Pet from the Tub",
        "duration": 20,
        "image": "complete.png",
        "devices_on": [],
        "audio": "offboard",
    })

    # --- Disinfectant (if pr == 10) ---
    if pr == 10:
        stages.extend(_prime_disinfectant_stages(12, 6))
        stages.append({
            "name": "disinfectant",
            "label": "Disinfecting Tub",
            "duration": dval,
            "image": "disinfect.png",
            "devices_on": DISINFECT_LINE_DEVICES,
            "parallel_pump": {"device": "p4", "duration": int(wt * 0.8)},
            "audio": "disinfect",
        })
        stages.append({
            "name": "disinfect_rinse",
            "label": "Rinsing Disinfectant",
            "duration": dval,
            "image": "water.png",
            "devices_on": WATER_LINE_DEVICES,
            "beep_end": True,
        })

    # --- Drain tanks ---
    stages.extend(_drain_stages(8))

    # --- Autoflush ---
    stages.extend(_flush_stages(fval))

    # --- Complete ---
    stages.append({
        "name": "complete",
        "label": "Session Complete — Thank You!",
        "duration": 10,
        "image": "complete.png",
        "devices_on": [],
        "audio": "thankyou",
    })

    return stages


# =============================================================================
# Pre-built Session Types
# =============================================================================
SESSION_STAGES = {
    "small": _full_bath_stages(
        sval=80, cval=80, dval=60, wval=60, dryval=480, fval=60,
        wt=30, msgval=30, tdry=30, pr=20, ctype=100,
    ),
    "large": _full_bath_stages(
        sval=100, cval=100, dval=60, wval=60, dryval=600, fval=60,
        wt=50, msgval=30, tdry=30, pr=20, ctype=100,
    ),
    "custdiy": _full_bath_stages(
        sval=100, cval=100, dval=60, wval=60, dryval=600, fval=60,
        wt=12, msgval=30, tdry=30, pr=10, ctype=100,
    ),
    "medsmall": _full_bath_stages(
        sval=80, cval=80, dval=60, wval=60, dryval=480, fval=60,
        wt=30, msgval=30, tdry=30, pr=20, ctype=200,
    ),
    "medlarge": _full_bath_stages(
        sval=100, cval=100, dval=60, wval=60, dryval=600, fval=60,
        wt=50, msgval=30, tdry=30, pr=20, ctype=200,
    ),
    "onlydisinfectant": (
        _prime_disinfectant_stages(12, 6)
        + [
            {
                "name": "disinfectant",
                "label": "Disinfecting Tub",
                "duration": 60,
                "image": "disinfect.png",
                "devices_on": DISINFECT_LINE_DEVICES,
                "parallel_pump": {"device": "p4", "duration": 12},
                "audio": "disinfect",
            },
            {
                "name": "disinfect_rinse",
                "label": "Rinsing Disinfectant",
                "duration": 60,
                "image": "water.png",
                "devices_on": WATER_LINE_DEVICES,
                "beep_end": True,
            },
        ]
        + _drain_stages(8)
        + _flush_stages(60)
        + [
            {
                "name": "complete",
                "label": "Cleanup Complete",
                "duration": 10,
                "image": "complete.png",
                "devices_on": [],
                "audio": "thankyou",
            },
        ]
    ),

    # =========================================================================
    # Utility / Test Sessions
    # =========================================================================
    "quicktest": [
        {
            "name": "testing",
            "label": "Testing All Relays",
            "duration": 90,
            "image": "testing.png",
            "devices_on": [],
            "special_handler": "test_relays",
        },
        {"name": "complete", "label": "Test Complete", "duration": 5,
         "image": "complete.png", "devices_on": []},
    ],
    "onlydrying": [
        {
            "name": "dryer_phase1",
            "label": "Drying — Phase 1",
            "duration": 150,
            "image": "drying.png",
            "devices_on": ["gpio:dry"],
            "audio": "dryer",
        },
        {
            "name": "dryer_break",
            "label": "Quick Break",
            "duration": 15,
            "image": "drying.png",
            "devices_on": [],
        },
        {
            "name": "dryer_phase2",
            "label": "Drying — Phase 2",
            "duration": 150,
            "image": "drying.png",
            "devices_on": ["gpio:dry"],
            "beep_end": True,
        },
        {"name": "complete", "label": "Drying Complete", "duration": 5,
         "image": "complete.png", "devices_on": []},
    ],
    "onlywater": [
        {
            "name": "water",
            "label": "Water Rinse",
            "duration": 90,
            "image": "water.png",
            "devices_on": WATER_LINE_DEVICES,
            "beep_end": True,
        },
        {"name": "complete", "label": "Rinse Complete", "duration": 5,
         "image": "complete.png", "devices_on": []},
    ],
    "onlyflush": (
        _flush_stages(60)
        + [{"name": "complete", "label": "Flush Complete", "duration": 5,
            "image": "complete.png", "devices_on": []}]
    ),
    "onlyshampoo": (
        _prime_shampoo_stages(12, 6)
        + [
            {
                "name": "shampoo",
                "label": "Shampoo Only",
                "duration": 60,
                "image": "shampoo.png",
                "devices_on": SHAMPOO_LINE_DEVICES,
                "parallel_pump": {"device": "p1", "duration": 10},
                "beep_end": True,
            },
            {"name": "complete", "label": "Shampoo Complete", "duration": 5,
             "image": "complete.png", "devices_on": []},
        ]
    ),
    "empty001": [
        {
            "name": "emptying",
            "label": "Emptying Tank",
            "duration": 180,
            "image": "preparing.png",
            "devices_on": ["d1", "ro2"],
        },
        {"name": "complete", "label": "Tank Empty", "duration": 5,
         "image": "complete.png", "devices_on": []},
    ],
    "demo": [
        {
            "name": "demo",
            "label": "Demo Mode — Testing Relays",
            "duration": 200,
            "image": "testing.png",
            "devices_on": [],
            "special_handler": "demo",
        },
        {"name": "complete", "label": "Demo Complete", "duration": 5,
         "image": "complete.png", "devices_on": []},
    ],
}


# =============================================================================
# Public API
# =============================================================================

def get_stages(session_type: str) -> list:
    """Get stage list for a session type, falling back to 'small' if unknown."""
    return SESSION_STAGES.get(session_type, SESSION_STAGES["small"])


def get_known_session_types() -> list:
    """Return all session types that have stage definitions."""
    return list(SESSION_STAGES.keys())


def is_known_session_type(session_type: str) -> bool:
    """Check if a session type has a stage definition."""
    return session_type in SESSION_STAGES


def get_total_duration(session_type: str) -> int:
    """Get the total duration in seconds for a session type."""
    stages = get_stages(session_type)
    return sum(s.get("duration", 0) for s in stages)


def get_stage_summary(session_type: str) -> list:
    """Get a compact summary of stages for display."""
    stages = get_stages(session_type)
    return [
        {
            "name": s["name"],
            "label": s["label"],
            "duration": s["duration"],
            "image": s.get("image", ""),
        }
        for s in stages
        if s.get("show_timer", True)
    ]
