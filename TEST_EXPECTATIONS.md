# JARVIS Testing Guide

## Setup

1. Copy `.env.example` to `.env` and fill in API keys:
   - `OPENAI_API_KEY` — required for LLM whispers + voice commands
   - `GEMINI_API_KEY` — required for activity/scene inference
   - `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` — required for TTS
2. Set `CAPTURE_MODE` in `.env`:
   - `webcam` — laptop camera (easiest for testing)
   - `video` — pre-recorded clip (set `VIDEO_PATH` too)
   - `glasses` — Meta glasses via iOS app
   - `screen` — screen region capture
3. Run:
   ```bash
   cd backend
   python main.py
   ```
   Server starts at `http://localhost:8000`

---

## Features & How to Test

### 1. Face Recognition

**What it does:** Recognizes known faces and speaks a personalized greeting.

**Setup:** Place reference photos in `backend/data/face_db/{person_id}/` (e.g. `face_db/ronaldo/photo1.jpg`). Matching profile should exist in `backend/data/family_profiles/{person_id}.json`.

**Test steps:**
1. Start capture (`POST /api/capture/start` or via frontend)
2. Stand in front of the camera

**Expected:**
- TTS speaks a warm, personalized greeting within a few seconds
- If you've interacted before, the greeting references your last conversation
- Walking away and coming back within 15 seconds will NOT re-trigger (cooldown)
- After 15+ seconds, you'll get greeted again

---

### 2. Conversation Session Tracking

**What it does:** Records the full transcript of a conversation while a person is present. When they leave, generates an LLM summary and stores it for future context.

**Test steps:**
1. Get recognized by the camera (triggers face detection)
2. Talk for at least 30 seconds (requires microphone + `OPENAI_API_KEY`)
3. Walk out of frame and stay away for 15+ seconds

**Expected:**
- While present: transcript accumulates silently in the background
- After 15s out of frame: session ends, LLM generates a summary
- A `face_departed` event fires on the WebSocket with duration and summary
- Next time you're recognized, the greeting references what you talked about

**Notes:**
- Sessions shorter than 30 seconds are discarded (no summary generated)
- Sessions auto-end at 30 minutes as a safety cap

---

### 3. Confusion Detection

**What it does:** Detects signs of confusion using motion, scene, activity, and audio signals. Responds with grounding or activity reminders.

**Test steps (pick one):**

| Trigger | How | Wait Time |
|---|---|---|
| Extended inactivity | Stand still in one spot | ~45 seconds |
| Repeated question | Say the same question twice within 2 minutes | Immediate |
| Pacing | Walk back and forth in frame | ~60 seconds in same room |
| Sundowning + stillness | Test between 4pm–7pm, stay still | ~30 seconds |

**Expected:**
- TTS speaks a contextual reminder:
  - If a **caregiver task** is set → task reminder ("Remember, you were going to take your medication")
  - If **recent activity** was detected → activity reminder ("You were just reading in the living room")
  - Otherwise → **full grounding** (time, place, household context)
- 30-second cooldown before confusion can trigger again
- Medium-confidence signals wait 15 seconds for confirmation before acting

---

### 4. Scene Classification & Wandering Alert

**What it does:** Classifies the current scene/location. If 3 consecutive readings are "unsafe" (not a recognized home room), triggers a wandering alert.

**Safe zones:** kitchen, living room, bedroom, hallway, bathroom, dining room, office, study, porch, garage

**Test steps:**
1. Point the camera at an outdoor or unfamiliar scene for ~30 seconds

**Expected:**
- TTS speaks a gentle redirect (e.g. "It looks like you might have wandered outside. Let's head back inside.")
- 60-second cooldown before it can trigger again

---

### 5. Activity Inference

**What it does:** Uses Gemini Vision to infer what the person is doing every ~10 seconds.

**Test steps:**
1. Perform a visible activity in front of the camera — reading, cooking, eating, writing, etc.

**Expected:**
- Activity is logged silently (no TTS output on its own)
- Activity feeds into confusion detection and voice command responses
- Say "What was I doing?" to hear the inferred activity spoken back

