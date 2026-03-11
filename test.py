#!/usr/bin/env python3
"""
Hardware / Module Test Runner for Drug Dispense Verify Subsystem

Usage:
    python test.py --picam --light --drawer --detector --encoder --matcher

Options:
    --picam      Test Raspberry Pi Camera Module (Picamera2)
    --light      Test WS2812 LED Ring Light
    --drawer     Test MN96100C 2.5D Sensor + Depth Analysis
    --detector   Test BaseDetector: area filtering + detect_and_crop (no model)
    --encoder    Test BaseEncoder: forward, L2 normalization, encode_batch (no model)
    --matcher    Test BaseMatcher: empty-gallery guard + forward dispatch (no model)
"""

import sys
import argparse

import numpy as np


# ANSI color codes
class Colors:
    GREEN  = '\033[92m'
    RED    = '\033[91m'
    YELLOW = '\033[93m'
    BLUE   = '\033[94m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'


def log(msg: str):
    print(msg)


def print_test_header(title: str):
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD} {title}{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.RESET}")


def print_result(test_name: str, success: bool):
    status = (f"{Colors.GREEN}{Colors.BOLD}[ OK ]{Colors.RESET}" if success
              else f"{Colors.RED}{Colors.BOLD}[ FAIL ]{Colors.RESET}")
    print(f"\n{status} {test_name}")


def run_test(test_name: str, test_func) -> bool:
    print(f"\n{Colors.YELLOW}► Running: {test_name}{Colors.RESET}")
    try:
        result = test_func()
        print_result(test_name, result)
        return result
    except Exception as e:
        print(f"\n{Colors.RED}  ↳ Unexpected error: {e}{Colors.RESET}")
        print_result(test_name, False)
        return False


# ============================================================
# Hardware Tests
# ============================================================

def test_picam() -> bool:
    """Test Raspberry Pi Camera Module (Picamera2)"""
    try:
        from picamera2 import Picamera2
        log("  ↳ Initializing Picamera2...")
        picam2 = Picamera2()
        picam2.start()
        log("  ↳ Capturing frame...")
        frame = picam2.capture_array()
        picam2.stop()
        picam2.close()
        if frame is not None and frame.size > 0:
            log(f"  ↳ Frame captured (shape={frame.shape}) ✓")
            return True
        log("  ↳ Frame is empty")
        return False
    except Exception as e:
        log(f"  ↳ Error: {e}")
        return False


def test_light() -> bool:
    """Test WS2812 LED Ring Light (24 LEDs on GPIO18)"""
    try:
        import board
        import neopixel
        import time
        
        log("  ↳ Initializing WS2812 LED Ring (GPIO18, 24 LEDs)...")
        pixels = neopixel.NeoPixel(board.D18, 24)
        
        log("  ↳ White → Off")
        pixels.fill((255, 255, 255))
        time.sleep(0.5)
        pixels.fill((0, 0, 0))
        time.sleep(0.2)
        
        log("  ↳ LED control successful ✓")
        return True
    except ImportError as e:
        log(f"  ↳ Module not found: {e}")
        log("  ↳ Install with: pip install adafruit-circuitpython-neopixel adafruit-blinka")
        return False
    except Exception as e:
        log(f"  ↳ Error: {e}")
        return False


def test_drawer() -> bool:
    """Test MN96100C 2.5D Sensor + Depth Analysis"""
    try:
        from eminent.sensors.vision2p5d import VideoCapture
        from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector
        
        log("  ↳ Initializing MN96100C 2.5D Sensor...")
        cap = VideoCapture(vid=0x04F3, pid=0x0C7E)
        
        log("  ↳ Capturing frame...")
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            log("  ↳ Failed to capture frame")
            return False
        
        if frame.shape != (160, 160, 3):
            log(f"  ↳ Unexpected frame shape: {frame.shape} (expected 160x160x3)")
            return False
        
        log(f"  ↳ Frame captured (shape={frame.shape}) ✓")
        
        # Test DepthAnalyzer
        log("  ↳ Testing DepthAnalyzer...")
        analyzer = DepthAnalyzer()
        gray = frame[:, :, 0]  # Use first channel as grayscale
        
        metrics = analyzer.calculate_depth_metrics(gray, use_transform=True)
        log(f"  ↳ Depth metrics: mean={metrics['mean']:.4f}, std={metrics['std']:.4f}")
        
        if not (0.0 <= metrics['mean'] <= 1.0):
            log(f"  ↳ Depth metric out of valid range [0, 1]: {metrics['mean']}")
            return False
        
        log("  ↳ DepthAnalyzer ✓")
        
        # Test DrawerStateDetector
        log("  ↳ Testing DrawerStateDetector...")
        detector = DrawerStateDetector(
            threshold_open=0.08,
            threshold_closed=0.06,
            filter_window=5,
            min_state_duration=3
        )
        
        # Feed multiple frames to test state detection
        for i in range(5):
            state = detector.update(metrics['mean'])
            log(f"  ↳ Frame {i+1}: state={state}")
        
        if state not in ["完全開啟", "閉合中", "完全閉合", "未知"]:
            log(f"  ↳ Invalid state: {state}")
            return False
        
        log("  ↳ DrawerStateDetector ✓")
        log("  ↳ MN96100C 2.5D Sensor + Depth Analysis ✓")
        return True
        
    except ImportError as e:
        log(f"  ↳ Module not found: {e}")
        log("  ↳ Make sure eminent library and utils.depth_analysis are available")
        return False
    except Exception as e:
        log(f"  ↳ Error: {e}")
        import traceback
        log(f"  ↳ {traceback.format_exc()}")
        return False


