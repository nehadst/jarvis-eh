"""
Calibration helper — shows the captured screen region in a window so you can
adjust CAPTURE_LEFT / TOP / WIDTH / HEIGHT in .env until it perfectly
frames the WhatsApp call.

Run from backend/:
    python capture/calibrate.py
"""

import cv2
from capture.frame_capture import FrameCapture


def main() -> None:
    cap = FrameCapture()
    print("Showing capture region. Press Q to quit.")
    print(f"Region: {cap.region}")

    for frame in cap.frames():
        # Overlay the region info
        label = f"Region: {cap.region['left']},{cap.region['top']}  {cap.region['width']}x{cap.region['height']}"
        cv2.putText(frame, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("Calibrate — press Q to quit", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
