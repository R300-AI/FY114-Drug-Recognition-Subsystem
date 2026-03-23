"""
MN96100C 2.5D Vision Sensor Configuration Module
Provides OpenCV-style object-oriented interface for sensor configuration
"""

from typing import Tuple, Optional
from pathlib import Path
import numpy as np
import cv2
import logging
import time



from .mn96100c import USBDeviceComm

# Constants
INIT_SLEEP_TIME = 0.2
RELEASE_SLEEP_TIME = 0.2

# Warmup constants
# Every 30s of idle time adds 1s of warmup, up to 10s max
# (e.g. 30s idle → 1s warmup, 150s → 5s, ≥300s → 10s)
WARMUP_STEP_SECONDS = 30   # idle seconds per warmup second
WARMUP_MAX_SECONDS  = 10   # maximum warmup duration

# Timestamp log file (one ISO timestamp per line, reset on each startup)
_TIMESTAMP_LOG_PATH = Path(__file__).parent / "read_timestamps.log"


class MN96100CConfig:
    """
    Configuration class for MN96100C 2.5D Vision Sensor.
    Contains all command definitions organized by functionality.
    """
    
    class ExposureSetting:
        """Exposure time/AE setting commands."""
        DEFAULT = [0x44, 0x04, 0x00]
        UNKNOWN = [0x44, 0x04, 0x9F]
    
    class FrameRate:
        """Frame rate control commands."""
        FULL = [0x44, 0x07, 0x00]          # 1/1 - Full frame rate
        HALF = [0x44, 0x07, 0x01]          # 1/2 - Half frame rate  
        QUARTER = [0x44, 0x07, 0x02]       # 1/4 - Quarter frame rate
        EIGHTH = [0x44, 0x07, 0x03]        # 1/8 - Eighth frame rate
        SIXTEENTH = [0x44, 0x07, 0x04]     # 1/16 - Sixteenth frame rate
    
    class LEDCurrent:
        """LED driving current commands."""
        LOW = [0x44, 0x0A, 0x03]           # 50mA x 2
        MEDIUM = [0x44, 0x0A, 0x17]        # 100mA x 2
        HIGH = [0x44, 0x0A, 0x2B]          # 200mA x 2
        ULTRA_HIGH = [0x44, 0x0A, 0x3F]    # 400mA x 2

    class TXOutput:
        """TX output resolution commands."""
        RESOLUTION_160x160 = [0x44, 0xF3, 0x00]
        
        # Frame dimensions
        WIDTH = 160
        HEIGHT = 160

    class WorkMode:
        """Sensor operation mode commands."""
        START_SENSING = [0x44, 0x12, 0x01]
        STOP_SENSING = [0x44, 0x12, 0x00]


