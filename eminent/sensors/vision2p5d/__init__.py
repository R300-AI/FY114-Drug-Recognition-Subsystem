"""
MN96100C 2.5D Vision Sensor — OpenCV-style interface

VideoCapture handles:
  - USB device init & configuration
  - Warmup (duration derived from last-session timestamp log)
  - Per-frame depth analysis, state detection, and state logging
  - Timestamp logging for next-session warmup calculation

Log files (fixed paths, reset on each init):
  - logs/drawer_state.log    — per-frame: time, state, intensity, threshold_open, threshold_closed
  - <package>/read_timestamps.log — Unix timestamps for warmup calculation
"""

from collections import deque
from pathlib import Path
from typing import Optional, Tuple
import logging
import time

import cv2
import numpy as np

from .mn96100c import USBDeviceComm

# ── Constants ──────────────────────────────────────────────────────────────
INIT_SLEEP_TIME    = 0.2
RELEASE_SLEEP_TIME = 0.2

WARMUP_STEP_SECONDS = 30   # idle seconds per warmup second
WARMUP_MAX_SECONDS  = 10   # maximum warmup duration

# Timestamp log: inside package dir, survives across runs, never grows large
_TIMESTAMP_LOG_PATH = Path(__file__).parent / "read_timestamps.log"

# State log: project logs/ dir, reset on every init
_STATE_LOG_PATH = Path("logs/drawer_state.log")


# ── Config classes ─────────────────────────────────────────────────────────

class MN96100CConfig:
    class ExposureSetting:
        DEFAULT = [0x44, 0x04, 0x00]
        UNKNOWN = [0x44, 0x04, 0x9F]

    class FrameRate:
        FULL      = [0x44, 0x07, 0x00]
        HALF      = [0x44, 0x07, 0x01]
        QUARTER   = [0x44, 0x07, 0x02]
        EIGHTH    = [0x44, 0x07, 0x03]
        SIXTEENTH = [0x44, 0x07, 0x04]

    class LEDCurrent:
        LOW       = [0x44, 0x0A, 0x03]
        MEDIUM    = [0x44, 0x0A, 0x17]
        HIGH      = [0x44, 0x0A, 0x2B]
        ULTRA_HIGH= [0x44, 0x0A, 0x3F]

    class TXOutput:
        RESOLUTION_160x160 = [0x44, 0xF3, 0x00]
        WIDTH  = 160
        HEIGHT = 160

    class WorkMode:
        START_SENSING = [0x44, 0x12, 0x01]
        STOP_SENSING  = [0x44, 0x12, 0x00]


# ── VideoCapture ───────────────────────────────────────────────────────────

