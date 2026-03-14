"""
=============================================================================
Spotless Functions - Bath Session Control - Project Spotless
=============================================================================
Main bath session functions adapted for IoT architecture.

This module contains all the core functions for controlling the pet
grooming/bathing process via ESP32 nodes and direct Raspberry Pi GPIO.

Variable Mapping (Legacy → New):
    top → s6
    bottom → s7
    flushmain → s8
    roof → s9

Device Summary:
    ESP32 Devices: p1, p2, p3, p4, p5, ro1, ro2, ro3, ro4, d1, d2, 
                   pump, s1-s9
    Direct GPIO:   dry, geyser
=============================================================================
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)

# =============================================================================
# Audio Path Configuration
# =============================================================================
AUDIO_BASE_PATH = "/home/spotless/Downloads/V3_Spotless"
VOICEOVER_PATH = f"{AUDIO_BASE_PATH}/Voiceover"
MUSIC_PATH = f"{AUDIO_BASE_PATH}/Mus"

# Audio files
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
    
    This class wraps all the bath control functions and manages
    communication with ESP32 nodes and direct GPIO.
    """
    
    def __init__(self, device_controller, gpio_controller):
        """
        Initialize SpotlessController.
        
        Args:
            device_controller: DeviceController for ESP32 nodes
            gpio_controller: GPIOController for direct Pi GPIO
        """
        self.devices = device_controller
        self.gpio = gpio_controller
        
        # Session state
        self.current_session = None
        self.session_start_time = None
        
    # =========================================================================
    # Device Access Properties
    # =========================================================================
    
    # Peristaltic Pumps
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
    
    # RO Solenoids
    @property
    def ro1(self): return self.devices.ro1
    @property
    def ro2(self): return self.devices.ro2
    @property
    def ro3(self): return self.devices.ro3
    @property
    def ro4(self): return self.devices.ro4
    
    # Diaphragm Pumps
    @property
    def d1(self): return self.devices.d1
    @property
    def d2(self): return self.devices.d2
    
    # Solenoids (s1-s9)
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
    def s6(self): return self.devices.s6  # was: top
    @property
    def s7(self): return self.devices.s7  # was: bottom
    @property
    def s8(self): return self.devices.s8  # was: flushmain
    @property
    def s9(self): return self.devices.s9  # was: roof
    
    # Main pump
    @property
    def pump(self): return self.devices.pump
    
    # Direct GPIO relays
    @property
    def dry(self): return self.gpio.dry
    @property
    def geyser(self): return self.gpio.geyser
    
    # =========================================================================
    # Helper Functions
    # =========================================================================
    
    def toggle_devices(self, device_list: List, state: bool):
        """
        Toggle multiple devices to the same state.
        
        Args:
            device_list: List of device handles
            state: True for ON, False for OFF
        """
        for device in device_list:
            if state:
                device.on()
            else:
                device.off()
                
    def play_audio(self, audio_key: str, wait: bool = True):
        """
        Play an audio file.
        
        Args:
            audio_key: Key from AUDIO_FILES dict
            wait: If True, wait for playback to finish
        """
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
        """Play beep sound multiple times."""
        for _ in range(count):
            self.play_audio("beep")
            time.sleep(interval)
            
    def kill_audio(self):
        """Stop all audio playback."""
        os.system("killall vlc")
        
    # =========================================================================
    # Timer Functions
    # =========================================================================
    
    def start_timer(self, stage_name: str) -> datetime:
        """Start a timer for a stage."""
        start_time = datetime.now()
        logger.info(f"** {stage_name} started at {start_time}")
        return start_time
        
    def end_timer(self, start_time: datetime):
        """End a timer and log duration."""
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Stage Duration: {duration}")
        
    # =========================================================================
    # Pump Control Functions
    # =========================================================================
    
    def pump_ready(self, pump_device, wait_time: float):
        """
        Activate a pump for a specified time.
        
        Args:
            pump_device: The pump device handle
            wait_time: Duration in seconds
        """
        pump_device.on()
        time.sleep(wait_time)
        pump_device.off()
        
    def pump_ready_async(self, pump_device, wait_time: float) -> threading.Thread:
        """
        Activate a pump asynchronously.
        
        Args:
            pump_device: The pump device handle
            wait_time: Duration in seconds
            
        Returns:
            Thread object
        """
        thread = threading.Thread(
            target=self.pump_ready, 
            args=(pump_device, wait_time),
            daemon=True
        )
        thread.start()
        return thread
        
    def empty_time(self, diaphragm, ro_solenoid, drain_time: float):
        """
        Empty/drain operation.
        
        Args:
            diaphragm: Diaphragm pump device
            ro_solenoid: RO solenoid device
            drain_time: Duration in seconds
        """
        self.toggle_devices([diaphragm, ro_solenoid], True)
        time.sleep(drain_time)
        self.toggle_devices([diaphragm, ro_solenoid], False)
        
    def empty_time_async(self, diaphragm, ro_solenoid, drain_time: float) -> threading.Thread:
        """Empty/drain operation asynchronously."""
        thread = threading.Thread(
            target=self.empty_time,
            args=(diaphragm, ro_solenoid, drain_time),
            daemon=True
        )
        thread.start()
        return thread
        
    # =========================================================================
    # Priming Functions
    # =========================================================================
    
    def priming(self, mainflow, localgate, main_ro, main_dp, dp_ro, 
                fill_time: float, empty_time: float):
        """
        General priming function.
        
        Args:
            mainflow: Main flow solenoid (s8)
            localgate: Local gate solenoid (s1 or s3)
            main_ro: Main RO solenoid
            main_dp: Main diaphragm pump
            dp_ro: Diaphragm RO solenoid
            fill_time: Fill duration in seconds
            empty_time: Empty duration in seconds
        """
        # Fill phase
        self.toggle_devices([mainflow, localgate, main_ro], True)
        time.sleep(fill_time)
        self.toggle_devices([mainflow, localgate, main_ro], False)
        
        # Empty/prime phase
        self.toggle_devices([main_dp, dp_ro], True)
        time.sleep(empty_time)
        self.toggle_devices([main_dp, dp_ro], False)
        
    def priming_shampoo(self, fill_time: float, empty_time: float):
        """Priming for shampoo tank."""
        logger.info(f"Priming shampoo: fill={fill_time}s, empty={empty_time}s")
        self.priming(self.s8, self.s1, self.ro1, self.d1, self.ro2, fill_time, empty_time)
        
    def priming_disinfectant(self, fill_time: float):
        """Priming for disinfectant tank."""
        logger.info(f"Priming disinfectant: fill={fill_time}s")
        self.priming(self.s8, self.s3, self.ro3, self.d2, self.ro4, fill_time, 6)
        
    # =========================================================================
    # Core Bath Functions
    # =========================================================================
    
    def Shampoo(self, qr_return: str, duration: float, pump_wait: float):
        """
        Shampoo stage.
        
        Args:
            qr_return: QR code/session identifier
            duration: Shampoo duration in seconds
            pump_wait: Pump activation time
        """
        curr_act = "Shampoo"
        st = self.start_timer(curr_act)
        
        # Start pump asynchronously
        pump_thread = self.pump_ready_async(self.p1, pump_wait)
        
        # Play audio
        self.play_audio("shampoo")
        self.play_audio("shampoo")
        self.beep()
        
        # Turn ON: s8, s1, s2, s4, d1, pump
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], False)
        
        logger.info(f"Shampoo complete for {qr_return}")
        self.end_timer(st)
        
    def Water(self, duration: float):
        """
        Water rinse stage.
        
        Args:
            duration: Water duration in seconds
        """
        curr_act = "Water"
        st = self.start_timer(curr_act)
        
        # Turn ON: s8, s5, s2, s4, pump
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], False)
        
        self.end_timer(st)
        
    def Conditioner(self, qr_return: str, duration: float, pump_wait: float):
        """
        Conditioner stage.
        
        Args:
            qr_return: QR code/session identifier
            duration: Conditioner duration in seconds
            pump_wait: Pump activation time
        """
        curr_act = "Conditioner"
        st = self.start_timer(curr_act)
        
        # Start pump asynchronously
        pump_thread = self.pump_ready_async(self.p2, pump_wait)
        
        # Play audio
        self.play_audio("conditioner")
        
        # Turn ON: s8, s1, s2, s4, d1, pump
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], False)
        
        logger.info(f"Conditioner complete for {qr_return}")
        self.end_timer(st)
        
    def Mbath(self, qr_return: str, duration: float, pump_wait: float):
        """
        Medicated bath stage.
        
        Args:
            qr_return: QR code/session identifier
            duration: Medicated bath duration in seconds
            pump_wait: Pump activation time
        """
        curr_act = "Medicated_Bath"
        st = self.start_timer(curr_act)
        
        # Start pump asynchronously
        pump_thread = self.pump_ready_async(self.p4, pump_wait)
        
        # Play audio
        self.play_audio("conditioner")
        self.beep()
        
        # Turn ON: s8, s1, s2, s4, d1, pump
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s1, self.s2, self.s4, self.d1, self.pump], False)
        
        logger.info(f"Medicated bath complete for {qr_return}")
        self.end_timer(st)
        
    def massage_time(self, duration: float):
        """
        Massage/wait time.
        
        Args:
            duration: Wait duration in seconds
        """
        curr_act = "Massage_Time"
        st = self.start_timer(curr_act)
        
        logger.info(f"Massage Time: {duration} seconds")
        self.play_audio("massage")
        time.sleep(duration)
        
        self.end_timer(st)
        
    def Dryer(self, qr_return: str, duration: float):
        """
        Dryer stage.
        
        Args:
            qr_return: QR code/session identifier
            duration: Total dryer duration in seconds
        """
        curr_act = "Drying"
        st = self.start_timer(curr_act)
        
        self.play_audio("dryer")
        self.play_audio("dryer")
        
        dmul = 0.5  # Duration multiplier
        
        # First drying cycle
        self.dry.on()
        time.sleep(duration * dmul)
        self.dry.off()
        
        # Break
        self.play_audio("break")
        time.sleep(15)
        self.end_timer(st)
        
        # Second drying cycle
        self.dry.on()
        time.sleep(duration * dmul)
        self.beep()
        self.dry.off()
        
        if qr_return == "Testing_only_Dryer":
            self.kill_audio()
            
        logger.info(f"Dryer complete for {qr_return}")
        self.end_timer(st)
        
    def Disinfectant(self, duration: float, pump_wait: float):
        """
        Disinfectant stage.
        
        Args:
            duration: Disinfectant duration in seconds
            pump_wait: Pump activation time
        """
        curr_act = "Disinfectant"
        st = self.start_timer(curr_act)
        
        diwt = pump_wait * 0.8
        
        # Start pump asynchronously
        pump_thread = self.pump_ready_async(self.p4, diwt)
        
        self.play_audio("disinfect")
        
        # Phase 1: Disinfectant spray
        self.toggle_devices([self.s8, self.s3, self.s4, self.s2, self.d2, self.pump], True)
        time.sleep(duration)
        self.toggle_devices([self.s8, self.s3, self.s4, self.s2, self.d2, self.pump], False)
        
        # Phase 2: Water rinse
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], True)
        time.sleep(duration)
        self.beep()
        self.toggle_devices([self.s8, self.s5, self.s2, self.s4, self.pump], False)
        
        self.end_timer(st)
        
    def Flush(self, duration: float):
        """
        Auto-flush stage.
        
        Args:
            duration: Flush duration per phase in seconds
        """
        curr_act = "Autoflush"
        st = self.start_timer(curr_act)
        
        # Phase 1: Top flush (s6 was 'top', s8 was 'flushmain')
        self.toggle_devices([self.s6, self.pump, self.s8], True)
        time.sleep(duration)
        self.toggle_devices([self.s6, self.pump], False)
        
        # Phase 2: Bottom flush (s7 was 'bottom')
        self.toggle_devices([self.s7, self.pump], True)
        time.sleep(duration)
        self.toggle_devices([self.s7, self.pump, self.s8], False)
        
        self.play_audio("thankyou")
        self.play_audio("powerdown")
        
        logger.info("Flush complete")
        self.end_timer(st)
        
    def Empty_tank(self, duration: float):
        """
        Empty tank operation.
        
        Args:
            duration: Empty duration in seconds
        """
        curr_act = "EmptyingTank"
        st = self.start_timer(curr_act)
        
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
        """Turn off all devices (emergency stop)."""
        logger.warning("ALLCLOSE - Turning off all devices")
        self.devices.all_off()
        self.gpio.all_off()
        
    def Lightson(self):
        """Turn on lights (placeholder - rglight not defined)."""
        # TODO: Implement when rglight is defined
        logger.info("Lights ON")
        
    def Lightsoff(self):
        """Turn off lights."""
        # TODO: Implement when rglight is defined
        self.play_audio("powerdown")
        logger.info("Lights OFF")
        
    def control_roof_lights(self):
        """Control roof lights based on time of day."""
        current_time = datetime.now().time()
        
        # Lights on from 5 PM to 5 AM
        on_time = datetime.strptime("17:00", "%H:%M").time()
        off_time = datetime.strptime("05:00", "%H:%M").time()
        
        if on_time <= current_time or current_time < off_time:
            self.s9.on()  # roof = s9
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
        """
        Main Spotless bath function.
        
        Args:
            qr_return: QR code/session identifier
            sval: Shampoo duration (seconds)
            cval: Conditioner duration (seconds)
            dval: Disinfectant duration (seconds)
            wval: Water duration (seconds)
            dryval: Dryer duration (seconds)
            fval: Flush duration (seconds)
            wt: Wait/pump time (seconds)
            stval: Stage value/wait time
            msgval: Massage time (seconds)
            tdry: Towel dry time (seconds)
            pr: Process type (10 = include disinfectant)
            stage: Starting stage (1-6, allows resuming)
            ctype: Conditioner type (100=normal, 200=medicated)
        """
        # Turn on roof lights (s9 was 'roof')
        self.s9.on()
        
        primeval = 30
        shampoo_empty_time = 6
        conditioner_empty_time = 12
        
        logger.info("-" * 60)
        curr_act = "Spotless Function"
        mst = self.start_timer(curr_act)
        logger.info(f"Stage: {stage}")
        logger.info(f"QR: {qr_return}, Shampoo: {sval}, Conditioner: {cval}, "
                   f"Disinfect: {dval}, Water: {wval}, Dryer: {dryval}, "
                   f"Flush: {fval}, WaitTime: {wt}, StageVal: {stval}, "
                   f"Massage: {msgval}, Towel: {tdry}, PR: {pr}, Stage: {stage}")
        
        start_time = datetime.now()
        
        # Priming the shampoo bottle
        self.priming_shampoo(primeval, shampoo_empty_time)
        
        # ON BOARDING
        for _ in range(2):
            self.play_audio("onboard")
        time.sleep(4)
        
        # Stage 1: Shampoo
        if stage <= 1:
            self.Shampoo(qr_return, sval, wt)
            self.massage_time(msgval)
            
        # Stage 2: Water 1
        if stage <= 2:
            self.beep()
            self.play_audio("water")
            self.Water(wval)
            # Prime for conditioner
            self.priming_shampoo(primeval, conditioner_empty_time)
            
        # Stage 3: Conditioner
        if stage <= 3:
            if ctype == 100:
                self.Conditioner(qr_return, cval, wt)
            elif ctype == 200:
                self.Mbath(qr_return, cval, wt)
            self.massage_time(msgval)
            self.beep()
            
        # Stage 4: Water 2
        if stage <= 4:
            self.play_audio("water2")
            new_wval = 2 * wval
            self.Water(new_wval)
            
        # Stage 5: Towel Dry
        if stage <= 5:
            curr_act = "Towel Dry"
            st = self.start_timer(curr_act)
            for _ in range(2):
                self.play_audio("towel")
            time.sleep(tdry)
            self.end_timer(st)
            
        # Stage 6: Dryer
        if stage <= 6:
            self.Dryer(qr_return, dryval)
            
        # OFF BOARD
        for _ in range(2):
            self.play_audio("offboard")
            time.sleep(3)
            
        # Disinfectant (if pr == 10)
        if pr == 10:
            for _ in range(2):
                self.play_audio("laststep")
                self.play_audio("disinfect")
                time.sleep(stval)
            self.Disinfectant(dval, wt)
            
        # Empty tanks asynchronously
        emp_sh = self.empty_time_async(self.d1, self.ro2, 8)
        emp_dt = self.empty_time_async(self.d2, self.ro4, 8)
        
        # Thank you
        self.play_audio("thankyou")
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Session Duration: {duration}")
        logger.info("-" * 60)
        self.end_timer(mst)
        
        self.kill_audio()
        self.Lightsoff()
        self.s9.off()  # roof off
        self.control_roof_lights()
        
    def fromDisinfectant(self, qr_return: str, sval: float, cval: float, 
                         dval: float, wval: float, dryval: float, fval: float,
                         wt: float, stval: float, msgval: float, tdry: float,
                         pr: int, stage: int, ctype: int):
        """
        Run session starting from disinfectant stage.
        
        Used when resuming a session that was interrupted after the bath.
        """
        curr_act = "From_Disinfectant"
        logger.info(f"** Customer QR Activated from Disinfectant Stage: {qr_return}")
        start_time = datetime.now()
        
        # Prime disinfectant
        self.priming_disinfectant(12)
        
        # Disinfectant
        self.Disinfectant(dval, wt)
        
        # Empty tanks asynchronously
        emp_sh = threading.Thread(target=self.Empty_tank, args=(30,), daemon=True)
        emp_sh.start()
        
        emp_dt = threading.Thread(target=self.Empty_tank, args=(30,), daemon=True)
        emp_dt.start()
        
        # Flush
        self.Flush(fval)
        
        # Thank you
        self.play_audio("thankyou")
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"** Total Duration for QR {qr_return}: {duration}")
        
        self.kill_audio()
        self.Lightsoff()
        
    # =========================================================================
    # Quick Test Functions
    # =========================================================================
    
    def just_shampoo(self, qr_return: str):
        """Quick test: shampoo only."""
        self.priming_shampoo(12, 6)
        self.Shampoo(qr_return, 60, 10)
        self.kill_audio()
        
    def just_water(self, duration: float):
        """Quick test: water only."""
        self.Water(duration)
        self.kill_audio()
        
    def test_relays(self):
        """Test all relays sequentially."""
        logger.info("Testing all relays...")
        
        # Test ESP32 devices
        all_devices = [
            self.p1, self.p2, self.p3, self.p4, self.p5,
            self.ro1, self.ro2, self.ro3, self.ro4,
            self.d1, self.d2,
            self.s1, self.s2, self.s3, self.s4, self.s5, 
            self.s6, self.s7, self.s8, self.s9,
            self.pump
        ]
        
        for device in all_devices:
            logger.info(f"Testing {device.device.name}...")
            device.on()
            time.sleep(2)
            device.off()
            time.sleep(0.5)
            
        # Test GPIO relays
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
        """
        Demo mode: Run all relays sequentially in a specific sequence.
        
        Sequence for each ESP32 node (backup2, backup1, rs2, rs1, fp1, p1, s1):
        - Node 1: p1, p2, ro2, ro1, d1, p3, pump
        - Node 2: p4, p5, ro4, ro3, d2, s7, s9
        - Node 3: s1, s2, s4, s3, s5, s6, s8
        
        Then Raspberry Pi GPIO relays:
        - dry (GPIO 14), geyser (GPIO 18)
        
        Each relay runs for 5 seconds.
        Works with any number of online nodes - offline nodes are skipped gracefully.
        """
        logger.info("=" * 60)
        logger.info(f"Starting DEMO mode for {qr_return}")
        logger.info("=" * 60)
        
        # Relay sequence: backup2, backup1, rs2, rs1, fp1, p1, s1
        # This corresponds to relays: 7, 6, 5, 4, 3, 2, 1
        
        # Node 1 sequence: p1 (backup2), p2 (backup1), ro2 (rs2), ro1 (rs1), d1 (fp1), p3 (p1), pump (s1)
        logger.info("\n--- Node 1 (spotless_node1) ---")
        node1_sequence = [self.p1, self.p2, self.ro2, self.ro1, self.d1, self.p3, self.pump]
        node1_names = ["p1 (backup2)", "p2 (backup1)", "ro2 (rs2)", "ro1 (rs1)", "d1 (fp1)", "p3 (p1)", "pump (s1)"]
        
        for device, name in zip(node1_sequence, node1_names):
            logger.info(f"  Activating {name}...")
            success = device.on()
            if not success:
                logger.warning(f"    ⚠️  Failed to activate {name} (node may be offline)")
            time.sleep(5)
            device.off()
            time.sleep(0.5)
        
        # Node 2 sequence: p4 (backup2), p5 (backup1), ro4 (rs2), ro3 (rs1), d2 (fp1), s7 (p1), s9 (s1)
        logger.info("\n--- Node 2 (spotless_node2) ---")
        node2_sequence = [self.p4, self.p5, self.ro4, self.ro3, self.d2, self.s7, self.s9]
        node2_names = ["p4 (backup2)", "p5 (backup1)", "ro4 (rs2)", "ro3 (rs1)", "d2 (fp1)", "s7 (p1)", "s9 (s1)"]
        
        for device, name in zip(node2_sequence, node2_names):
            logger.info(f"  Activating {name}...")
            success = device.on()
            if not success:
                logger.warning(f"    ⚠️  Failed to activate {name} (node may be offline)")
            time.sleep(5)
            device.off()
            time.sleep(0.5)
        
        # Node 3 sequence: s1 (backup2), s2 (backup1), s4 (rs2), s3 (rs1), s5 (fp1), s6 (p1), s8 (s1)
        logger.info("\n--- Node 3 (spotless_node3) ---")
        node3_sequence = [self.s1, self.s2, self.s4, self.s3, self.s5, self.s6, self.s8]
        node3_names = ["s1 (backup2)", "s2 (backup1)", "s4 (rs2)", "s3 (rs1)", "s5 (fp1)", "s6 (p1)", "s8 (s1)"]
        
        for device, name in zip(node3_sequence, node3_names):
            logger.info(f"  Activating {name}...")
            success = device.on()
            if not success:
                logger.warning(f"    ⚠️  Failed to activate {name} (node may be offline)")
            time.sleep(5)
            device.off()
            time.sleep(0.5)
        
        # Raspberry Pi GPIO relays
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


