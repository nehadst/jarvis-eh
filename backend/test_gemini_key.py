"""
Quick test script to verify GEMINI_API_KEY and make a minimal Gemini call.
Run from the `backend/` folder:

    python test_gemini_key.py

Exit codes:
  0 = success
  1 = key missing
  2 = google.generativeai not installed
  3 = API call failed
"""

import sys
from config import settings

if not settings.gemini_api_key:
    print("GEMINI_API_KEY not found in .env (settings.gemini_api_key is empty).")
    sys.exit(1)

try:
    import google.generativeai as genai
except Exception as e:
    print("google.generativeai not installed:", e)
    print("Install with: pip install google-generative-ai")
    sys.exit(2)

try:
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    # Minimal prompt to verify key works
    response = model.generate_content("Say hello in one word.")
    text = getattr(response, "text", None)
    print("API call succeeded. Response:")
    print(text)
    sys.exit(0)
except Exception as e:
    print("API call failed:", e)
    sys.exit(3)