class VideoCapture:
    """
    OpenCV-style VideoCapture for MN96100C 2.5D Vision Sensor.

    Internally manages:
      - Warmup (blocking, called during __init__)
      - Depth analysis + state detection on every read()
      - Per-frame logging to logs/drawer_state.log

    After each successful read(), access:
      cap.state      — 完全開啟 / 閉合中 / 完全閉合 / 未知
      cap.intensity  — MAX-smoothed intensity value
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
        # Depth analysis params
        threshold_open: float = 80.0,
        threshold_closed: float = 150.0,
        min_state_duration: int = 5,
        min_open_duration: int = 3,
        min_close_duration: int = 5,
        roi: Optional[dict] = None,
        smoothing_window: int = 1,
        enable_smoothing: bool = False,
        history_size: int = 500,
    ):
        self._logger = logging.getLogger(__name__)
        self.usb_comm = None
        self._is_opened = False

        self.vid = vid
        self.pid = pid
        self.width  = MN96100CConfig.TXOutput.WIDTH
        self.height = MN96100CConfig.TXOutput.HEIGHT

        # Depth analysis
        from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector
        self._depth_analyzer  = DepthAnalyzer()
        self._state_detector  = DrawerStateDetector(
            threshold_open=threshold_open,
            threshold_closed=threshold_closed,
            min_state_duration=min_state_duration,
            min_open_duration=min_open_duration,
            min_close_duration=min_close_duration,
        )
        self._history         = deque(maxlen=history_size)
        self._roi             = roi or {}
        self._smoothing_window = smoothing_window
        self._enable_smoothing = enable_smoothing

        # Public state (updated on every read)
        self.state     = "未知"
        self.intensity = 0.0

        # Warmup: read last session timestamp before resetting log
        self._last_read_time: Optional[float] = self._load_last_timestamp()

        # Setup loggers
        self._setup_timestamp_logger()
        self._setup_state_logger()

        # Connect device → run warmup → mark ready
        try:
            self._initialize_device(exposure_setting, frame_rate, led_current, tx_output)
        except Exception as e:
            self._logger.error(f"Failed to initialize VideoCapture: {e}")
            self._cleanup()
            raise

    # ── Init helpers ───────────────────────────────────────────────────────

    def _initialize_device(self, exposure_setting, frame_rate, led_current, tx_output):
        self.usb_comm = USBDeviceComm(vid=self.vid, pid=self.pid)
        self.usb_comm.connect()

        for cmd, name in zip(
            [exposure_setting, frame_rate, led_current, tx_output],
            ["exposure_setting", "frame_rate", "led_current", "tx_output"],
        ):
            try:
                self.usb_comm.send_command(cmd)
            except Exception as e:
                self._logger.error(f"Failed to send {name}: {e}")
                raise

        self.usb_comm.send_command(MN96100CConfig.WorkMode.START_SENSING)
        time.sleep(INIT_SLEEP_TIME)
        self._is_opened = True

        # Warmup (blocking) — UI should show after this returns
        self._run_warmup()

        # Mark warm so read() doesn't re-trigger
        self._last_read_time = time.time()

    def _load_last_timestamp(self) -> Optional[float]:
        last_time = None
        try:
            if _TIMESTAMP_LOG_PATH.exists():
                for line in reversed(_TIMESTAMP_LOG_PATH.read_text().splitlines()):
                    line = line.strip()
                    if line:
                        last_time = float(line)
                        break
        except Exception as e:
            self._logger.warning(f"Could not read timestamp log: {e}")
        finally:
            try:
                _TIMESTAMP_LOG_PATH.write_text("")
            except Exception as e:
                self._logger.warning(f"Could not reset timestamp log: {e}")
        return last_time

    def _setup_timestamp_logger(self):
        self._ts_logger = logging.getLogger(f"{__name__}.timestamps")
        self._ts_logger.setLevel(logging.DEBUG)
        self._ts_logger.propagate = False
        if not self._ts_logger.handlers:
            h = logging.FileHandler(_TIMESTAMP_LOG_PATH, mode='a', encoding='utf-8')
            h.setFormatter(logging.Formatter('%(message)s'))
            self._ts_logger.addHandler(h)

    def _setup_state_logger(self):
        _STATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state_logger = logging.getLogger(f"{__name__}.state")
        self._state_logger.setLevel(logging.DEBUG)
        self._state_logger.propagate = False
        self._state_logger.handlers.clear()
        h = logging.FileHandler(_STATE_LOG_PATH, mode='w', encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s  %(message)s',
                                         datefmt='%Y-%m-%d %H:%M:%S'))
        self._state_logger.addHandler(h)

    # ── Warmup ────────────────────────────────────────────────────────────

    def _warmup_duration(self) -> int:
        if self._last_read_time is None:
            return WARMUP_MAX_SECONDS
        idle = time.time() - self._last_read_time
        return min(int(idle // WARMUP_STEP_SECONDS), WARMUP_MAX_SECONDS)

    def _run_warmup(self):
        duration = self._warmup_duration()
        if duration == 0:
            print("[sensor] 暖機跳過（距上次讀取時間短）", flush=True)
            return
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

    # ── Read ──────────────────────────────────────────────────────────────

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.isOpened():
            return False, None
        try:
            raw_data, _ = self.usb_comm.get_image()
            if not raw_data:
                return False, None

            ret, frame = self._process_raw_data(raw_data)
            if ret:
                self._process_depth(frame)
                self._last_read_time = time.time()
                self._ts_logger.debug(str(self._last_read_time))
            return ret, frame

        except Exception as e:
            self._logger.error(f"Error reading frame: {e}")
            return False, None

    def _process_depth(self, frame: np.ndarray):
        """Depth analysis → state detection → terminal print + file log."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

        if self._roi.get('enabled', False):
            r = self._roi
            gray = gray[r['y1']:r['y2'], r['x1']:r['x2']]

        metrics = self._depth_analyzer.calculate_depth_metrics(gray)
        self._history.append(metrics['mean'])

        if self._enable_smoothing and self._smoothing_window > 1:
            smoothed = max(list(self._history)[-self._smoothing_window:])
        else:
            smoothed = metrics['mean']

        self.state     = self._state_detector.update(smoothed)
        self.intensity = smoothed

        open_th   = self._state_detector.threshold_open
        closed_th = self._state_detector.threshold_closed

        print(
            f"[sensor] state={self.state:<6}  intensity={smoothed:6.1f}"
            f"  open={open_th}  closed={closed_th}",
            flush=True,
        )
        self._state_logger.info(
            f"state={self.state}  intensity={smoothed:.1f}"
            f"  threshold_open={open_th}  threshold_closed={closed_th}"
        )

    def _process_raw_data(self, raw_data: str) -> Tuple[bool, Optional[np.ndarray]]:
        try:
            image_array = np.frombuffer(bytes.fromhex(raw_data), dtype=np.uint8)
            expected = self.width * self.height
            if image_array.size != expected:
                return False, None
            frame_bgr = cv2.cvtColor(
                image_array.reshape(self.height, self.width),
                cv2.COLOR_GRAY2BGR,
            )
            return True, frame_bgr
        except Exception as e:
            self._logger.error(f"Error processing raw data: {e}")
            return False, None

    # ── Control ───────────────────────────────────────────────────────────

    def isOpened(self) -> bool:
        return self._is_opened and self.usb_comm is not None

    def release(self):
        if not self._is_opened:
            return
        try:
            self.usb_comm.send_command(MN96100CConfig.WorkMode.STOP_SENSING)
            time.sleep(RELEASE_SLEEP_TIME)
        except Exception:
            pass
        self._cleanup()

    def _cleanup(self):
        if self.usb_comm:
            try:
                self.usb_comm.disconnect()
            except Exception:
                pass
            finally:
                self.usb_comm = None
        self._is_opened = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()

    def __del__(self):
        self.release()


if __name__ == "__main__":
    cap = VideoCapture()
    try:
        while True:
            success, frame = cap.read()
            if success and frame is not None:
                cv2.imshow("MN96100C", cv2.resize(frame, (640, 640)))
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
