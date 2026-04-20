#!/usr/bin/env python3
"""
Hardware / API Test Runner for Drug-Recognition-Subsystem

Usage:
    python test.py --picam --light --drawer --api

Options:
    --picam   Test Raspberry Pi Camera Module (Picamera2)
    --light   Test WS2812 LED Ring Light
    --drawer  Test MN96100C 2.5D Sensor + Depth Analysis
    --api     Test remote FY115 Segment/Encoder API connectivity
"""

import sys
import argparse


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
# Remote API Test
# ============================================================

def test_api(segment_url: str, encoder_url: str) -> bool:
    """Test remote FY115 Segment API and Encoder API connectivity."""
    import cv2
    import requests
    from pathlib import Path

    seg_url = segment_url.rstrip("/")
    enc_url = encoder_url.rstrip("/")
    timeout = 10

    log(f"  ↳ Segment API: {seg_url}")
    log(f"  ↳ Encoder API: {enc_url}")

    # Step 1: healthz
    log("  ↳ GET /healthz (Segment)...")
    r = requests.get(f"{seg_url}/healthz", timeout=timeout)
    if r.status_code != 200 or r.json().get("status") != "ok":
        log(f"  ↳ Segment healthz failed: {r.status_code} {r.text}")
        return False
    log("  ↳ Segment /healthz OK ✓")

    log("  ↳ GET /healthz (Encoder)...")
    r = requests.get(f"{enc_url}/healthz", timeout=timeout)
    if r.status_code != 200 or r.json().get("status") != "ok":
        log(f"  ↳ Encoder healthz failed: {r.status_code} {r.text}")
        return False
    log("  ↳ Encoder /healthz OK ✓")

    # Step 2: 用 sample 圖測試 Segment API
    sample_path = Path("src/sample/sample.jpg")
    if not sample_path.exists():
        log("  ↳ src/sample/sample.jpg not found, skipping predict test")
        return True

    log("  ↳ POST /v1/segment/predict (Segment)...")
    with open(sample_path, "rb") as f:
        r = requests.post(
            f"{seg_url}/v1/segment/predict",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"include_mask_rle": "true"},
            timeout=timeout,
        )
    if r.status_code != 200:
        log(f"  ↳ Segment predict failed: {r.status_code}")
        return False
    seg_data = r.json()
    count = seg_data.get("count", 0)
    log(f"  ↳ Segment predict OK: {count} detections ✓")

    if count == 0:
        log("  ↳ No detections in sample image, skipping Encoder test")
        return True

    # Step 3: 裁切第一個 detection 測試 Encoder API
    log("  ↳ POST /v1/encoder/encode (Encoder)...")
    frame = cv2.imread(str(sample_path))
    x1, y1, x2, y2 = seg_data["detections"][0]["bbox"]
    crop = frame[y1:y2, x1:x2]
    _, buf = cv2.imencode(".jpg", crop)
    r = requests.post(
        f"{enc_url}/v1/encoder/encode",
        files={"file": ("crop.jpg", buf.tobytes(), "image/jpeg")},
        timeout=timeout,
    )
    if r.status_code != 200:
        log(f"  ↳ Encoder encode failed: {r.status_code}")
        return False
    results = r.json().get("results", [])
    if not results:
        log("  ↳ Encoder returned empty results")
        return False
    top = results[0]
    log(f"  ↳ Encoder encode OK: top-1 score={top['score']:.4f}  "
        f"name={top.get('中文品名', '')} ✓")

    return True


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Test hardware and API components of the Drug-Recognition-Subsystem',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test.py --picam --light --drawer --api   # All tests
  python test.py --api                            # API connectivity only (no hardware required)
  python test.py --picam --drawer                 # Hardware tests only
        """
    )
    parser.add_argument('--picam',  action='store_true', help='Test Raspberry Pi Camera Module')
    parser.add_argument('--light',  action='store_true', help='Test WS2812 LED Ring Light')
    parser.add_argument('--drawer', action='store_true', help='Test MN96100C 2.5D Sensor + Depth Analysis')
    parser.add_argument('--api',    action='store_true', help='Test remote FY115 Segment/Encoder API')

    # 預設值從 api.yaml 讀取，讓 test.py 與 run.py 保持一致
    try:
        import yaml
        from pathlib import Path
        _cfg = yaml.safe_load(Path(__file__).parent.joinpath('api.yaml').read_text(encoding='utf-8'))
    except Exception:
        _cfg = {}
    parser.add_argument('--segment-url', default=_cfg.get('segment_url', 'http://192.168.50.1:8001'),
                        help='Segment API 位址（預設讀自 api.yaml）')
    parser.add_argument('--encoder-url', default=_cfg.get('encoder_url', 'http://192.168.50.1:8002'),
                        help='Encoder API 位址（預設讀自 api.yaml）')

    args = parser.parse_args()

    if not any(v for k, v in vars(args).items() if k not in ('segment_url', 'encoder_url')):
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
        results['Remote API'] = run_test('FY115 Segment + Encoder API',
                                         lambda: test_api(args.segment_url, args.encoder_url))

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
