"""
Run this ONCE to login and save token.json permanently.
    python get_token.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CREDS_FILE = os.path.join(BASE_DIR, "credentials.json")

import os
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"  # allow scope changes

print("Opening browser for Google login...")
flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

with open(TOKEN_FILE, "w", encoding="utf-8") as f:
    f.write(creds.to_json())

print(f"\nSUCCESS! token.json saved to: {TOKEN_FILE}")
print("Now run main.py — it will never ask for login again!")