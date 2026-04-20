#!/usr/bin/env python3
"""
Hardware / API Test Runner for FY114 Drug Recognition Subsystem

Usage:
    python test.py --picam --light --drawer --api

Options:
    --picam   Test Raspberry Pi Camera Module (Picamera2)
    --light   Test WS2812 LED Ring Light
    --drawer  Test MN96100C 2.5D Sensor + Depth Analysis
    --api     Test AI pipeline (API config read from api.yaml)
"""

import sys
import argparse
from pathlib import Path

try:
    import yaml
    _cfg_path = Path(__file__).parent / "api.yaml"
    _cfg = yaml.safe_load(_cfg_path.read_text(encoding="utf-8")) if _cfg_path.exists() else {}
except ImportError:
    _cfg = {}

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
        
        log("  ↳ White (stays on)")
        pixels.fill((255, 255, 255))
        time.sleep(0.5)

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
        
        metrics = analyzer.calculate_depth_metrics(gray)
        log(f"  ↳ Depth metrics: mean={metrics['mean']:.1f}, std={metrics['std']:.2f}")

        if not (0 <= metrics['mean'] <= 255):
            log(f"  ↳ Intensity out of valid range [0, 255]: {metrics['mean']}")
            return False
        
        log("  ↳ DepthAnalyzer ✓")
        
        # Test DrawerStateDetector
        log("  ↳ Testing DrawerStateDetector...")
        detector = DrawerStateDetector(
            threshold_open=80,
            threshold_closed=150,
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
# API Test
# ============================================================

def test_api(segment_url: str, encoder_url: str) -> bool:
    """Test the full AI pipeline directly against Segment and Encoder APIs."""
    import cv2
    import numpy as np
    import requests
    from utils.analyser import analyse, check_reachable

    log(f"  ↳ Checking Segment API at {segment_url}/healthz...")
    log(f"  ↳ Checking Encoder API at {encoder_url}/healthz...")
    try:
        check_reachable(segment_url, encoder_url, timeout=5)
        log(f"  ↳ Segment API is up ✓")
        log(f"  ↳ Encoder API is up ✓")
    except requests.exceptions.RequestException as e:
        log(f"  ↳ API not reachable: {e}")
        return False

    log("  ↳ Sending test image to Segment → Encoder pipeline...")
    try:
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(dummy, (100, 100), (300, 380), (200, 200, 200), -1)
        data = analyse(dummy, segment_url, encoder_url, timeout=60)
    except requests.exceptions.RequestException as e:
        log(f"  ↳ Pipeline request failed: {e}")
        return False

    if data.get("status") != "ok":
        log(f"  ↳ Unexpected response: {data}")
        return False

    pills = data.get("pills", [])
    log(f"  ↳ Pipeline response: status=ok  pills={len(pills)} ✓")
    for i, p in enumerate(pills):
        log(f"  ↳   [{i+1}] {p.get('name', '?')}  score={p.get('score', 0):.4f}  lic={p.get('license_number', '?')}")

    log("  ↳ API pipeline test passed ✓")
    return True


# ============================================================
# Main
# ============================================================

def main():
    _segment_url = _cfg.get('segment_url', 'http://192.168.50.1:8001')
    _encoder_url = _cfg.get('encoder_url', 'http://192.168.50.1:8002')

    parser = argparse.ArgumentParser(
        description='Test hardware and AI API pipeline of the FY114 Drug Recognition Subsystem',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test.py --picam --light --drawer --api   # All tests
  python test.py --picam --drawer                 # Hardware only
  python test.py --api                            # API pipeline only
        """
    )
    parser.add_argument('--picam',   action='store_true', help='Test Raspberry Pi Camera Module')
    parser.add_argument('--light',   action='store_true', help='Test WS2812 LED Ring Light')
    parser.add_argument('--drawer',  action='store_true', help='Test MN96100C 2.5D Sensor + Depth Analysis')
    parser.add_argument('--api',     action='store_true', help='Test AI pipeline (config from api.yaml)')

    args = parser.parse_args()

    if not any([args.picam, args.light, args.drawer, args.api]):
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
    if args.api:
        results['AI API Pipeline'] = run_test(
            'AI API Pipeline (Segment + Encoder)',
            lambda: test_api(_segment_url, _encoder_url),
        )

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
