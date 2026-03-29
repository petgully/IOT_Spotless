"""
=============================================================================
Spotless Controller - Bath Session Control - Project Spotless
=============================================================================
Core hardware-control logic for the pet grooming process.

Controls ESP32 relay devices and Raspberry Pi GPIO relays to run
shampoo, water, conditioner, dryer, disinfectant, and flush stages.

Session parameter presets are managed by config_manager.py (single source
of truth). This module only receives parameters and drives hardware.

Variable Mapping (Legacy -> New):
    top -> s6,  bottom -> s7,  flushmain -> s8,  roof -> s9

Device Summary:
    ESP32: p1-p5, ro1-ro4, d1, d2, s1-s9, pump
    GPIO:  dry, geyser
=============================================================================
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)

# =============================================================================
# Audio Path Configuration
# =============================================================================
AUDIO_BASE_PATH = "/home/spotless/Downloads/V3_Spotless"
VOICEOVER_PATH = f"{AUDIO_BASE_PATH}/Voiceover"
MUSIC_PATH = f"{AUDIO_BASE_PATH}/Mus"

AUDIO_FILES = {
    "welcome": f"{VOICEOVER_PATH}/1_Welcome.mp3",
    "onboard": f"{VOICEOVER_PATH}/2_Onboard.mp3",
    "shampoo": f"{VOICEOVER_PATH}/3_Shampoo.mp3",
    "water": f"{VOICEOVER_PATH}/4_Water.mp3",
    "conditioner": f"{VOICEOVER_PATH}/5_Condition.mp3",
    "water2": f"{VOICEOVER_PATH}/6_Water.mp3",
    "towel": f"{VOICEOVER_PATH}/7_Towel.mp3",
    "dryer": f"{VOICEOVER_PATH}/8_Dryer.mp3",
    "break": f"{VOICEOVER_PATH}/9_Break.mp3",
    "offboard": f"{VOICEOVER_PATH}/10_Offboard.mp3",
    "laststep": f"{VOICEOVER_PATH}/11_laststep.mp3",
    "disinfect": f"{VOICEOVER_PATH}/12_Disinfect.mp3",
    "thankyou": f"{VOICEOVER_PATH}/13_Thankyou.mp3",
    "massage": f"{VOICEOVER_PATH}/Massage.mp3",
    "beep": f"{MUSIC_PATH}/Beep.mp3",
    "powerdown": f"{MUSIC_PATH}/Powerdown.mp3",
    "music_8h": f"{MUSIC_PATH}/8_hours.mp3",
}


# =============================================================================
# Spotless Controller Class
# =============================================================================
class SpotlessController:
    """
    Main controller for Spotless bath functions.

    Wraps all bath control functions and manages communication with
    ESP32 nodes (via DeviceController) and direct GPIO.
    """

    def __init__(self, device_controller, gpio_controller):
        self.devices = device_controller
        self.gpio = gpio_controller
        self.current_session = None
        self.session_start_time = None

    # =========================================================================
    # Device Access Properties
    # =========================================================================

    @property
    def p1(self): return self.devices.p1
    @property
    def p2(self): return self.devices.p2
    @property
    def p3(self): return self.devices.p3
    @property
    def p4(self): return self.devices.p4
    @property
    def p5(self): return self.devices.p5

    @property
    def ro1(self): return self.devices.ro1
    @property
    def ro2(self): return self.devices.ro2
    @property
    def ro3(self): return self.devices.ro3
    @property
    def ro4(self): return self.devices.ro4

    @property
    def d1(self): return self.devices.d1
    @property
    def d2(self): return self.devices.d2

    @property
    def s1(self): return self.devices.s1
    @property
    def s2(self): return self.devices.s2
    @property
    def s3(self): return self.devices.s3
    @property
    def s4(self): return self.devices.s4
    @property
    def s5(self): return self.devices.s5
    @property
    def s6(self): return self.devices.s6
    @property
    def s7(self): return self.devices.s7
    @property
    def s8(self): return self.devices.s8
    @property
    def s9(self): return self.devices.s9

    @property
    def pump(self): return self.devices.pump

    @property
    def dry(self): return self.gpio.dry
    @property
    def geyser(self): return self.gpio.geyser

    # =========================================================================
    # Helper Functions
    # =========================================================================

    def toggle_devices(self, device_list: List, state: bool):
        for device in device_list:
            if state:
                device.on()
            else:
                device.off()

    def play_audio(self, audio_key: str, wait: bool = True):
        audio_file = AUDIO_FILES.get(audio_key)
        if audio_file:
            cmd = f"cvlc {audio_file} vlc://quit"
            if wait:
                os.system(cmd)
            else:
                threading.Thread(target=lambda: os.system(cmd), daemon=True).start()
        else:
            logger.warning(f"Unknown audio key: {audio_key}")

    def beep(self, count: int = 6, interval: float = 0.5):
        for _ in range(count):
            self.play_audio("beep")
            time.sleep(interval)

    def kill_audio(self):
        os.system("killall vlc")

    # =========================================================================
    # Timer Functions
    # =========================================================================

    def start_timer(self, stage_name: str) -> datetime:
        start_time = datetime.now()
        logger.info(f"** {stage_name} started at {start_time}")
        return start_time

    def end_timer(self, start_time: datetime):
        duration = datetime.now() - start_time
        logger.info(f"Stage Duration: {duration}")

    # =========================================================================
    # Pump Control Functions
    # =========================================================================

    def pump_ready(self, pump_device, wait_time: float):
        pump_device.on()
        time.sleep(wait_time)
        pump_device.off()

    def pump_ready_async(self, pump_device, wait_time: float) -> threading.Thread:
        thread = threading.Thread(
            target=self.pump_ready,
            args=(pump_device, wait_time),
            daemon=True,
        )
        thread.start()
        return thread

    def empty_time(self, diaphragm, ro_solenoid, drain_time: float):
        self.toggle_devices([diaphragm, ro_solenoid], True)
        time.sleep(drain_time)
        self.toggle_devices([diaphragm, ro_solenoid], False)

    def empty_time_async(self, diaphragm, ro_solenoid, drain_time: float) -> threading.Thread:
        thread = threading.Thread(
            target=self.empty_time,
            args=(diaphragm, ro_solenoid, drain_time),
            daemon=True,
        )
        thread.start()
        return thread

    # =========================================================================
    # Priming Functions
    # =========================================================================

    def priming(self, mainflow, localgate, main_ro, main_dp, dp_ro,
                fill_time: float, empty_time: float):
        self.toggle_devices([mainflow, localgate, main_ro], True)
        time.sleep(fill_time)
        self.toggle_devices([mainflow, localgate, main_ro], False)

        self.toggle_devices([main_dp, dp_ro], True)
        time.sleep(empty_time)
        self.toggle_devices([main_dp, dp_ro], False)

    def priming_shampoo(self, fill_time: float, empty_time: float):
        logger.info(f"Priming shampoo: fill={fill_time}s, empty={empty_time}s")
        self.priming(self.s8, self.s1, self.ro1, self.d1, self.ro2, fill_time, empty_time)

    def priming_disinfectant(self, fill_time: float):
        logger.info(f"Priming disinfectant: fill={fill_time}s")
        self.priming(self.s8, self.s3, self.ro3, self.d2, self.ro4, fill_time, 6)

    # =========================================================================
    # Core Bath Functions
    # =========================================================================

    def Shampoo(self, qr_return: str, duration: float, pump_wait: float):
        st = self.start_timer("Shampoo")
        self.pump_ready_async(self.p1, pump_wait)
        self.play_audio("shampoo")
        self.play_audio("shampoo")
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], False)
        logger.info(f"Shampoo complete for {qr_return}")
        self.end_timer(st)

    def Water(self, duration: float):
        st = self.start_timer("Water")
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], False)
        self.end_timer(st)

    def Conditioner(self, qr_return: str, duration: float, pump_wait: float):
        st = self.start_timer("Conditioner")
        self.pump_ready_async(self.p2, pump_wait)
        self.play_audio("conditioner")
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], False)
        logger.info(f"Conditioner complete for {qr_return}")
        self.end_timer(st)

    def Mbath(self, qr_return: str, duration: float, pump_wait: float):
        st = self.start_timer("Medicated_Bath")
        self.pump_ready_async(self.p4, pump_wait)
        self.play_audio("conditioner")
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], False)
        logger.info(f"Medicated bath complete for {qr_return}")
        self.end_timer(st)

    def massage_time(self, duration: float):
        st = self.start_timer("Massage_Time")
        logger.info(f"Massage Time: {duration} seconds")
        self.play_audio("massage")
        time.sleep(duration)
        self.end_timer(st)

    def Dryer(self, qr_return: str, duration: float):
        st = self.start_timer("Drying")
        self.play_audio("dryer")
        self.play_audio("dryer")
        dmul = 0.5
        self.dry.on()
        time.sleep(duration * dmul)
        self.dry.off()
        self.play_audio("break")
        time.sleep(15)
        self.end_timer(st)
        self.dry.on()
        time.sleep(duration * dmul)
        self.beep()
        self.dry.off()
        if qr_return == "Testing_only_Dryer":
            self.kill_audio()
        logger.info(f"Dryer complete for {qr_return}")
        self.end_timer(st)

    def Disinfectant(self, duration: float, pump_wait: float):
        st = self.start_timer("Disinfectant")
        diwt = pump_wait * 0.8
        self.pump_ready_async(self.p4, diwt)
        self.play_audio("disinfect")
        self.toggle_devices([self.s8, self.s3, self.s4, self.s2, self.d2, self.pump], True)
        time.sleep(duration)
        self.toggle_devices([self.s8, self.s3, self.s4, self.s2, self.d2, self.pump], False)
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], False)
        self.end_timer(st)

    def Flush(self, duration: float):
        st = self.start_timer("Autoflush")
        self.toggle_devices([self.s6, self.pump, self.s8], True)
        time.sleep(duration)
        self.toggle_devices([self.s6, self.pump], False)
        self.toggle_devices([self.s7, self.pump], True)
        time.sleep(duration)
        self.toggle_devices([self.s7, self.pump, self.s8], False)
        self.play_audio("thankyou")
        self.play_audio("powerdown")
        logger.info("Flush complete")
        self.end_timer(st)

    def Empty_tank(self, duration: float):
        st = self.start_timer("EmptyingTank")
        self.toggle_devices([self.d1, self.ro2], True)
        time.sleep(duration)
        self.toggle_devices([self.d1, self.ro2], False)
        self.play_audio("powerdown")
        self.kill_audio()
        logger.info("Tank emptied")
        self.end_timer(st)

    # =========================================================================
    # Utility Functions
    # =========================================================================

    def Allclose(self):
        logger.warning("ALLCLOSE - Turning off all devices")
        self.devices.all_off()
        self.gpio.all_off()

    def Lightson(self):
        logger.info("Lights ON")

    def Lightsoff(self):
        self.play_audio("powerdown")
        logger.info("Lights OFF")

    def control_roof_lights(self):
        current_time = datetime.now().time()
        on_time = datetime.strptime("17:00", "%H:%M").time()
        off_time = datetime.strptime("05:00", "%H:%M").time()
        if on_time <= current_time or current_time < off_time:
            self.s9.on()
            logger.info("Roof lights turned ON")
        else:
            self.s9.off()
            logger.info("Roof lights turned OFF")

    # =========================================================================
    # Main Spotless Function
    # =========================================================================

    def Spotless(self, qr_return: str, sval: float, cval: float, dval: float,
                 wval: float, dryval: float, fval: float, wt: float,
                 stval: float, msgval: float, tdry: float, pr: int,
                 stage: int, ctype: int):
        self.s9.on()
        primeval = 30
        shampoo_empty_time = 6
        conditioner_empty_time = 12

        logger.info("-" * 60)
        mst = self.start_timer("Spotless Function")
        logger.info(f"Stage: {stage}")
        logger.info(f"QR: {qr_return}, Shampoo: {sval}, Conditioner: {cval}, "
                     f"Disinfect: {dval}, Water: {wval}, Dryer: {dryval}, "
                     f"Flush: {fval}, WaitTime: {wt}, StageVal: {stval}, "
                     f"Massage: {msgval}, Towel: {tdry}, PR: {pr}, Stage: {stage}")

        start_time = datetime.now()
        self.priming_shampoo(primeval, shampoo_empty_time)

        for _ in range(2):
            self.play_audio("onboard")
        time.sleep(4)

        if stage <= 1:
            self.Shampoo(qr_return, sval, wt)
            self.massage_time(msgval)
        if stage <= 2:
            self.beep()
            self.play_audio("water")
            self.Water(wval)
            self.priming_shampoo(primeval, conditioner_empty_time)
        if stage <= 3:
            if ctype == 100:
                self.Conditioner(qr_return, cval, wt)
            elif ctype == 200:
                self.Mbath(qr_return, cval, wt)
            self.massage_time(msgval)
            self.beep()
        if stage <= 4:
            self.play_audio("water2")
            self.Water(2 * wval)
        if stage <= 5:
            st = self.start_timer("Towel Dry")
            for _ in range(2):
                self.play_audio("towel")
            time.sleep(tdry)
            self.end_timer(st)
        if stage <= 6:
            self.Dryer(qr_return, dryval)

        for _ in range(2):
            self.play_audio("offboard")
            time.sleep(3)

        if pr == 10:
            for _ in range(2):
                self.play_audio("laststep")
                self.play_audio("disinfect")
                time.sleep(stval)
            self.Disinfectant(dval, wt)

        self.empty_time_async(self.d1, self.ro2, 8)
        self.empty_time_async(self.d2, self.ro4, 8)
        self.play_audio("thankyou")

        duration = datetime.now() - start_time
        logger.info(f"Session Duration: {duration}")
        logger.info("-" * 60)
        self.end_timer(mst)

        self.kill_audio()
        self.Lightsoff()
        self.s9.off()
        self.control_roof_lights()

    def fromDisinfectant(self, qr_return: str, sval: float, cval: float,
                         dval: float, wval: float, dryval: float, fval: float,
                         wt: float, stval: float, msgval: float, tdry: float,
                         pr: int, stage: int, ctype: int):
        logger.info(f"** Customer QR Activated from Disinfectant Stage: {qr_return}")
        start_time = datetime.now()
        self.priming_disinfectant(12)
        self.Disinfectant(dval, wt)
        threading.Thread(target=self.Empty_tank, args=(30,), daemon=True).start()
        threading.Thread(target=self.Empty_tank, args=(30,), daemon=True).start()
        self.Flush(fval)
        self.play_audio("thankyou")
        logger.info(f"** Total Duration for QR {qr_return}: {datetime.now() - start_time}")
        self.kill_audio()
        self.Lightsoff()

    # =========================================================================
    # Quick Test Functions
    # =========================================================================

    def just_shampoo(self, qr_return: str):
        self.priming_shampoo(12, 6)
        self.Shampoo(qr_return, 60, 10)
        self.kill_audio()

    def just_water(self, duration: float):
        self.Water(duration)
        self.kill_audio()

    def test_relays(self):
        logger.info("Testing all relays...")
        all_devices = [
            self.p1, self.p2, self.p3, self.p4, self.p5,
            self.ro1, self.ro2, self.ro3, self.ro4,
            self.d1, self.d2,
            self.s1, self.s2, self.s3, self.s4, self.s5,
            self.s6, self.s7, self.s8, self.s9,
            self.pump,
        ]
        for device in all_devices:
            logger.info(f"Testing {device.device.name}...")
            device.on()
            time.sleep(2)
            device.off()
            time.sleep(0.5)
        logger.info("Testing dry...")
        self.dry.on()
        time.sleep(2)
        self.dry.off()
        logger.info("Testing geyser...")
        self.geyser.on()
        time.sleep(2)
        self.geyser.off()
        logger.info("Relay test complete!")

    def demo(self, qr_return: str = "DEMO"):
        logger.info("=" * 60)
        logger.info(f"Starting DEMO mode for {qr_return}")
        logger.info("=" * 60)

        sequences = [
            ("Node 1 (spotless_node1)",
             [self.p1, self.p2, self.ro2, self.ro1, self.d1, self.p3, self.pump],
             ["p1 (backup2)", "p2 (backup1)", "ro2 (rs2)", "ro1 (rs1)", "d1 (fp1)", "p3 (p1)", "pump (s1)"]),
            ("Node 2 (spotless_node2)",
             [self.p4, self.p5, self.ro4, self.ro3, self.d2, self.s7, self.s9],
             ["p4 (backup2)", "p5 (backup1)", "ro4 (rs2)", "ro3 (rs1)", "d2 (fp1)", "s7 (p1)", "s9 (s1)"]),
            ("Node 3 (spotless_node3)",
             [self.s1, self.s2, self.s4, self.s3, self.s5, self.s6, self.s8],
             ["s1 (backup2)", "s2 (backup1)", "s4 (rs2)", "s3 (rs1)", "s5 (fp1)", "s6 (p1)", "s8 (s1)"]),
        ]

        for label, devices, names in sequences:
            logger.info(f"\n--- {label} ---")
            for device, name in zip(devices, names):
                logger.info(f"  Activating {name}...")
                success = device.on()
                if not success:
                    logger.warning(f"  Failed to activate {name} (node may be offline)")
                time.sleep(5)
                device.off()
                time.sleep(0.5)

        logger.info("\n--- Raspberry Pi GPIO Relays ---")
        logger.info("  Activating dry (GPIO 14)...")
        self.dry.on()
        time.sleep(5)
        self.dry.off()
        time.sleep(0.5)
        logger.info("  Activating geyser (GPIO 18)...")
        self.geyser.on()
        time.sleep(5)
        self.geyser.off()

        logger.info("=" * 60)
        logger.info("DEMO mode complete!")
        logger.info("=" * 60)
