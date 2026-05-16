"""
=============================================================================
Stage Executor - Project Spotless
=============================================================================
Data-driven bath controller. Reads stage configs (from session_stages.py /
config_manager.py) and executes them: turns on relays, counts down while
emitting progress events, turns off relays.

ONE function (execute_stage) replaces all the old individual functions
(Shampoo, Water, Conditioner, Dryer, etc.).  The complexity lives entirely
in the stage config data — the executor itself is simple and generic.

Device name conventions in stage configs:
    "p1", "s8", "pump"  → MQTT device (via DeviceController)
    "gpio:dry"          → Direct Raspberry Pi GPIO (via GPIOController)
=============================================================================
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Audio
# =============================================================================
AUDIO_BASE_PATH = "/home/spotless/Downloads/V3_Spotless"

AUDIO_FILES = {
    "welcome":     f"{AUDIO_BASE_PATH}/Voiceover/1_Welcome.mp3",
    "onboard":     f"{AUDIO_BASE_PATH}/Voiceover/2_Onboard.mp3",
    "shampoo":     f"{AUDIO_BASE_PATH}/Voiceover/3_Shampoo.mp3",
    "water":       f"{AUDIO_BASE_PATH}/Voiceover/4_Water.mp3",
    "conditioner": f"{AUDIO_BASE_PATH}/Voiceover/5_Condition.mp3",
    "water2":      f"{AUDIO_BASE_PATH}/Voiceover/6_Water.mp3",
    "towel":       f"{AUDIO_BASE_PATH}/Voiceover/7_Towel.mp3",
    "dryer":       f"{AUDIO_BASE_PATH}/Voiceover/8_Dryer.mp3",
    "break":       f"{AUDIO_BASE_PATH}/Voiceover/9_Break.mp3",
    "offboard":    f"{AUDIO_BASE_PATH}/Voiceover/10_Offboard.mp3",
    "laststep":    f"{AUDIO_BASE_PATH}/Voiceover/11_laststep.mp3",
    "disinfect":   f"{AUDIO_BASE_PATH}/Voiceover/12_Disinfect.mp3",
    "thankyou":    f"{AUDIO_BASE_PATH}/Voiceover/13_Thankyou.mp3",
    "massage":     f"{AUDIO_BASE_PATH}/Voiceover/Massage.mp3",
    "beep":        f"{AUDIO_BASE_PATH}/Mus/Beep.mp3",
    "powerdown":   f"{AUDIO_BASE_PATH}/Mus/Powerdown.mp3",
    "music_8h":    f"{AUDIO_BASE_PATH}/Mus/8_hours.mp3",
}

# Type alias for the event callback: callback(event_name, data) -> None
EventCallback = Callable[[str, Dict], None]

def _noop(*_args, **_kwargs):
    pass


class StageExecutor:
    """
    Executes a list of stages, driving hardware and emitting UI events.

    Usage:
        executor = StageExecutor(device_controller, gpio_controller)
        executor.run_session(stages, emit=socketio_emit)
        executor.stop()  # emergency stop
    """

    def __init__(self, device_controller, gpio_controller):
        """
        Args:
            device_controller: DeviceController instance (MQTT relays)
            gpio_controller:   GPIOController instance (RPi GPIO relays)
        """
        self.devices = device_controller
        self.gpio = gpio_controller
        self._running = False
        self._current_stage: Optional[Dict] = None

    # =========================================================================
    # Public API
    # =========================================================================

    def run_session(self, stages: List[Dict],
                    emit: EventCallback = None) -> bool:
        """
        Execute a full session (list of stages) sequentially.

        Args:
            stages: Ordered list of stage dicts from session_stages.py
            emit:   Callback(event_name, data) for UI updates

        Returns True if all stages completed, False if stopped or errored.
        """
        emit = emit or _noop
        self._running = True
        total_stages = len(stages)

        logger.info("=" * 60)
        logger.info(f"SESSION START — {total_stages} stages")
        logger.info("=" * 60)

        try:
            for i, stage in enumerate(stages):
                if not self._running:
                    logger.warning("Session stopped by user")
                    return False

                success = self._execute_stage(stage, i, total_stages, emit)
                if not success and not self._running:
                    return False

            logger.info("=" * 60)
            logger.info("SESSION COMPLETE")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"Session error: {e}", exc_info=True)
            self.all_off()
            return False
        finally:
            self._running = False
            self._current_stage = None

    def stop(self):
        """Emergency stop — turns off all devices immediately."""
        self._running = False
        self.all_off()
        logger.warning("EMERGENCY STOP — all devices off")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_stage(self) -> Optional[Dict]:
        return self._current_stage

    # =========================================================================
    # Core Stage Execution
    # =========================================================================

    def _execute_stage(self, stage: Dict, index: int,
                       total: int, emit: EventCallback) -> bool:
        """
        Execute a single stage:
          1. Play audio cue (non-blocking)
          2. Start parallel pump if specified
          3. Turn ON devices from devices_on list
          4. Countdown loop — emit progress every second
          5. Turn OFF devices
          6. Beep if beep_end is set
        """
        name = stage.get("name", "unknown")
        label = stage.get("label", name)
        duration = stage.get("duration", 0)
        devices_on = stage.get("devices_on", [])
        parallel_pump = stage.get("parallel_pump")
        audio_key = stage.get("audio")
        beep_end = stage.get("beep_end", False)
        image = stage.get("image", "")
        special = stage.get("special_handler")

        self._current_stage = stage

        logger.info(f"  [{index+1}/{total}] {name}: {duration}s "
                     f"devices={devices_on}")

        # --- Special handler (test_relays, demo) ---
        if special:
            emit("stage_start", {
                "stage_index": index, "stage_name": name,
                "stage_label": label, "stage_duration": duration,
                "stage_image": image, "total_stages": total,
            })
            self._run_special(special, duration, index, total, emit)
            emit("stage_complete", {"stage_index": index, "stage_name": name})
            return True

        # --- 1. Audio cue ---
        if audio_key:
            self._play_audio_async(audio_key)

        # --- 2. Parallel pump ---
        if parallel_pump:
            pump_dev = parallel_pump.get("device", "")
            pump_dur = parallel_pump.get("duration", 0)
            if pump_dev and pump_dur > 0:
                self._pump_async(pump_dev, pump_dur)

        # --- 3. Turn ON devices ---
        self._set_devices(devices_on, True)

        # --- 4. Emit stage_start ---
        emit("stage_start", {
            "stage_index": index,
            "stage_name": name,
            "stage_label": label,
            "stage_duration": duration,
            "stage_image": image,
            "total_stages": total,
        })

        # --- 5. Countdown loop ---
        for second in range(duration):
            if not self._running:
                self._set_devices(devices_on, False)
                return False

            remaining = duration - second - 1
            progress = int((second + 1) / max(duration, 1) * 100)

            emit("stage_progress", {
                "stage_index": index,
                "stage_name": name,
                "progress": progress,
                "elapsed": second + 1,
                "remaining": remaining,
                "total_duration": duration,
            })
            time.sleep(1)

        # --- 6. Turn OFF devices ---
        self._set_devices(devices_on, False)

        # --- 7. Beep ---
        if beep_end:
            self._beep()

        emit("stage_complete", {"stage_index": index, "stage_name": name})
        return True

    # =========================================================================
    # Device Control Helpers
    # =========================================================================

    def _set_devices(self, device_names: List[str], state: bool):
        """Turn a list of devices ON or OFF. Handles gpio: prefix."""
        for name in device_names:
            try:
                if name.startswith("gpio:"):
                    gpio_name = name[5:]
                    relay = self.gpio.get_relay(gpio_name)
                    if relay:
                        relay.set(state)
                    else:
                        logger.warning(f"Unknown GPIO device: {gpio_name}")
                else:
                    handle = self.devices.get(name)
                    if handle:
                        handle.set(state)
                    else:
                        logger.warning(f"Unknown MQTT device: {name}")
            except Exception as e:
                logger.error(f"Error setting {name} to {state}: {e}")

    def all_off(self):
        """Turn off all MQTT and GPIO devices."""
        logger.warning("ALL OFF — shutting down all devices")
        try:
            self.devices.all_off()
        except Exception as e:
            logger.error(f"Error in MQTT all_off: {e}")
        try:
            self.gpio.all_off()
        except Exception as e:
            logger.error(f"Error in GPIO all_off: {e}")

    # =========================================================================
    # Pump / Audio Helpers
    # =========================================================================

    def _pump_async(self, device_name: str, duration: float):
        """Run a peristaltic pump in a background thread."""
        def _run():
            handle = self.devices.get(device_name)
            if handle:
                logger.info(f"  Parallel pump {device_name}: ON for {duration}s")
                handle.on()
                time.sleep(duration)
                handle.off()
                logger.info(f"  Parallel pump {device_name}: OFF")
            else:
                logger.warning(f"Unknown pump device: {device_name}")

        threading.Thread(target=_run, daemon=True).start()

    def _play_audio_async(self, audio_key: str):
        """Play an audio file in the background."""
        path = AUDIO_FILES.get(audio_key)
        if path:
            cmd = f"cvlc {path} vlc://quit"
            threading.Thread(
                target=lambda: os.system(cmd), daemon=True
            ).start()

    def _beep(self, count: int = 6, interval: float = 0.5):
        beep_path = AUDIO_FILES.get("beep")
        if beep_path:
            for _ in range(count):
                os.system(f"cvlc {beep_path} vlc://quit")
                time.sleep(interval)

    def _kill_audio(self):
        os.system("killall vlc 2>/dev/null")

    # =========================================================================
    # Special Handlers (test_relays, demo)
    # =========================================================================

    def _run_special(self, handler: str, duration: int,
                     index: int, total: int, emit: EventCallback):
        """Run a special handler that needs custom device sequencing."""
        if handler == "test_relays":
            self._test_relays_sequence(index, total, emit)
        elif handler == "demo":
            self._demo_sequence(index, total, emit)
        else:
            logger.warning(f"Unknown special handler: {handler}")
            time.sleep(duration)

    def _test_relays_sequence(self, index: int, total: int,
                              emit: EventCallback):
        all_mqtt = [
            "p1", "p2", "p3", "p4", "p5",
            "ro1", "ro2", "ro3", "ro4",
            "d1", "d2",
            "s1", "s2", "s3", "s4", "s5",
            "top", "bottom", "flushmain", "s8",
            "pump",
        ]
        gpio_names = ["dry", "roof", "geyser", "rglight"]
        all_items = [(n, "mqtt") for n in all_mqtt] + [(n, "gpio") for n in gpio_names]
        total_items = len(all_items)

        for i, (name, kind) in enumerate(all_items):
            if not self._running:
                return
            logger.info(f"  Test: {name} ({kind})")
            if kind == "mqtt":
                h = self.devices.get(name)
                if h:
                    h.on()
            else:
                r = self.gpio.get_relay(name)
                if r:
                    r.on()

            time.sleep(2)

            if kind == "mqtt":
                h = self.devices.get(name)
                if h:
                    h.off()
            else:
                r = self.gpio.get_relay(name)
                if r:
                    r.off()

            progress = int((i + 1) / total_items * 100)
            emit("stage_progress", {
                "stage_index": index, "stage_name": "testing",
                "progress": progress, "elapsed": (i + 1) * 3,
                "remaining": (total_items - i - 1) * 3,
                "total_duration": total_items * 3,
            })
            time.sleep(0.5)

    def _demo_sequence(self, index: int, total: int, emit: EventCallback):
        nodes = {
            "Node 1": ["p1", "p2", "ro1", "ro2", "d1", "p3", "pump"],
            "Node 2": ["p4", "p5", "ro3", "ro4", "d2", "top", "flushmain"],
            "Node 3": ["s1", "s2", "s3", "s4", "s5", "bottom", "s8"],
        }
        step = 0
        total_steps = sum(len(v) for v in nodes.values()) + 4  # +4 for GPIO

        for node_label, devices_list in nodes.items():
            logger.info(f"  --- {node_label} ---")
            for name in devices_list:
                if not self._running:
                    return
                h = self.devices.get(name)
                if h:
                    h.on()
                    time.sleep(5)
                    h.off()
                step += 1
                emit("stage_progress", {
                    "stage_index": index, "stage_name": "demo",
                    "progress": int(step / total_steps * 100),
                    "elapsed": step * 6, "remaining": (total_steps - step) * 6,
                    "total_duration": total_steps * 6,
                })
                time.sleep(0.5)

        logger.info("  --- Raspberry Pi GPIO ---")
        for gpio_name in ["dry", "roof", "geyser", "rglight"]:
            if not self._running:
                return
            r = self.gpio.get_relay(gpio_name)
            if r:
                r.on()
                time.sleep(5)
                r.off()
            step += 1
            time.sleep(0.5)
