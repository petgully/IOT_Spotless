"""
=============================================================================
Stage Executor - Project Spotless (Contract v1.1 §6, §9)
=============================================================================
Per-second-accounting bath controller. Reads stage dicts from
session_stages.py and executes them with:

  - Relay confirmation polling (default: optimistic; pluggable
    `confirm_on_fn` lets session_runner inject real MQTT state checks).
  - Per-second `delivered_seconds[stage_name]` accumulator that ONLY
    increments while the required relays are confirmed ON
    (`accounting='relays'`) or always (`accounting='wallclock'`).
  - Stage-budget enforcement: the executor stops a stage the instant it
    delivers `budget` seconds — anti-fraud guarantee (contract §6.4, §14).
  - Resume support: an optional `resume_state` skips completed stages
    and rewinds the current stage to its already-delivered count, so the
    customer gets EXACTLY the remaining seconds owed.
  - Periodic flush callback (default every 5s) so the runner can persist
    progress + enqueue cloud writes.
  - Major-stage completion callback so the runner can fire stage-complete
    cloud writes (contract §8.3).

Device name conventions in stage configs (same as before):
    "p1", "s8", "pump"  -> MQTT device (via DeviceController)
    "gpio:dry"          -> Direct Raspberry Pi GPIO (via GPIOController)

Public API:
    executor = StageExecutor(device_controller, gpio_controller)
    result   = executor.run_session(
        stages,
        on_stage_start=...,
        on_progress_tick=...,        # per-second
        on_progress_flush=...,       # per-5s (default cadence)
        on_stage_complete=...,
        on_session_complete=...,
        on_abort=...,
        emit=socketio_emit,
        resume_state=None,
        major_stages=set(),
        confirm_on_fn=None,
    )
    executor.stop(reason='admin-stop')
=============================================================================
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# =============================================================================
# Audio
# =============================================================================
AUDIO_BASE_PATH = os.environ.get(
    "SPOTLESS_AUDIO_BASE", "/home/spotless/Downloads/V3_Spotless"
)

AUDIO_FILES: Dict[str, str] = {
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

# Disable VLC subprocess launches when not on the kiosk (dev / CI / Windows).
AUDIO_ENABLED = os.environ.get("SPOTLESS_AUDIO", "auto").lower()
if AUDIO_ENABLED == "auto":
    AUDIO_ENABLED_BOOL = (os.name == "posix" and os.path.exists(AUDIO_BASE_PATH))
else:
    AUDIO_ENABLED_BOOL = AUDIO_ENABLED in ("1", "true", "yes", "on")


# =============================================================================
# Confirmation policy (contract §6.4)
# =============================================================================
RELAY_CONFIRM_SOFT_TIMEOUT_S = 2.0    # warn-only after this many sec without confirmation
RELAY_CONFIRM_HARD_TIMEOUT_S = 10.0   # abort the stage after this many consecutive fault seconds
PROGRESS_FLUSH_INTERVAL_S    = 5      # SQLite + cloud queue write cadence


# =============================================================================
# Types
# =============================================================================

EventCallback = Callable[[str, Dict[str, Any]], None]


@dataclass
class ResumeState:
    """Optional input to run_session(). Tells the executor how far the
    previous attempt got, so it skips/shortens stages accordingly."""
    completed_stages: List[str] = field(default_factory=list)
    delivered_seconds: Dict[str, int] = field(default_factory=dict)
    # Index of the stage that was in flight when interrupted (cosmetic; the
    # executor recomputes from completed_stages + delivered_seconds).
    current_stage_idx: int = 0


@dataclass
class SessionResult:
    """Returned by run_session()."""
    ok: bool                                 # True if session completed normally
    aborted: bool = False
    abort_reason: Optional[str] = None
    last_stage: str = ""
    completed_stages: List[str] = field(default_factory=list)
    delivered_seconds: Dict[str, int] = field(default_factory=dict)
    current_stage_idx: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "last_stage": self.last_stage,
            "completed_stages": list(self.completed_stages),
            "delivered_seconds": dict(self.delivered_seconds),
            "current_stage_idx": self.current_stage_idx,
        }


def _noop(*_args, **_kwargs) -> None:
    pass


# =============================================================================
# Executor
# =============================================================================

class StageExecutor:
    """Sequential stage executor with anti-fraud accounting + resume."""

    def __init__(self, device_controller, gpio_controller):
        self.devices = device_controller
        self.gpio = gpio_controller
        self._running = False
        self._abort_reason: Optional[str] = None
        self._current_stage: Optional[Dict] = None

    # =========================================================================
    # Public API
    # =========================================================================

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_stage(self) -> Optional[Dict]:
        return self._current_stage

    def stop(self, reason: str = "admin-stop") -> None:
        """External stop request. Sets a flag; the executor exits cleanly."""
        self._running = False
        self._abort_reason = reason
        try:
            self.all_off()
        except Exception as e:
            logger.error(f"stop(): all_off failed: {e}")
        logger.warning(f"StageExecutor.stop() reason={reason!r}")

    def all_off(self) -> None:
        logger.warning("ALL OFF - shutting down all devices")
        try:
            if self.devices and hasattr(self.devices, "all_off"):
                self.devices.all_off()
        except Exception as e:
            logger.error(f"MQTT all_off error: {e}")
        try:
            if self.gpio and hasattr(self.gpio, "all_off"):
                self.gpio.all_off()
        except Exception as e:
            logger.error(f"GPIO all_off error: {e}")

    # ---------------------------------------------------------------- main run
    def run_session(
        self,
        stages: List[Dict],
        *,
        emit: Optional[EventCallback] = None,
        on_stage_start:       Optional[Callable[[Dict, int], None]] = None,
        on_progress_tick:     Optional[Callable[[Dict, int, int], None]] = None,
        on_progress_flush:    Optional[Callable[[Dict, int], None]] = None,
        on_stage_complete:    Optional[Callable[..., None]] = None,
        on_session_complete:  Optional[Callable[[SessionResult], None]] = None,
        on_abort:             Optional[Callable[[SessionResult], None]] = None,
        resume_state:         Optional[ResumeState] = None,
        major_stages:         Optional[Set[str]] = None,
        confirm_on_fn:        Optional[Callable[[List[str]], bool]] = None,
    ) -> SessionResult:
        """Execute the full session sequentially.

        Args:
            stages:               from session_stages.build_session().
            emit:                 socketio emit callback (for UI events).
            on_stage_start:       (stage, idx) callback fired right after relays go on.
            on_progress_tick:     (stage, delivered, budget) per-second hook.
            on_progress_flush:    (stage, delivered) per-5s hook (persist to SQLite).
            on_stage_complete:    (stage, idx, delivered) — fired on full-budget completion.
            on_session_complete:  (result) callback on natural completion.
            on_abort:             (result) callback on abort.
            resume_state:         if given, executor skips already-completed
                                  stages and rewinds the current stage.
            major_stages:         names of stages that should be reported to
                                  on_stage_complete (others are silent
                                  beyond local tracking).
            confirm_on_fn:        (devices_on_list) -> bool. Returns True when
                                  all listed relays are confirmed ON. If None,
                                  optimistic mode is used (assume on after set).
        """
        emit                = emit or _noop
        on_stage_start      = on_stage_start or (lambda *_: None)
        on_progress_tick    = on_progress_tick or (lambda *_: None)
        on_progress_flush   = on_progress_flush or (lambda *_: None)
        on_stage_complete   = on_stage_complete or (lambda *_: None)
        on_session_complete = on_session_complete or (lambda _r: None)
        on_abort            = on_abort or (lambda _r: None)
        major_stages        = major_stages or set()
        confirm_on_fn       = confirm_on_fn or self._optimistic_confirm

        # ----- resume bookkeeping -----
        completed: List[str] = list(resume_state.completed_stages) if resume_state else []
        delivered: Dict[str, int] = dict(resume_state.delivered_seconds) if resume_state else {}
        for s in stages:
            delivered.setdefault(s["name"], 0)

        self._running = True
        self._abort_reason = None
        total = len(stages)
        last_stage_name = ""
        current_idx = 0

        logger.info("=" * 60)
        logger.info(
            f"SESSION START stages={total} resume={bool(resume_state)} "
            f"already_completed={len(completed)}"
        )
        logger.info("=" * 60)

        try:
            for idx, stage in enumerate(stages):
                if not self._running:
                    break

                name = stage.get("name", f"stage_{idx}")
                budget = int(stage.get("duration", 0))
                last_stage_name = name
                current_idx = idx

                # --- Skip already-completed stages ---
                if name in completed:
                    delivered[name] = budget
                    emit("stage_skipped", {
                        "stage_index": idx, "stage_name": name,
                        "total_stages": total,
                    })
                    logger.info(f"  [{idx+1}/{total}] SKIP {name} (already completed)")
                    continue

                # --- Compute remaining work for this stage (resume mid-stage) ---
                already = int(delivered.get(name, 0))
                remaining = max(0, budget - already)

                if remaining <= 0 and budget > 0:
                    # Stage was paid in full last time but not yet marked complete.
                    completed.append(name)
                    self._fire_stage_complete(
                        stage, idx, budget, major_stages, on_stage_complete, emit
                    )
                    continue

                # --- Run the stage ---
                ok = self._execute_stage(
                    stage           = stage,
                    idx             = idx,
                    total           = total,
                    already         = already,
                    budget          = budget,
                    delivered       = delivered,
                    emit            = emit,
                    on_stage_start  = on_stage_start,
                    on_progress_tick    = on_progress_tick,
                    on_progress_flush   = on_progress_flush,
                    confirm_on_fn   = confirm_on_fn,
                )

                if not ok:
                    # Abort: relays are already off; reason is on self.
                    break

                # Stage finished its budget.
                completed.append(name)
                self._fire_stage_complete(
                    stage, idx, delivered[name], major_stages,
                    on_stage_complete, emit,
                )

            # ----- session-level outcome -----
            if not self._running:
                # Aborted
                result = SessionResult(
                    ok=False,
                    aborted=True,
                    abort_reason=self._abort_reason or "stopped",
                    last_stage=last_stage_name,
                    completed_stages=completed,
                    delivered_seconds=delivered,
                    current_stage_idx=current_idx,
                )
                logger.warning(
                    f"SESSION ABORT reason={result.abort_reason!r} "
                    f"completed={len(completed)}/{total}"
                )
                on_abort(result)
                return result

            result = SessionResult(
                ok=True,
                aborted=False,
                last_stage=last_stage_name,
                completed_stages=completed,
                delivered_seconds=delivered,
                current_stage_idx=current_idx,
            )
            logger.info("=" * 60)
            logger.info(f"SESSION COMPLETE stages={total}")
            logger.info("=" * 60)
            on_session_complete(result)
            return result

        except Exception as e:
            logger.error(f"Session error: {e}", exc_info=True)
            self._abort_reason = self._abort_reason or f"exception:{e}"
            self.all_off()
            result = SessionResult(
                ok=False, aborted=True, abort_reason=self._abort_reason,
                last_stage=last_stage_name, completed_stages=completed,
                delivered_seconds=delivered, current_stage_idx=current_idx,
            )
            on_abort(result)
            return result
        finally:
            self._running = False
            self._current_stage = None

    # =========================================================================
    # Single-stage execution
    # =========================================================================

    def _execute_stage(
        self,
        *,
        stage: Dict,
        idx: int,
        total: int,
        already: int,
        budget: int,
        delivered: Dict[str, int],
        emit: EventCallback,
        on_stage_start:    Callable,
        on_progress_tick:  Callable,
        on_progress_flush: Callable,
        confirm_on_fn:     Callable[[List[str]], bool],
    ) -> bool:
        """Run a single stage end-to-end. Returns False if aborted mid-stage."""
        name        = stage.get("name", f"stage_{idx}")
        label       = stage.get("label", name)
        devices_on  = stage.get("devices_on", []) or []
        parallel    = stage.get("parallel_pump")
        audio_key   = stage.get("audio")
        beep_end    = bool(stage.get("beep_end", False))
        image       = stage.get("image", "")
        special     = stage.get("special_handler")
        accounting  = stage.get(
            "accounting",
            "wallclock" if not devices_on else "relays",
        )

        self._current_stage = stage
        logger.info(
            f"  [{idx+1}/{total}] {name}: budget={budget}s already={already}s "
            f"devices={devices_on} accounting={accounting}"
        )

        # ----- Special handler path (test_relays, demo) -----
        if special:
            emit("stage_start", {
                "stage_index": idx, "stage_name": name, "stage_label": label,
                "stage_duration": budget, "stage_image": image,
                "total_stages": total,
            })
            self._run_special(special, budget, idx, total, emit)
            delivered[name] = budget
            emit("stage_complete", {"stage_index": idx, "stage_name": name})
            return True

        # ----- 1. Audio cue -----
        if audio_key and AUDIO_ENABLED_BOOL:
            self._play_audio_async(audio_key)

        # ----- 2. Parallel pump (mL dose) -----
        if parallel and devices_on:
            pump_dev = parallel.get("device", "")
            pump_dur = float(parallel.get("duration", 0))
            if pump_dev and pump_dur > 0:
                self._pump_async(pump_dev, pump_dur)

        # ----- 3. Turn ON devices -----
        self._set_devices(devices_on, True)

        # ----- 4. Stage start emit -----
        emit("stage_start", {
            "stage_index": idx, "stage_name": name, "stage_label": label,
            "stage_duration": budget, "stage_image": image,
            "total_stages": total,
            "resumed_from": already if already > 0 else 0,
        })
        try:
            on_stage_start(stage, idx)
        except Exception as e:
            logger.error(f"on_stage_start callback error: {e}")

        # ----- 5. Tick loop with anti-fraud accounting -----
        fault_seconds = 0
        last_flush_at = time.time()
        emitted_soft_warning = False

        while delivered[name] < budget and self._running:
            tick_start = time.time()

            # Decide whether this second "counts" toward delivered.
            if accounting == "wallclock" or not devices_on:
                counted = True
            else:
                try:
                    counted = bool(confirm_on_fn(devices_on))
                except Exception as e:
                    logger.error(f"confirm_on_fn error: {e}; assuming OFF")
                    counted = False

            if counted:
                delivered[name] = min(budget, delivered[name] + 1)
                fault_seconds = 0
                emitted_soft_warning = False
            else:
                fault_seconds += 1
                if (not emitted_soft_warning
                        and fault_seconds >= RELAY_CONFIRM_SOFT_TIMEOUT_S):
                    logger.warning(
                        f"  [{name}] relays not confirmed ON after "
                        f"{fault_seconds}s — soft warning"
                    )
                    emit("stage_relay_warning", {
                        "stage_index": idx, "stage_name": name,
                        "fault_seconds": fault_seconds,
                    })
                    emitted_soft_warning = True
                if fault_seconds >= RELAY_CONFIRM_HARD_TIMEOUT_S:
                    self._abort_reason = f"relay-fault:{name}:{fault_seconds}s"
                    logger.error(
                        f"  [{name}] HARD ABORT - relays not confirmed for "
                        f"{fault_seconds}s; aborting session"
                    )
                    self._set_devices(devices_on, False)
                    self._running = False  # CRITICAL: propagate abort to outer loop
                    return False

            # Per-second UI tick
            remaining = max(0, budget - delivered[name])
            progress  = int(delivered[name] / max(budget, 1) * 100)
            emit("stage_progress", {
                "stage_index": idx, "stage_name": name,
                "progress": progress,
                "elapsed":  delivered[name],
                "remaining": remaining,
                "total_duration": budget,
                "counted": counted,
            })
            try:
                on_progress_tick(stage, delivered[name], budget)
            except Exception as e:
                logger.error(f"on_progress_tick callback error: {e}")

            # Periodic flush (default every 5s)
            now = time.time()
            if (now - last_flush_at) >= PROGRESS_FLUSH_INTERVAL_S:
                last_flush_at = now
                try:
                    on_progress_flush(stage, delivered[name])
                except Exception as e:
                    logger.error(f"on_progress_flush callback error: {e}")

            # Sleep the remainder of the second (be mindful of long callbacks)
            elapsed = time.time() - tick_start
            sleep_for = max(0.0, 1.0 - elapsed)
            if sleep_for > 0:
                # Sleep in chunks so a stop() request is responsive.
                end_at = time.time() + sleep_for
                while time.time() < end_at and self._running:
                    time.sleep(min(0.1, end_at - time.time()))

        # ----- 6. Stop loop reason: aborted? -----
        if not self._running:
            self._set_devices(devices_on, False)
            return False

        # ----- 7. Final flush at stage end -----
        try:
            on_progress_flush(stage, delivered[name])
        except Exception as e:
            logger.error(f"on_progress_flush (final) error: {e}")

        # ----- 8. Turn OFF devices -----
        self._set_devices(devices_on, False)

        # ----- 9. Beep -----
        if beep_end and AUDIO_ENABLED_BOOL:
            self._beep()

        return True

    def _fire_stage_complete(self, stage, idx, delivered, major_stages,
                              on_stage_complete, emit):
        """Fire stage-complete callback for EVERY stage (callers filter for major).

        Local persistence (session_progress) needs every stage; cloud writes
        are filtered at the callback site using `major_stages`.
        """
        name = stage.get("name", f"stage_{idx}")
        emit("stage_complete", {"stage_index": idx, "stage_name": name})
        is_major = name in major_stages
        try:
            on_stage_complete(stage, idx, delivered, is_major)
        except TypeError:
            # Backward-compat for callers that don't accept is_major
            try:
                on_stage_complete(stage, idx, delivered)
            except Exception as e:
                logger.error(f"on_stage_complete (legacy) callback error: {e}")
        except Exception as e:
            logger.error(f"on_stage_complete callback error: {e}")

    # =========================================================================
    # Device control
    # =========================================================================

    def _set_devices(self, device_names: List[str], state: bool) -> None:
        for name in device_names:
            try:
                if name.startswith("gpio:"):
                    gpio_name = name[5:]
                    relay = self.gpio.get_relay(gpio_name) if self.gpio else None
                    if relay:
                        relay.set(state)
                    else:
                        logger.warning(f"Unknown GPIO device: {gpio_name}")
                else:
                    handle = self.devices.get(name) if self.devices else None
                    if handle:
                        handle.set(state)
                    else:
                        logger.warning(f"Unknown MQTT device: {name}")
            except Exception as e:
                logger.error(f"Error setting {name} -> {state}: {e}")

    def _optimistic_confirm(self, devices_on: List[str]) -> bool:
        """Default confirmation policy: assume relays are on once we've set them.

        session_runner can pass a real `confirm_on_fn` that consults the
        node_controller's MQTT state cache for true anti-fraud guarantees.
        """
        return True

    # =========================================================================
    # Pump / Audio
    # =========================================================================

    def _pump_async(self, device_name: str, duration: float) -> None:
        def _run():
            handle = self.devices.get(device_name) if self.devices else None
            if handle:
                logger.info(f"  Parallel pump {device_name}: ON for {duration}s")
                handle.on()
                # Sleep in chunks for stop responsiveness
                end_at = time.time() + duration
                while time.time() < end_at and self._running:
                    time.sleep(min(0.2, end_at - time.time()))
                handle.off()
                logger.info(f"  Parallel pump {device_name}: OFF")
            else:
                logger.warning(f"Unknown pump device: {device_name}")
        threading.Thread(target=_run, daemon=True).start()

    def _play_audio_async(self, audio_key: str) -> None:
        path = AUDIO_FILES.get(audio_key)
        if not path:
            return
        if not os.path.exists(path):
            logger.debug(f"audio: file missing {path}")
            return
        threading.Thread(
            target=lambda: os.system(f"cvlc {path} vlc://quit"),
            daemon=True,
        ).start()

    def _beep(self, count: int = 6, interval: float = 0.5) -> None:
        beep_path = AUDIO_FILES.get("beep")
        if not beep_path or not os.path.exists(beep_path):
            return
        for _ in range(count):
            os.system(f"cvlc {beep_path} vlc://quit")
            time.sleep(interval)

    # =========================================================================
    # Special handlers (test_relays, demo)
    # =========================================================================

    def _run_special(self, handler: str, duration: int,
                      index: int, total: int, emit: EventCallback) -> None:
        if handler == "test_relays":
            self._test_relays_sequence(index, total, emit)
        elif handler == "demo":
            self._demo_sequence(index, total, emit)
        else:
            logger.warning(f"Unknown special handler: {handler}")
            self._responsive_sleep(duration)

    def _responsive_sleep(self, duration: float) -> None:
        end_at = time.time() + duration
        while time.time() < end_at and self._running:
            time.sleep(min(0.25, end_at - time.time()))

    def _test_relays_sequence(self, index: int, total: int,
                              emit: EventCallback) -> None:
        all_mqtt = [
            "p1", "p2", "p3", "p4",
            "ro1", "ro2", "ro3", "ro4",
            "d1", "d2",
            "s1", "s2", "s3", "s4", "s5",
            "flushmain", "s8",
            "pump",
        ]
        # top/bottom moved to Pi GPIO; p4 on Node 2 BACK1; p5 backup dropped.
        gpio_names = ["dry", "roof", "geyser", "top", "bottom", "rglight"]
        items = [(n, "mqtt") for n in all_mqtt] + [(n, "gpio") for n in gpio_names]
        total_items = len(items)

        for i, (name, kind) in enumerate(items):
            if not self._running:
                return
            logger.info(f"  Test: {name} ({kind})")
            handle = (self.devices.get(name) if kind == "mqtt" and self.devices
                      else self.gpio.get_relay(name) if self.gpio else None)
            if handle:
                handle.on()
            self._responsive_sleep(2)
            if handle:
                handle.off()
            progress = int((i + 1) / total_items * 100)
            emit("stage_progress", {
                "stage_index": index, "stage_name": "testing",
                "progress": progress, "elapsed": (i + 1) * 3,
                "remaining": (total_items - i - 1) * 3,
                "total_duration": total_items * 3,
            })
            self._responsive_sleep(0.5)

    def _demo_sequence(self, index: int, total: int,
                       emit: EventCallback) -> None:
        nodes = {
            "Node 1": ["pump", "p1", "d1", "ro2", "ro1", "p2"],
            "Node 2": ["flushmain", "p3", "d2", "ro4", "ro3", "p4"],
            "Node 3": ["s8", "s1", "s5", "s4", "s3", "s2"],
        }
        gpio_demo = ["dry", "roof", "geyser", "top", "bottom", "rglight"]
        step = 0
        total_steps = sum(len(v) for v in nodes.values()) + len(gpio_demo)

        for node_label, devices_list in nodes.items():
            logger.info(f"  --- {node_label} ---")
            for name in devices_list:
                if not self._running:
                    return
                h = self.devices.get(name) if self.devices else None
                if h:
                    h.on()
                    self._responsive_sleep(5)
                    h.off()
                step += 1
                emit("stage_progress", {
                    "stage_index": index, "stage_name": "demo",
                    "progress": int(step / total_steps * 100),
                    "elapsed": step * 6,
                    "remaining": (total_steps - step) * 6,
                    "total_duration": total_steps * 6,
                })
                self._responsive_sleep(0.5)

        for gpio_name in gpio_demo:
            if not self._running:
                return
            r = self.gpio.get_relay(gpio_name) if self.gpio else None
            if r:
                r.on()
                self._responsive_sleep(5)
                r.off()
            step += 1
            self._responsive_sleep(0.5)
