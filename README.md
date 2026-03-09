#  WINNING Submission for Hack Canada 2026 🎉 | Jarvis Eh? The Meta Glasses AI Agent for People with Dementia
> *Built on Meta glasses. Sees what you see. Helps you navigate life.*

A real-time AI companion that runs on Meta glasses and a phone/laptop backend to assist people with dementia — providing face recognition, situation grounding, activity continuity, wandering detection, and conversation support.

---

## Team & Feature Ownership

| Feature | Owner | Module |
|---|---|---|
| 1. Face Recognition + Memory Recall | **Maaz** | `backend/features/face_recognition/` |
| 3. Situation Grounding | **Nehad** | `backend/features/situation_grounding/` |
| 4. Activity Continuity | **Hashim** | `backend/features/activity_continuity/` |
| 9. Wandering Guardian | TBD | `backend/features/wandering_guardian/` |
| 12. Conversation Copilot | TBD | `backend/features/conversation_copilot/` |
| Caregiver Dashboard | TBD | `frontend/` |

---

## Architecture

```
Meta Glasses (POV camera)
        │
        ▼
WhatsApp Video Call → Laptop Screen
        │
        ▼  (mss screen capture, 1-2 FPS)
┌───────────────────────────────────┐
│         Python Backend            │
│                                   │
│  Frame Capture (mss + OpenCV)     │
│          │                        │
│  Feature Pipeline                 │
│  ├── Face Recognition (DeepFace)  │
│  ├── Situation Grounding          │
│  ├── Activity Continuity          │
│  ├── Wandering Guardian           │
│  └── Conversation Copilot         │
│          │                        │
│  Services                         │
│  ├── Gemini API (reasoning)       │
│  ├── ElevenLabs (voice output)    │
│  ├── Cloudinary (media)           │
│  └── Backboard.io (memory)        │
└───────────┬───────────────────────┘
            │
     WebSocket (real-time events)
            │
            ▼
     React Dashboard (caregiver)
```

---

## Quick Start

### 1. Clone & Configure

```bash
git clone <repo>
cd jarvis-eh

# Copy env template and fill in your API keys
cp .env.example .env
```

### 2. Backend Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
```

### 3. Add Family Photos

Create a folder per person under `backend/data/face_db/`:
```
backend/data/face_db/
  sarah_johnson/
    img1.jpg
    img2.jpg
  david_smith/
    img1.jpg
```

Create a matching JSON profile under `backend/data/family_profiles/`:
```
backend/data/family_profiles/
  sarah_johnson.json    ← see example_person.json for format
```

### 4. Run Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The API will be at `http://localhost:8000`  
The WebSocket dashboard feed: `ws://localhost:8000/ws`

### 5. Run Frontend (Caregiver Dashboard)

```bash
cd frontend
npm install
npm run dev
```

Dashboard at `http://localhost:5173`

---

## API Keys Needed

| Service | What it's used for | Get it at |
|---|---|---|
| Google Gemini | Scene understanding, whisper generation | https://aistudio.google.com |
| ElevenLabs | Natural voice output through glasses | https://elevenlabs.io |
| Cloudinary | Family photo/video storage & montages | https://cloudinary.com |
| Backboard.io | Persistent memory, agent orchestration | https://backboard.io |

---

## Features Implemented

### Feature 1 — Face Recognition + Memory Recall (Maaz)
- Detects faces in the live frame using DeepFace + RetinaFace
- Matches against `data/face_db/` (family album)
- Fetches person profile from `data/family_profiles/`
- Sends context to Gemini → generates warm whisper
- Plays audio via ElevenLabs: *"That's Sarah, your granddaughter. She came by last Tuesday."*

### Feature 3 — Situation Grounding (Nehad)
- Gemini Vision classifies the scene (kitchen, living room, outdoors…)
- Detects disorientation via motion heuristics (head turning, pacing)
- Pulls current time, active caregiver-set task, and household context
- Generates: *"You're at home in your living room. It's Thursday afternoon."*

### Feature 4 — Activity Continuity (Hashim)
- Maintains a 60-second rolling buffer of inferred activities
- YOLOv8 / Gemini Vision detects objects (kettle, book, mug…)
- On confusion trigger, retrieves the last known activity
- Generates: *"You were making tea. The kettle is on the counter to your left."*

### Feature 9 — Wandering Guardian
- POC: family labels safe rooms via dashboard
- Detects if scene transitions to unknown outdoor area
- Plays familiar redirect voice (ElevenLabs)
- Alerts caregiver dashboard in real-time

### Feature 12 — Conversation Copilot
- Transcribes audio from the live stream (Whisper STT)
- Detects topic loops, repeated questions, subject drift
- Retrieves related family memory from Backboard
- Whispers context privately: *"She's talking about the cottage trip last summer."*

---

## Screen Capture Setup

The backend captures the WhatsApp call window using `mss`. You need to configure the screen region in `.env`:

```env
CAPTURE_LEFT=0
CAPTURE_TOP=0
CAPTURE_WIDTH=1280
CAPTURE_HEIGHT=720
```

Use the calibration script to find the right values:
```bash
cd backend
python capture/calibrate.py
```

---

## Sponsor Integrations

| Sponsor | How we use it |
|---|---|
| **Google Gemini** | Reasoning engine for all 5 features — face-context whisper, grounding, activity inference, conversation analysis |
| **ElevenLabs** | Every voice output — whispers, grounding messages, montage narration, redirect voice |
| **Cloudinary** | Family album storage + transforms + AI memory montage video generation |
| **Backboard.io** | Persistent cross-session memory — family profiles, last interactions, current tasks, conversation history |
| **Vultr** | Hosts the Python CV pipeline, FastAPI backend, and montage render jobs |

---

## DeepFace POC

There's a standalone webcam test in `deepface_test/` that Maaz used to validate the face recognition approach:

```bash
cd deepface_test
pip install -r requirements.txt
python test_deepface.py
```

This tests the ArcFace model + RetinaFace detector against the `face_db/` folder.