# ============================================================
# Module Tests (no real model required)
# ============================================================

def test_detector() -> bool:
    """Test BaseDetector: area filtering + detect_and_crop (inline subclass, no model)"""
    from utils.detector import BaseDetector
    from utils.types import Detection

    class _DummyDetector(BaseDetector):
        min_area = 500

        def __init__(self):
            pass  # no model

        def forward(self, image: np.ndarray) -> list[Detection]:
            h, w = image.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            return [
                Detection(bbox=(0,  0,  10, 10), mask=mask, confidence=0.9),  # area=100  → filtered
                Detection(bbox=(0,  0,  30, 20), mask=mask, confidence=0.8),  # area=600  → kept
                Detection(bbox=(50, 50, 80, 90), mask=mask, confidence=0.7),  # area=1200 → kept
            ]

    log("  ↳ Creating _DummyDetector (inline, no model)...")
    det = _DummyDetector()
    dummy = np.zeros((200, 200, 3), dtype=np.uint8)

    results = det(dummy)  # __call__ applies min_area filter
    log(f"  ↳ forward() returned 3 detections; after min_area={det.min_area} filter: {len(results)}")
    if len(results) != 2:
        log(f"  ↳ Expected 2, got {len(results)}")
        return False

    crops = det.detect_and_crop(dummy)
    log(f"  ↳ detect_and_crop() returned {len(crops)} crops")
    if len(crops) != 2:
        log(f"  ↳ Expected 2 crops, got {len(crops)}")
        return False
    if not all(isinstance(c, np.ndarray) for _, c in crops):
        log("  ↳ Crops are not ndarray")
        return False

    log("  ↳ BaseDetector ✓")
    return True


def test_encoder() -> bool:
    """Test BaseEncoder: forward, L2 normalization, encode_batch (inline subclass, no model)"""
    from utils.encoder import BaseEncoder

    EXPECTED_DIM = 4

    class _DummyEncoder(BaseEncoder):
        FEATURE_DIM = EXPECTED_DIM

        def __init__(self):
            pass  # no model

        def forward(self, image: np.ndarray) -> np.ndarray:
            # Sum each quadrant → 4-dim vector (simple arithmetic, no ML)
            h, w = image.shape[:2]
            hh, hw = h // 2, w // 2
            return np.array([
                float(image[:hh, :hw].sum()),
                float(image[:hh, hw:].sum()),
                float(image[hh:, :hw].sum()),
                float(image[hh:, hw:].sum()),
            ])

    log("  ↳ Creating _DummyEncoder (inline, no model)...")
    enc = _DummyEncoder()
    dummy = np.random.randint(1, 255, (8, 8, 3), dtype=np.uint8)

    feat = enc(dummy)  # __call__: forward → float32 → L2 normalize
    log(f"  ↳ Feature shape: {feat.shape}, dtype: {feat.dtype}")
    if feat.shape != (EXPECTED_DIM,):
        log(f"  ↳ Expected shape ({EXPECTED_DIM},), got {feat.shape}")
        return False
    if feat.dtype != np.float32:
        log(f"  ↳ Expected float32, got {feat.dtype}")
        return False

    norm = np.linalg.norm(feat)
    log(f"  ↳ L2 norm: {norm:.6f} (should be 1.0)")
    if not np.isclose(norm, 1.0, atol=1e-5):
        log(f"  ↳ Norm is not 1.0")
        return False

    images = [np.random.randint(1, 255, (8, 8, 3), dtype=np.uint8) for _ in range(3)]
    batch = enc.encode_batch(images)
    log(f"  ↳ encode_batch shape: {batch.shape}")
    if batch.shape != (3, EXPECTED_DIM):
        log(f"  ↳ Expected (3, {EXPECTED_DIM}), got {batch.shape}")
        return False

    log("  ↳ BaseEncoder ✓")
    return True


