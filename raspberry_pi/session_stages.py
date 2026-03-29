"""
=============================================================================
Session Stage Definitions - Project Spotless
=============================================================================
Defines the UI stage sequences for each session type.

Each stage has:
    name     - Internal identifier
    label    - Display label for the kiosk UI
    duration - Duration in seconds (matches hardware timing)
    image    - Image filename for the kiosk UI

These are used by the session runner to drive the progress bar and by
the QR validator to check if a session type is known.
=============================================================================
"""

SESSION_STAGES = {
    "small": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Shampoo Stage", "duration": 120, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "conditioner", "label": "Conditioner Stage", "duration": 120, "image": "conditioner.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 480, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "large": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Shampoo Stage", "duration": 150, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 80, "image": "water.png"},
        {"name": "conditioner", "label": "Conditioner Stage", "duration": 150, "image": "conditioner.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 80, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 600, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "custdiy": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 15, "image": "preparing.png"},
        {"name": "shampoo", "label": "Shampoo Stage", "duration": 100, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "conditioner", "label": "Conditioner Stage", "duration": 100, "image": "conditioner.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 600, "image": "drying.png"},
        {"name": "disinfectant", "label": "Disinfectant", "duration": 60, "image": "disinfect.png"},
        {"name": "autoflush", "label": "Auto Flush", "duration": 120, "image": "flush.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "medsmall": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Medicated Shampoo", "duration": 80, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "medbath", "label": "Medicated Bath", "duration": 80, "image": "medbath.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 480, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "medlarge": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Medicated Shampoo", "duration": 100, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "medbath", "label": "Medicated Bath", "duration": 100, "image": "medbath.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 600, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "onlydisinfectant": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "disinfectant", "label": "Disinfecting Tub", "duration": 60, "image": "disinfect.png"},
        {"name": "autoflush", "label": "Auto Flush", "duration": 120, "image": "flush.png"},
        {"name": "complete", "label": "Cleanup Complete", "duration": 10, "image": "complete.png"},
    ],
    "quicktest": [
        {"name": "testing", "label": "Testing All Relays", "duration": 90, "image": "testing.png"},
        {"name": "complete", "label": "Test Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlydrying": [
        {"name": "drying", "label": "Drying Only", "duration": 300, "image": "drying.png"},
        {"name": "complete", "label": "Drying Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlywater": [
        {"name": "water", "label": "Water Rinse", "duration": 90, "image": "water.png"},
        {"name": "complete", "label": "Rinse Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlyflush": [
        {"name": "flush", "label": "Flushing System", "duration": 60, "image": "flush.png"},
        {"name": "complete", "label": "Flush Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlyshampoo": [
        {"name": "shampoo", "label": "Shampoo Only", "duration": 60, "image": "shampoo.png"},
        {"name": "complete", "label": "Shampoo Complete", "duration": 5, "image": "complete.png"},
    ],
    "empty001": [
        {"name": "emptying", "label": "Emptying Tank", "duration": 180, "image": "empty.png"},
        {"name": "complete", "label": "Tank Empty", "duration": 5, "image": "complete.png"},
    ],
    "demo": [
        {"name": "demo", "label": "Demo Mode - Testing Relays", "duration": 200, "image": "testing.png"},
        {"name": "complete", "label": "Demo Complete", "duration": 5, "image": "complete.png"},
    ],
}


def get_stages(session_type: str) -> list:
    """Get stage list for a session type, falling back to 'small' if unknown."""
    return SESSION_STAGES.get(session_type, SESSION_STAGES['small'])


def get_known_session_types() -> list:
    """Return all session types that have stage definitions."""
    return list(SESSION_STAGES.keys())


def is_known_session_type(session_type: str) -> bool:
    """Check if a session type has a stage definition."""
    return session_type in SESSION_STAGES
