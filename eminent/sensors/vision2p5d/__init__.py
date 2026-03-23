"""
MN96100C 2.5D Vision Sensor Configuration Module
Provides OpenCV-style object-oriented interface for sensor configuration
"""

from typing import Tuple, Optional
from collections import deque
import numpy as np
import cv2
import logging
import time



from .mn96100c import USBDeviceComm

# Constants
INIT_SLEEP_TIME = 0.2
RELEASE_SLEEP_TIME = 0.2

# Warmup constants
WARMUP_IDLE_THRESHOLD = 300  # seconds (5 minutes)
WARMUP_DURATION = 10         # seconds
READ_LOG_MAXLEN = 100        # keep last N read timestamps


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

        # Read timestamp log: stores time.time() of each successful read (max 100)
        self._read_timestamps: deque = deque(maxlen=READ_LOG_MAXLEN)

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
        
    def _needs_warmup(self) -> bool:
        """Return True if idle time since last successful read exceeds WARMUP_IDLE_THRESHOLD."""
        if not self._read_timestamps:
            return False
        idle = time.time() - self._read_timestamps[-1]
        return idle > WARMUP_IDLE_THRESHOLD

    def _run_warmup(self):
        """Stream frames for WARMUP_DURATION seconds without returning data (camera warm-up)."""
        self._logger.info(
            f"Camera idle for >{WARMUP_IDLE_THRESHOLD}s — running {WARMUP_DURATION}s warmup..."
        )
        deadline = time.time() + WARMUP_DURATION
        while time.time() < deadline:
            try:
                self.usb_comm.get_image()
            except Exception:
                pass
        self._logger.info("Warmup complete.")

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
                self._read_timestamps.append(time.time())
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