def test_matcher() -> bool:
    """Test BaseMatcher: empty-gallery guard + forward dispatch (inline subclass, no model)"""
    from utils.matcher import BaseMatcher
    from utils.gallery import Gallery
    from utils.types import MatchResult

    call_log: list[str] = []

    class _DummyMatcher(BaseMatcher):
        def forward(self, feature: np.ndarray) -> MatchResult | None:
            call_log.append("forward")
            scores = np.dot(self.gallery.features, feature)
            best = int(np.argmax(scores))
            meta = self.gallery.get_metadata(best)
            return MatchResult(
                license_number=meta.get("license_number", ""),
                name=meta.get("name", ""),
                side=meta.get("side", 0),
                score=float(scores[best]),
            )

    # Test 1: empty gallery → __call__ must return None without entering forward
    log("  ↳ Test 1: empty gallery guard...")
    empty_gallery = Gallery("nonexistent_path")
    matcher = _DummyMatcher(empty_gallery)
    dummy_feat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    result = matcher(dummy_feat)
    if result is not None:
        log(f"  ↳ Expected None, got {result}")
        return False
    if call_log:
        log("  ↳ forward() must NOT be called on empty gallery")
        return False
    log("  ↳ Empty-gallery guard OK ✓")

    # Test 2: in-memory gallery → forward dispatched, correct best match returned
    log("  ↳ Test 2: forward dispatch with in-memory gallery...")
    gallery = Gallery.__new__(Gallery)
    gallery.path = None
    gallery._features = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ], dtype=np.float32)
    gallery._index = {"entries": [
        {"license_number": "TEST-001", "name": "Drug A", "side": 0},
        {"license_number": "TEST-002", "name": "Drug B", "side": 1},
    ]}

    matcher2 = _DummyMatcher(gallery)
    query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    result2 = matcher2(query)

    log(f"  ↳ Match result: {result2}")
    if result2 is None:
        log("  ↳ Expected a MatchResult, got None")
        return False
    if result2.license_number != "TEST-001":
        log(f"  ↳ Expected TEST-001, got {result2.license_number}")
        return False
    if "forward" not in call_log:
        log("  ↳ forward() was not called")
        return False
    log("  ↳ Forward dispatch OK ✓")

    log("  ↳ BaseMatcher ✓")
    return True


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Test hardware and module components of the Drug Dispense Verify Subsystem',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test.py --picam --light --drawer --detector --encoder --matcher  # All tests
  python test.py --detector --encoder --matcher                           # Module tests only (no hardware)
  python test.py --picam --drawer                                         # Hardware tests only
  python test.py --drawer                                                 # 2.5D sensor only
        """
    )
    parser.add_argument('--picam',    action='store_true', help='Test Raspberry Pi Camera Module')
    parser.add_argument('--light',    action='store_true', help='Test WS2812 LED Ring Light')
    parser.add_argument('--drawer',   action='store_true', help='Test MN96100C 2.5D Sensor + Depth Analysis')
    parser.add_argument('--detector', action='store_true', help='Test BaseDetector (area filtering, no model)')
    parser.add_argument('--encoder',  action='store_true', help='Test BaseEncoder (L2 norm, no model)')
    parser.add_argument('--matcher',  action='store_true', help='Test BaseMatcher (guard + dispatch, no model)')

    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        print(f"\n{Colors.RED}Error: Please specify at least one test option.{Colors.RESET}\n")
        sys.exit(1)

    print_test_header("Component Testing")

    results = {}

    if args.picam:
        results['Pi Camera'] = run_test('Raspberry Pi Camera', test_picam)
    if args.light:
        results['LED Ring'] = run_test('WS2812 LED Ring Light', test_light)
    if args.drawer:
        results['2.5D Sensor'] = run_test('MN96100C 2.5D Sensor + Depth Analysis', test_drawer)
    if args.detector:
        results['Detector'] = run_test('BaseDetector', test_detector)
    if args.encoder:
        results['Encoder'] = run_test('BaseEncoder', test_encoder)
    if args.matcher:
        results['Matcher'] = run_test('BaseMatcher', test_matcher)

    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD} Test Summary{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.RESET}\n")

    passed = sum(1 for r in results.values() if r)
    total = len(results)
    for name, result in results.items():
        status = f"{Colors.GREEN}PASS{Colors.RESET}" if result else f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"  {status}  {name}")

    print(f"\n{Colors.BOLD}Total: {passed}/{total} tests passed{Colors.RESET}\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
