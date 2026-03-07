Shared base pipeline for all 6 features
1. Start the live POV feed


Wearer uses the Meta glasses and starts a WhatsApp video call to the team laptop.


Tooling: Meta glasses + WhatsApp Desktop/Web


Why: Meta supports sharing the wearer’s view on calls.


2. Capture the video frames on desktop


Full-screen the call window, lock its position, and have Python capture that region repeatedly.


Tooling: Python + mss for screen grab, OpenCV for frame processing


Backup option: OBS Studio if you want a more stable capture source before Python reads frames.


3. Preprocess frames


Resize, denoise, crop to region of interest, and sample only 1–2 FPS for AI tasks.


Tooling: OpenCV, optional NumPy


4. Send event data to the AI layer


For every “interesting” frame or clip, package detections and context into a structured event.


Tooling: Python service layer, optional FastAPI


5. Memory/orchestration layer


Store persistent user/family context and route the event to the right agent.


Tooling: Backboard.io for persistent memory / orchestration if you want sponsor alignment, since Backboard positions itself as a memory layer with stateful context, routing, retrieval, and tools.


6. Reasoning layer


Turn detections + memory into a human-friendly response.


Tooling: Gemini API


7. Voice output


Convert the final response into calm, natural speech.


Tooling: ElevenLabs TTS, which supports lifelike TTS and real-time audio streaming.


8. Media/dashboard output


Show montages, timelines, and caregiver alerts in a web app.


Tooling: React app, ideally with Cloudinary React Starter Kit for the sponsor challenge since the challenge explicitly asks for that framework and Cloudinary’s docs say the starter kit provides an AI-ready React app with upload and delivery features.


9. Hosting


Run the API / CV pipeline / web app on cloud compute.


Tooling: Vultr for backend hosting to match that sponsor track



1) FACE RECOGNITION + MEMORY RECALL
Step 1: Capture a frame when a face appears


Detect whether a face is present in the captured WhatsApp frame.


Tooling: OpenCV, optionally face_recognition or DeepFace


Step 2: Extract the face embedding


Convert the visible face into an embedding vector.


Tooling: face_recognition, DeepFace, or InsightFace


Step 3: Match against the family album


Compare the embedding against preloaded family embeddings from setup.


Tooling: local vector store or lightweight DB; family images stored in Cloudinary for sponsor alignment and easy retrieval/transforms


Step 4: Pull memory context


Once the person is identified, fetch:


name


relationship


age


last interaction


one personal detail


Tooling: Backboard.io memory store or a JSON/Firestore/Postgres fallback


Sponsor angle: this is a very good Backboard use case because the system needs persistent person-specific memory across sessions.


Step 5: Generate the whisper


Send structured context to Gemini:


Recognized person: Sarah


Relationship: granddaughter


Last interaction: watched a movie last Tuesday


Tone: warm, short, calming


Tooling: Gemini API


Step 6: Speak it out loud


Convert Gemini’s response into natural speech.


Tooling: ElevenLabs


Output example: “That’s Sarah, your granddaughter. She came by last Tuesday and you watched a movie together.”


Best sponsor fit


Gemini for reasoning


ElevenLabs for whisper audio


Backboard for family memory


Cloudinary for album storage


Vultr for hosting the recognition service



2) AI MEMORY MONTAGE (VIDEO GENERATION)
Step 1: Trigger montage generation


Trigger when a known face is recognized or when a caregiver presses “Show memory.”


Tooling: React caregiver dashboard


Step 2: Retrieve related photos/videos


Pull all Sarah-tagged or event-tagged media from the family archive.


Tooling: Cloudinary asset storage / metadata tagging


This is one of your strongest Cloudinary sponsor hooks because their challenge explicitly emphasizes innovative media experiences, transformations, and video usage, plus the React AI Starter Kit.


Step 3: Transform the media


Apply:


auto-crop on faces


resizing


ordering by date/event


transitions


optional Ken Burns style motion


Tooling: Cloudinary transformations + delivery


Step 4: Generate the narrative


Ask Gemini to write a short emotional narration:


“This is Sarah at Christmas...”


Tooling: Gemini API


Step 5: Generate the voiceover


Turn narration into natural audio.


Tooling: ElevenLabs


Step 6: Assemble the montage


Stitch images/video clips and audio into a short recap.


Tooling: Cloudinary video pipeline if enough, otherwise moviepy or ffmpeg on the backend


Step 7: Display it


Show on caregiver laptop or nearby monitor.


Tooling: React + Cloudinary React Starter Kit


Best sponsor fit


Cloudinary is the headline integration here


Gemini for script


ElevenLabs for narration


Vultr for rendering backend



3) SITUATION GROUNDING
Step 1: Continuously sample the POV feed


Every 1–2 seconds, capture a frame and infer the environment.


Tooling: mss + OpenCV


Step 2: Detect disorientation signals


Heuristics for confusion:


repeated head turning


pacing in place


stopping for too long


repeated “where am I / what am I doing” speech


Tooling:


OpenCV / MediaPipe for motion/head movement


Whisper / speech-to-text if you want spoken confusion cues


Step 3: Infer scene and room


Use Gemini or a vision model to classify:


kitchen


living room


hallway


outdoors