---

### 6. Motion Detection

**What it does:** Detects stillness and pacing via frame-by-frame analysis.

**Test steps:**
- **Stillness:** Stand completely still for ~10 seconds
- **Pacing:** Walk back and forth repeatedly

**Expected:**
- No direct TTS output — these signals feed into the Confusion Detector
- Combined with scene/activity data, they contribute to confusion alerts

---

### 7. Voice Commands (requires microphone)

**What it does:** Listens for speech, routes intent via GPT-4o-mini, and responds.

**Test steps & expected responses:**

| Say this | Expected response |
|---|---|
| "Who is that?" / "Do I know them?" | Repeats the last face greeting |
| "Where am I?" / "I'm lost" | Grounding: current scene, time of day, household context |
| "What was I doing?" / "What should I do?" | Task reminder > activity reminder > grounding (priority order) |
| "I'm feeling anxious" / general question | Empathetic free-form LLM response |
| Normal conversation / background noise | No action (correctly ignored) |

**Notes:**
- 8-second cooldown between voice commands
- Microphone mutes for 6 seconds after TTS plays (prevents echo feedback)
- Requires `OPENAI_API_KEY` for Whisper transcription

---

### 8. Manual Grounding (Caregiver API)

**What it does:** Immediately delivers a grounding message — no cooldown, always works.

**Test:**
```bash
curl -X POST http://localhost:8000/api/grounding/trigger
```

**Expected:**
- TTS immediately speaks: time of day, current location, household context, and any recent activity
- Event fires on WebSocket

---

### 9. Task Management (Caregiver API)

**What it does:** Caregivers can set tasks for the patient. Tasks take highest priority in confusion responses.

**Test:**
```bash
# Set a task
curl -X POST http://localhost:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task": "Take your medication", "set_by": "caregiver"}'

# Check current task
curl http://localhost:8000/api/tasks

# Clear task
curl -X DELETE http://localhost:8000/api/tasks
```

**Expected:**
- When confusion is detected with an active task, TTS says something like "Remember, you were going to take your medication"
- Task appears in the frontend dashboard

---

### 10. Live Video Stream

**Test:** Open in a browser:
```
http://localhost:8000/api/stream
```

**Expected:**
- MJPEG feed showing the camera's view in real time

---

### 11. WebSocket Events (Frontend Dashboard)

**Test:** Connect to `ws://localhost:8000/ws` (or open the frontend)

**Expected events:**

| Event | When |
|---|---|
| `face_detected` | Person recognized — includes name, confidence, bounding box |
| `face_departed` | Person left — includes duration, conversation summary |
| `grounding` | Grounding triggered (manual or confusion) |
| `wandering` | Unsafe scene detected |
| `voice_command` | Voice command processed |

---

## Timing Reference

| Parameter | Value |
|---|---|
| Min gap between TTS outputs | 4 seconds |
| Face re-greeting cooldown | 15 seconds per person |
| Departure grace period | 15 seconds |
| Confusion detection cooldown | 30 seconds |
| Wandering alert cooldown | 60 seconds |
| Activity inference interval | 10 seconds |
| Scene classification | Every 10th AI frame |
| Min conversation session length | 30 seconds |
| Voice command cooldown | 8 seconds |
| TTS echo suppression (mic mute) | 6 seconds |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No TTS audio | Check `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in `.env` |
| Face not recognized | Add more reference photos to `face_db/{person_id}/`, try lowering `FACE_SIMILARITY_THRESHOLD` |
| Voice commands not working | Check `OPENAI_API_KEY`, make sure microphone is accessible |
| Scene always "unsafe" | Check Gemini API key, ensure camera shows a recognizable indoor space |
| No activity inference | Check `GEMINI_API_KEY`, ensure a person is visible in frame |
| Greeting repeats too fast | Normal cooldown is 15s — verify you're not restarting capture between tests |
| Confusion never triggers | Need to stay still 45s+ OR repeat a question — check that motion sensor is getting frames |