# =============================================================================
# Session Configuration Presets
# =============================================================================
SESSION_PRESETS = {
    "small": {
        "description": "Small Pet Bath Session",
        "params": {
            "sval": 120,      # Shampoo duration
            "cval": 120,      # Conditioner duration
            "dval": 60,       # Disinfectant duration
            "wval": 60,       # Water duration
            "dryval": 480,    # Dryer duration
            "fval": 60,       # Flush duration
            "wt": 30,         # Wait time
            "stval": 10,      # Stage value
            "msgval": 10,     # Massage time
            "tdry": 30,       # Towel dry time
            "pr": 20,         # Process type
            "stage": 1,       # Starting stage
            "ctype": 100,     # Conditioner type (normal)
        }
    },
    "large": {
        "description": "Large Pet Bath Session",
        "params": {
            "sval": 150,
            "cval": 150,
            "dval": 60,
            "wval": 80,
            "dryval": 600,
            "fval": 60,
            "wt": 50,
            "stval": 10,
            "msgval": 10,
            "tdry": 30,
            "pr": 20,
            "stage": 1,
            "ctype": 100,
        }
    },
    "custdiy": {
        "description": "Customer DIY Session",
        "params": {
            "sval": 100,
            "cval": 100,
            "dval": 60,
            "wval": 60,
            "dryval": 600,
            "fval": 60,
            "wt": 12,
            "stval": 10,
            "msgval": 10,
            "tdry": 30,
            "pr": 10,
            "stage": 1,
            "ctype": 100,
        }
    },
    "medsmall": {
        "description": "Medicated Bath - Small Pet",
        "params": {
            "sval": 80,
            "cval": 80,
            "dval": 60,
            "wval": 60,
            "dryval": 480,
            "fval": 60,
            "wt": 30,
            "stval": 10,
            "msgval": 10,
            "tdry": 30,
            "pr": 20,
            "stage": 1,
            "ctype": 200,  # Medicated
        }
    },
    "medlarge": {
        "description": "Medicated Bath - Large Pet",
        "params": {
            "sval": 100,
            "cval": 100,
            "dval": 60,
            "wval": 60,
            "dryval": 600,
            "fval": 60,
            "wt": 50,
            "stval": 10,
            "msgval": 10,
            "tdry": 30,
            "pr": 20,
            "stage": 1,
            "ctype": 200,  # Medicated
        }
    },
    "onlydisinfectant": {
        "description": "Disinfectant Only",
        "params": {
            "sval": 100,
            "cval": 100,
            "dval": 60,
            "wval": 60,
            "dryval": 600,
            "fval": 60,
            "wt": 15,
            "stval": 10,
            "msgval": 10,
            "tdry": 30,
            "pr": 20,
            "stage": 1,
            "ctype": 200,
        }
    },
}


def get_session_params(session_type: str) -> dict:
    """Get parameters for a session type."""
    preset = SESSION_PRESETS.get(session_type)
    if preset:
        return preset["params"].copy()
    return None
