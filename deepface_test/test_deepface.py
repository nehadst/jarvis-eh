import os
import cv2
import time
from pathlib import Path
from deepface import DeepFace

# ----------------------------
# Config
# ----------------------------
DB_PATH = "face_db"
FRAMES_PATH = "frames"
MODEL_NAME = "ArcFace"       # strong default to try first
DETECTOR_BACKEND = "retinaface"  # more robust face detection
DISTANCE_METRIC = "cosine"
THRESHOLD = None             # use DeepFace default threshold for the model

Path(FRAMES_PATH).mkdir(parents=True, exist_ok=True)

def detect_and_draw_faces(frame) -> tuple:
    """
    Detect faces in frame and draw rectangles around them.
    Returns (display_frame, face_count).
    """
    try:
        # Use retinaface for face detection
        faces = DeepFace.extract_faces(
            img_path=frame,
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=False,
            silent=True
        )
        
        display = frame.copy()
        for face_info in faces:
            # Extract bounding box
            x, y, w, h = face_info['facial_area'].values()
            # Draw rectangle
            cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
        
        return display, len(faces)
    except Exception as e:
        return frame.copy(), 0

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
        status_text = f"Faces detected: {face_count} | SPACE = capture/test | Q = quit"
        color = (0, 255, 0) if face_count > 0 else (0, 0, 255)
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
            timestamp = int(time.time())
            frame_path = os.path.join(FRAMES_PATH, f"capture_{timestamp}.jpg")
            cv2.imwrite(frame_path, frame)
            print(f"\nSaved frame: {frame_path}")
            run_match(frame_path)

        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()