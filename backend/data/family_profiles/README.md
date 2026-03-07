# Family Profiles

Each person in the patient's family has a JSON file here.
The filename **must match** the `id` field and the subfolder name in `face_db/`.

## Example

```
family_profiles/
  sarah_johnson.json    ← profile
  david_smith.json

face_db/
  sarah_johnson/        ← folder name must match the JSON id
    img1.jpg
    img2.jpg
  david_smith/
    img1.jpg
```

## Profile Schema

```json
{
  "id": "sarah_johnson",           // must match filename and face_db folder
  "name": "Sarah Johnson",         // full display name
  "relationship": "granddaughter", // e.g. son, daughter, husband, friend
  "age": 24,
  "face_folder": "sarah_johnson",  // subfolder under data/face_db/
  "cloudinary_folder": "rewind/family/sarah_johnson",
  "last_interaction": {
    "date": "2026-02-28",          // ISO date
    "summary": "She came by and you watched a movie together"
  },
  "personal_detail": "She just started working as a nurse",
  "voice_anchor_file": null,       // optional path to their voice recording
  "notes": [],                     // any extra notes the caregiver adds
  "calming_anchors": []            // phrases to help ground the patient
}
```

## Adding a New Person

1. Add their photos to `face_db/{their_id}/`
2. Create `family_profiles/{their_id}.json` using the schema above
3. Restart the backend (or call `POST /api/capture/start` again — profiles reload automatically)