Tooling: Gemini API or a CV classifier


Step 4: Pull recent context


Fetch:


current time


recent activity


caregiver-entered task


known household context like “David is home”


Tooling: Backboard memory / orchestration


This is a good Backboard use because the grounding message depends on persistent and recent context, not just the current frame.


Step 5: Add caregiver tasking


Let family members enter “Current task: go to the fridge and grab an orange.”


Tooling: caregiver dashboard in React


Store in Backboard or DB as active task


Step 6: Generate the grounding response


Gemini prompt combines:


room


time


current task


tone constraints


Example output:


“You’re at home in the kitchen. It’s Thursday afternoon. You’re getting an orange from the fridge.”


Step 7: Speak the grounding message


Tooling: ElevenLabs


Best sponsor fit


Gemini for grounding response


Backboard for active context / tasks


ElevenLabs for calm delivery


Vultr for backend inference



4) ACTIVITY CONTINUITY
Step 1: Maintain a rolling activity buffer


Save the last 30–90 seconds of interpreted context.


Tooling: in-memory queue, Redis, or Backboard session memory


Step 2: Infer the current activity


Detect likely activities from objects + motion:


kettle + mug + kitchen counter = making tea


book + couch posture = reading


Tooling:


OpenCV


optional YOLOv8 for object detection


Gemini for higher-level activity interpretation


Step 3: Detect confusion/interruption


Trigger when the user stops, repeats actions, or asks for help.


Tooling: motion heuristics + optional speech cues


Step 4: Retrieve the immediately prior activity


Query the activity buffer:


“What was the most probable task 10–30 seconds ago?”


Tooling: Backboard or local state store


Step 5: Generate a continuity cue


Gemini turns the activity state into a gentle reminder:


“You were making tea. The kettle is on the counter to your left.”


Tooling: Gemini API


Step 6: Speak the cue


Tooling: ElevenLabs


Best sponsor fit


Backboard for short-term continuity memory


Gemini for natural reminder generation


ElevenLabs for voice output



9) WANDERING GUARDIAN
Because you want no phone for now, I’d split this into POC version and future version.
POC version for the hackathon
Step 1: Define safe zones manually


Family labels:


home living room


kitchen


front hallway


outside front porch


Tooling: caregiver dashboard in React


Step 2: Recognize when the scene leaves the safe zone


If the camera view changes from known indoor rooms to sidewalk/street/outdoor unknown area, trigger a wandering event.


Tooling: scene recognition with Gemini or CV classifier


Step 3: Check for escalation


Confirm it’s not just a benign transition by requiring:


outdoors for X seconds


no known destination


confusion signals


Tooling: simple rules engine


Step 4: Generate soft de-escalation


Gemini creates a gentle redirect line:


“Hey Dad, let’s head back home.”


Or better: use a family-authored template


Step 5: Speak in familiar voice


Tooling: ElevenLabs


Stronger demo if you clone or approximate a family voice, subject to your team’s ethical comfort


Step 6: Alert caregiver dashboard


Show:


event time


current scene label


confidence


Tooling: React dashboard + websocket/Firebase updates


Future version after the hackathon
Add phone GPS + geofencing and merge with scene recognition for a real safe-zone system.


Best sponsor fit


Gemini for scene understanding


ElevenLabs for familiar redirect voice


Backboard for escalation rules/history


Vultr for inference hosting



12) CONVERSATION COPILOT
Step 1: Capture audio from the call


Use the WhatsApp call audio stream as the speech source.


Tooling: system audio capture or microphone loopback, depending on your OS


Step 2: Transcribe the conversation


Convert speech into rolling text.


Tooling: Whisper or another STT engine


Step 3: Identify who’s being discussed


Detect names, places, events, repeated questions, and topic drift.


Tooling: NER + Gemini API


Step 4: Retrieve related memory


If conversation mentions:


Sarah


cottage trip


Christmas dinner


fetch the corresponding family/event memory from the store.


Tooling: Backboard memory or DB


Step 5: Detect looping or confusion


Trigger when:


the same question repeats


the user gives no response


topic changes but the user looks lost


Tooling: rules + Gemini reasoning


Step 6: Generate the whisper assist


Example:


“She’s talking about the cottage trip last summer.”


Tooling: Gemini API


Step 7: Deliver privately


For the demo, just play the whisper locally to simulate the private assist channel.


Tooling: ElevenLabs


Best sponsor fit


Gemini is the star here


Backboard provides conversational memory across time


ElevenLabs makes it feel magical



Recommended sponsor mapping by feature
If your team wants the cleanest judging story:
Cloudinary


Family album


media transformations


memory montage


caregiver media UI


strongest fit: Feature 2


Backboard.io


persistent family memory


recent interaction history


active tasks


session continuity


strongest fit: Features 1, 3, 4, 12


Google Gemini


face-context whisper generation


grounding messages


activity interpretation


conversation topic assistance


strongest fit: Features 1, 3, 4, 12


ElevenLabs


all whisper audio


montage narration


calming redirect voice


strongest fit: every feature with audio output


Vultr


host the CV pipeline, APIs, dashboard backend, and montage jobs


strongest fit: entire system infrastructure


Google Antigravity


use as the dev environment and mention it in the build story, but it’s not really part of runtime
