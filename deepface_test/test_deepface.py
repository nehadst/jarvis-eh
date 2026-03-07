import os
import cv2
import time
import threading
import queue
from pathlib import Path
from deepface import DeepFace

# Haar Cascade for fast live face detection (doesn't block the UI)
_FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# Single worker thread + queue so DeepFace/TensorFlow calls never run concurrently
_match_queue: queue.Queue = queue.Queue()

def _match_worker() -> None:
    """Persistent background thread — processes one match at a time."""
    while True:
        frame_path = _match_queue.get()
        if frame_path is None:
            break
        if frame_path == "__prewarm__":
            _prewarm_model()
        else:
            run_match(frame_path)
        _match_queue.task_done()

_worker_thread = threading.Thread(target=_match_worker, daemon=True)
_worker_thread.start()
_match_queue.put("__prewarm__")  # warm up TF + rebuild pkl cache immediately on launch

# ----------------------------
# Config
# ----------------------------
DB_PATH = "face_db"
FRAMES_PATH = "frames"
MODEL_NAME = "ArcFace"
DETECTOR_BACKEND = "opencv"   # fast (~50ms) — retinaface is accurate but ~15s on CPU
DISTANCE_METRIC = "cosine"
THRESHOLD = None

Path(FRAMES_PATH).mkdir(parents=True, exist_ok=True)

def _prewarm_model() -> None:
    """
    Load the ArcFace model + build/verify the face_db .pkl cache at startup
    so the first Space press is fast. Runs in the worker thread.
    """
    import tempfile, numpy as np
    print("[prewarm] Loading ArcFace model and verifying face_db cache...")
    # Create a tiny blank image — just enough to trigger model + cache load
    blank = np.zeros((160, 160, 3), dtype=np.uint8)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        cv2.imwrite(tmp.name, blank)
        tmp_path = tmp.name
    try:
        DeepFace.find(
            img_path=tmp_path,
            db_path=DB_PATH,
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            distance_metric=DISTANCE_METRIC,
            enforce_detection=False,
            silent=True,
        )
    except Exception:
        pass  # expected — blank image won't match anything
    finally:
        os.unlink(tmp_path)
    print("[prewarm] Ready. Press SPACE to capture.")

def detect_and_draw_faces(frame) -> tuple:
    """
    Detect faces in frame using Haar Cascade and draw rectangles.
    Fast enough to run on every frame without blocking the UI.
    Returns (display_frame, face_count).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )
    display = frame.copy()
    for (x, y, w, h) in faces:
        cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
    return display, len(faces)

def run_match(frame_path: str) -> None:
    """
    Run DeepFace.find on a saved webcam frame and print the best match.
    """
    try:
        results = DeepFace.find(
            img_path=frame_path,
            db_path=DB_PATH,
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            distance_metric=DISTANCE_METRIC,
            enforce_detection=True,
            silent=True,
        )

        # DeepFace.find returns a list of dataframes
        if not results or len(results) == 0:
            print("No results returned.")
            return

        df = results[0]

        if df.empty:
            print("No match found in database.")
            return

        # Sort by smallest distance just to be safe
        df = df.sort_values(by="distance", ascending=True)
        best = df.iloc[0]

        print("\n=== BEST MATCH ===")
        print(f"identity: {best['identity']}")
        print(f"distance: {best['distance']:.4f}")

        # DeepFace may include threshold in the dataframe depending on version/settings
        if "threshold" in df.columns:
            print(f"threshold: {best['threshold']:.4f}")
            is_match = best["distance"] <= best["threshold"]
            print(f"match: {is_match}")
        else:
            print("threshold: not returned in dataframe")
            print("match: likely yes if this is clearly the smallest known distance")

    except Exception as e:
        print(f"DeepFace error: {e}")

def main() -> None:
    if not os.path.isdir(DB_PATH):
        raise FileNotFoundError(f"Database folder not found: {DB_PATH}")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam.")

    print("Webcam started.")
    print("Press SPACE to capture and test recognition.")
    print("Press Q to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to read frame from webcam.")
            break

        # Detect and draw faces on the frame
        display, face_count = detect_and_draw_faces(frame)
        
        # Add status text
        busy = _match_queue.qsize() > 0
        status_text = f"Faces detected: {face_count} | {'MATCHING...' if busy else 'SPACE = capture'} | Q = quit"
        color = (0, 165, 255) if busy else ((0, 255, 0) if face_count > 0 else (0, 0, 255))
        cv2.putText(
            display,
            status_text,
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )

        cv2.imshow("DeepFace Webcam Test", display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):
            if _match_queue.qsize() > 0:
                print("Still processing previous capture — please wait...")
            else:
                timestamp = int(time.time())
                frame_path = os.path.join(FRAMES_PATH, f"capture_{timestamp}.jpg")
                cv2.imwrite(frame_path, frame)
                print(f"\nSaved frame: {frame_path}")
                print("Running match in background — window stays responsive...")
                _match_queue.put(frame_path)

        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()