class VideoCapture:
    """
    OpenCV-style VideoCapture for MN96100C 2.5D Vision Sensor.

    Provides simple interface for capturing frames from the sensor with
    fixed configuration parameters.
    """

    def __init__(
        self,
        exposure_setting=MN96100CConfig.ExposureSetting.DEFAULT,
        frame_rate=MN96100CConfig.FrameRate.QUARTER,
        led_current=MN96100CConfig.LEDCurrent.ULTRA_HIGH,
        tx_output=MN96100CConfig.TXOutput.RESOLUTION_160x160,
        *,
        vid: int = 0x04F3,
        pid: int = 0x0C7E,
    ):
        """
        Initialize VideoCapture with MN96100C configuration.

        Args:
            exposure_setting: Exposure time/AE setting command
            frame_rate: Frame rate control command
            led_current: LED current setting command
            tx_output: TX output resolution command
            vid: USB Vendor ID (from Hardware Ids), e.g. 0x04F3
            pid: USB Product ID (from Hardware Ids), e.g. 0x0C7E
        """
        self._logger = logging.getLogger(__name__)
        self.usb_comm = None
        self._is_opened = False

        # Last successful read time, loaded from previous session's log file
        self._last_read_time: Optional[float] = self._load_last_timestamp()
        self._setup_timestamp_logger()

        # Store device identifiers for later use
        self.vid = vid
        self.pid = pid

        # Use frame dimensions from config
        self.width = MN96100CConfig.TXOutput.WIDTH
        self.height = MN96100CConfig.TXOutput.HEIGHT

        try:
            self._initialize_device(exposure_setting, frame_rate, led_current, tx_output)
        except Exception as e:
            self._logger.error(f"Failed to initialize VideoCapture: {e}")
            self._cleanup()
            raise

    def _initialize_device(self, exposure_setting, frame_rate, led_current, tx_output):
        """Initialize and configure the USB device."""
        self.usb_comm = USBDeviceComm(vid=self.vid, pid=self.pid)
        self.usb_comm.connect()

        # Send configuration commands
        self._send_configuration_commands(exposure_setting, frame_rate, led_current, tx_output)

        # Start sensing
        self.usb_comm.send_command(MN96100CConfig.WorkMode.START_SENSING)
        time.sleep(INIT_SLEEP_TIME)

        self._is_opened = True
        self._logger.info("VideoCapture initialized successfully")
    
    def _send_configuration_commands(self, exposure_setting, frame_rate, led_current, tx_output):
        """Send all configuration commands to the device."""
        commands = [exposure_setting, frame_rate, led_current, tx_output]
        command_names = ["exposure_setting", "frame_rate", "led_current", "tx_output"]
        
        for command, name in zip(commands, command_names):
            try:
                self.usb_comm.send_command(command)
                self._logger.debug(f"Sent {name} command: {command}")
            except Exception as e:
                self._logger.error(f"Failed to send {name} command: {e}")
                raise
        
    def _load_last_timestamp(self) -> Optional[float]:
        """
        Read the last line of the previous session's timestamp log to get the
        last successful read time, then reset the log file for the new session.
        Returns the timestamp as float (Unix time), or None if unavailable.
        """
        last_time = None
        try:
            if _TIMESTAMP_LOG_PATH.exists():
                lines = _TIMESTAMP_LOG_PATH.read_text().splitlines()
                for line in reversed(lines):
                    line = line.strip()
                    if line:
                        last_time = float(line)
                        break
        except Exception as e:
            self._logger.warning(f"Could not read timestamp log: {e}")
        finally:
            # Always reset the log file so it doesn't grow unbounded
            try:
                _TIMESTAMP_LOG_PATH.write_text("")
            except Exception as e:
                self._logger.warning(f"Could not reset timestamp log: {e}")
        return last_time

    def _setup_timestamp_logger(self):
        """Set up a dedicated file logger that appends one Unix timestamp per read."""
        self._ts_logger = logging.getLogger(f"{__name__}.timestamps")
        self._ts_logger.setLevel(logging.DEBUG)
        self._ts_logger.propagate = False  # don't bubble up to root logger

        if not self._ts_logger.handlers:
            handler = logging.FileHandler(_TIMESTAMP_LOG_PATH, mode='a', encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            self._ts_logger.addHandler(handler)

    def _warmup_duration(self) -> int:
        """
        Compute required warmup duration based on idle time.

        Staircase: every WARMUP_STEP_SECONDS of idle = 1s warmup, capped at WARMUP_MAX_SECONDS.
        Returns WARMUP_MAX_SECONDS on first startup (no previous timestamp).
        """
        if self._last_read_time is None:
            return WARMUP_MAX_SECONDS   # 首次啟動 → 最長暖機
        idle = time.time() - self._last_read_time
        return min(int(idle // WARMUP_STEP_SECONDS), WARMUP_MAX_SECONDS)

    def _needs_warmup(self) -> bool:
        """Return True if computed warmup duration is at least 1 second."""
        return self._warmup_duration() > 0

    def _run_warmup(self):
        """Stream frames for the computed warmup duration, printing n/m countdown."""
        duration = self._warmup_duration()
        if self._last_read_time is None:
            print(f"[sensor] 首次啟動 → 暖機 {duration}s", flush=True)
        else:
            idle = time.time() - self._last_read_time
            print(f"[sensor] 距上次讀取 {idle:.0f}s → 暖機 {duration}s", flush=True)

        for i in range(duration):
            print(f"[sensor] 暖機中 {i + 1}/{duration}", flush=True)
            deadline = time.time() + 1.0
            while time.time() < deadline:
                try:
                    self.usb_comm.get_image()
                except Exception:
                    pass

        print("[sensor] 暖機完成", flush=True)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read frame from device.

        If the camera has been idle for more than WARMUP_IDLE_THRESHOLD seconds,
        a WARMUP_DURATION-second warmup stream is executed first (frames discarded).
        Each successful read is logged; only the latest READ_LOG_MAXLEN entries are kept.

        Returns:
            Tuple of (success, frame) where:
            - success: True if frame was read successfully
            - frame: numpy array containing BGR image data, or None if failed
        """
        if not self.isOpened():
            self._logger.warning("Device not opened")
            return False, None

        if self._needs_warmup():
            self._run_warmup()

        try:
            raw_data, _ = self.usb_comm.get_image()

            if not raw_data:
                return False, None

            result = self._process_raw_data(raw_data)
            if result[0]:  # success
                self._last_read_time = time.time()
                self._ts_logger.debug(str(self._last_read_time))
            return result

        except Exception as e:
            self._logger.error(f"Error reading frame: {e}")
            return False, None
    
    def _process_raw_data(self, raw_data: str) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Process raw hexadecimal data into BGR image.
        
        Args:
            raw_data: Raw hexadecimal string data from device
            
        Returns:
            Tuple of (success, processed_frame)
        """
        try:
            image_array = np.frombuffer(bytes.fromhex(raw_data), dtype=np.uint8)
            
            expected_size = self.width * self.height
            if image_array.size != expected_size:
                self._logger.warning(f"Invalid image size: {image_array.size}, expected: {expected_size}")
                return False, None
                
            # Reshape and convert to BGR
            frame_gray = image_array.reshape(self.height, self.width)
            frame_bgr = cv2.cvtColor(frame_gray, cv2.COLOR_GRAY2BGR)
            
            return True, frame_bgr
            
        except Exception as e:
            self._logger.error(f"Error processing raw data: {e}")
            return False, None
    
    def isOpened(self) -> bool:
        """
        Check if VideoCapture is opened.
        
        Returns:
            True if device is opened and ready, False otherwise
        """
        return self._is_opened and self.usb_comm is not None
    
    def release(self):
        """Release VideoCapture resources and disconnect from device."""
        if not self._is_opened:
            return
            
        try:
            self._stop_sensing()
            self._cleanup()
            self._logger.info("VideoCapture released successfully")
            
        except Exception as e:
            self._logger.error(f"Error releasing VideoCapture: {e}")
    
    def _stop_sensing(self):
        """Stop the sensor from sensing."""
        if self.usb_comm:
            self.usb_comm.send_command(MN96100CConfig.WorkMode.STOP_SENSING)
            time.sleep(RELEASE_SLEEP_TIME)
    
    def _cleanup(self):
        """Clean up resources."""
        if self.usb_comm:
            try:
                self.usb_comm.disconnect()
            except Exception as e:
                self._logger.error(f"Error disconnecting USB: {e}")
            finally:
                self.usb_comm = None
                
        self._is_opened = False
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
    
    def __del__(self):
        """Destructor to ensure resources are released."""
        self.release()

if __name__ == "__main__":
    # Example usage
    cap = VideoCapture()
    
    try:
        while True:
            success, frame = cap.read()
            if success and frame is not None:
                # Display frame using OpenCV
                cv2.imshow("MN96100C Frame", cv2.resize(frame, (640, 640)))
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print("Failed to read frame")
                break
                
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("VideoCapture released")
