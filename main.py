"""
Monojog Shohochor - AI Talking Robot for Students
"""

import os, re, time, threading, schedule, datetime, tempfile, winsound, sys
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write
import speech_recognition as sr
from gtts import gTTS
from playsound import playsound
from groq import Groq
from dotenv import load_dotenv
import pytz

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

conversation_history = []
BD_TZ = pytz.timezone("Asia/Dhaka")

# ALARM STATE
alarm_waiting = False
alarm_lock = threading.Lock()

def set_alarm_waiting(state: bool):
    global alarm_waiting
    with alarm_lock:
        alarm_waiting = state

def is_alarm_waiting() -> bool:
    with alarm_lock:
        return alarm_waiting

# Google Classroom
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CREDS_FILE = os.path.join(BASE_DIR, "credentials.json")

def get_classroom_service():
    creds = None

    # Load existing token
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            print("[Auth] Token refreshed and saved.")
        except Exception as e:
            print(f"[Auth] Refresh failed: {e}")
            creds = None

    # Login if no valid creds
    if not creds or not creds.valid:
        print("[Auth] Opening browser for Google login...")
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
        creds = flow.run_local_server(
            port=8080,
            access_type="offline",
            prompt="consent",
            open_browser=True
        )
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"[Auth] Login successful! Token saved to {TOKEN_FILE}")

    return build("classroom", "v1", credentials=creds)

def get_assignments() -> list:
    """Fetch all assignments with due dates from Google Classroom."""
    try:
        service = get_classroom_service()
        courses = service.courses().list(courseStates=["ACTIVE"]).execute().get("courses", [])
        assignments = []
        now = datetime.datetime.now(BD_TZ)

        for course in courses:
            course_id = course["id"]
            course_name = course["name"]
            try:
                works = service.courses().courseWork().list(
                    courseId=course_id,
                    orderBy="dueDate asc"
                ).execute().get("courseWork", [])
            except Exception:
                works = []

            for work in works:
                title = work.get("title", "Untitled")
                due = work.get("dueDate")
                due_time = work.get("dueTime", {})
                state = work.get("state", "")

                if due:
                    due_dt = datetime.datetime(
                        due["year"], due["month"], due["day"],
                        due_time.get("hours", 23),
                        due_time.get("minutes", 59),
                        tzinfo=BD_TZ
                    )
                    days_left = (due_dt.date() - now.date()).days
                    assignments.append({
                        "course": course_name,
                        "title": title,
                        "due": due_dt,
                        "days_left": days_left,
                    })

        assignments.sort(key=lambda x: x["due"])
        return assignments

    except Exception as e:
        print(f"[Classroom Error] {e}")
        return []

def speak_assignments(assignments: list):
    """Speak assignment summary clearly."""
    if not assignments:
        msg = "তোমার গুগল ক্লাসরুম যে এখন কোনো উপকামিং এসাইনমেন্ট নেই! রিলাক্স করো."
        print(f"[Classroom] {msg}")
        speak(msg)
        return

    total = len(assignments)
    overdue = [a for a in assignments if a["days_left"] < 0]
    today = [a for a in assignments if a["days_left"] == 0]
    tomorrow = [a for a in assignments if a["days_left"] == 1]
    upcoming = [a for a in assignments if a["days_left"] > 1]

    # Summary message
    summary = f"তোমার মোট {total} টা অ্যাসাইনমেন্ট বাকি আছে "
    if overdue:
        summary += f"{len(overdue)} সাবমিশনের দিন শেষ হয়ে গেছে! "
    if today:
        summary += f"{len(today)} টা আজকে বাকি"
    if tomorrow:
        summary += f"{len(tomorrow)} টা আগামীকাল সাবমিশনের লাস্ট ডেট! "
    if upcoming:
        summary += f"Baki {len(upcoming)} টা upcoming. "

    print(f"\n[Classroom] {summary}")
    speak(summary)
    time.sleep(0.5)

    # Detail each assignment
    for a in assignments[:6]:  # max 6
        days = a["days_left"]
        due_str = a["due"].strftime("%d %B, %I:%M %p")

        if days < 0:
            urgency = f"OVERDUE! {abs(days)}  আগে শেষ হয়ে গেছে!"
        elif days == 0:
            urgency = "আজকে সাবমিশনের দিন!"
        elif days == 1:
            urgency = "আগামীকাল সাবমিশনের লাস্ট ডেট!"
        else:
            urgency = f"{days} দিন বাকি"

        detail = f"{a['course']} course e '{a['title']}' — {due_str} — {urgency}"
        print(f"  → {detail}")
        speak(detail)
        time.sleep(0.3)

def check_and_notify_assignments():
    """Background hourly check — notify if urgent assignments exist."""
    assignments = get_assignments()
    urgent = [a for a in assignments if 0 <= a["days_left"] <= 2]
    if urgent:
        msg = f"Attention! তোমার {len(urgent)} টা অ্যাসাইনমেন্টের ডিউ ডেট খুবই কাছে "
        for a in urgent:
            msg += f"{a['course']} er '{a['title']}' {a['days_left']} দিনের মধ্যে ডিউ . "
        print(f"\n[Auto Reminder] {msg}")
        speak(msg)

def start_classroom_scheduler():
    threading.Timer(10, check_and_notify_assignments).start()
    schedule.every(1).hours.do(check_and_notify_assignments)

# SYSTEM PROMPT 
SYSTEM_PROMPT = """
You are "Monojog Shohochor" (মনোযোগ সহচর), a friendly AI assistant robot for university students in Bangladesh.

Personality:
- Warm, encouraging, supportive like a close friend
- Reply in the SAME language the user uses (Bengali or English)
- Expert Python programming teacher
- Helps with schedule, alarms, reminders
- Connected to Google Classroom
- At night asks about the day — console if sad, celebrate if happy
- Energetic, motivating, never harsh

ALARM TOKENS (include in reply when needed):
- Relative: ALARM_RELATIVE:<seconds>   e.g. 2 min = ALARM_RELATIVE:120
- Specific time: ALARM_SET:<HH:MM>     e.g. 6 AM = ALARM_SET:06:00
- Named reminder: REMINDER_SET:<HH:MM>:<label>

CLASSROOM TOKEN:
- When user asks about assignments, homework, due dates, pending work → include: FETCH_ASSIGNMENTS

Keep replies short and natural.
"""

# TTS
def speak(text: str):
    ascii_ratio = sum(c.isascii() for c in text) / max(len(text), 1)
    lang = "en" if ascii_ratio > 0.85 else "bn"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tmp_path = f.name
        gTTS(text=text, lang=lang, slow=False).save(tmp_path)
        playsound(tmp_path)
        os.unlink(tmp_path)
    except Exception as e:
        print(f"[TTS Error] {e}")

# STT 
SAMPLE_RATE = 16000
RECORD_SECONDS = 7

def listen(duration: int = RECORD_SECONDS) -> str:
    print("\n[Monojog Shohochor] Listening... (speak now)")
    try:
        audio_data = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
    except Exception as e:
        print(f"[Mic Error] {e}")
        return ""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        tmp_wav = f.name
    wav_write(tmp_wav, SAMPLE_RATE, audio_data)

    recognizer = sr.Recognizer()
    with sr.AudioFile(tmp_wav) as source:
        audio = recognizer.record(source)
    os.unlink(tmp_wav)

    try:
        try:
            text = recognizer.recognize_google(audio, language="bn-BD")
        except Exception:
            text = recognizer.recognize_google(audio, language="en-US")
        print(f"[You] {text}")
        return text
    except sr.UnknownValueError:
        print("[STT] Could not understand. Try again.")
        return ""
    except sr.RequestError as e:
        print(f"[STT Error] {e}")
        return ""

# GROQ AI
def get_ai_response(user_input: str) -> str:
    conversation_history.append({"role": "user", "content": user_input})
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history,
            max_tokens=512,
            temperature=0.75,
        )
        reply = response.choices[0].message.content.strip()
        conversation_history.append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        print(f"[Groq Error] {e}")
        return "Oops! Something went wrong. Please try again."

# ALARM
def beep_and_speak(label: str):
    print(f"\n🔔 [ALARM] {label}")
    for _ in range(5):
        winsound.Beep(1000, 600)
        time.sleep(0.3)
    msg = f"Hey! {label}! এখন কিভাবে সাহায্য করতে পারি?"
    print(f"[Monojog Shohochor] {msg}")
    speak(msg)

def run_relative_alarm(seconds: int, label: str):
    print(f"[Scheduler] Input PAUSED. '{label}' rings in {seconds}s.")
    set_alarm_waiting(True)
    time.sleep(seconds)
    set_alarm_waiting(False)
    beep_and_speak(label)

def run_absolute_alarm(time_str: str, label: str):
    now_bd = datetime.datetime.now(BD_TZ)
    alarm_bd = now_bd.replace(
        hour=int(time_str.split(":")[0]),
        minute=int(time_str.split(":")[1]),
        second=0, microsecond=0
    )
    if alarm_bd <= now_bd:
        alarm_bd += datetime.timedelta(days=1)
    delay = (alarm_bd - now_bd).total_seconds()
    print(f"[Scheduler] Input PAUSED. '{label}' at {alarm_bd.strftime('%I:%M %p')} BD ({int(delay)}s).")
    set_alarm_waiting(True)
    time.sleep(delay)
    set_alarm_waiting(False)
    beep_and_speak(label)

def parse_and_schedule(reply: str) -> str:
    # Relative alarm
    m = re.search(r"ALARM_RELATIVE:(\d+)", reply)
    if m:
        seconds = int(m.group(1))
        label = f"{seconds // 60} minute reminder" if seconds >= 60 else f"{seconds} second reminder"
        threading.Thread(target=run_relative_alarm, args=(seconds, label), daemon=True).start()
        reply = reply.replace(m.group(0), "").strip()

    # Absolute alarm
    m = re.search(r"ALARM_SET:(\d{1,2}:\d{2})", reply)
    if m:
        threading.Thread(target=run_absolute_alarm, args=(m.group(1), "Wake Up Alarm"), daemon=True).start()
        reply = reply.replace(m.group(0), "").strip()

    # Named reminder
    m = re.search(r"REMINDER_SET:(\d{1,2}:\d{2}):(.+?)(?:\n|$)", reply)
    if m:
        threading.Thread(target=run_absolute_alarm, args=(m.group(1), m.group(2).strip()), daemon=True).start()
        reply = reply.replace(m.group(0), "").strip()

    # Fetch assignments
    if "FETCH_ASSIGNMENTS" in reply:
        reply = reply.replace("FETCH_ASSIGNMENTS", "").strip()
        threading.Thread(target=lambda: speak_assignments(get_assignments()), daemon=True).start()

    return reply

# NIGHT CHECK-IN 
def night_checkin():
    msg = ""
    print(f"\n[Night Check-in] {msg}")
    speak(msg)
    user_input = listen()
    if user_input:
        reply = get_ai_response(f"[Night check-in] User said: {user_input}")
        clean = parse_and_schedule(reply)
        print(f"[Monojog Shohochor] {clean}")
        speak(clean)

def start_daily_scheduler():
    schedule.every().day.at("22:00").do(night_checkin)
    start_classroom_scheduler()
    def _run():
        while True:
            schedule.run_pending()
            time.sleep(30)
    threading.Thread(target=_run, daemon=True).start()

# MAIN
def main():
    print("=" * 55)
    print("   Monojog Shohochor - Student AI Assistant Robot")
    print("=" * 55)
    print("Google Classroom connected!")
    print("Talk freely! Say 'bye' to quit.\n")

    start_daily_scheduler()

    greeting = ("হ্যালো আমি মনোযোগ সহচর!!! "
                "তোমার Google Classroom এর সাথে যুক্ত আছি. "
                "তোমার অ্যাসাইনমেন্টের ডিউ ডেট, অ্যালার্ট এবং অ্যালার্ম সেট করতে পারি!")
    print(f"[Monojog Shohochor] {greeting}\n")
    speak(greeting)

    while True:
        if is_alarm_waiting():
            print("[System] Alarm pending... input paused.")
            time.sleep(2)
            continue

        user_input = listen()
        if not user_input:
            continue

        if any(x in user_input.lower() for x in ["bye", "exit", "quit", "biday"]):
            farewell = "Bye bye! Take care. Monojog rakho!"
            print(f"[Monojog Shohochor] {farewell}")
            speak(farewell)
            break

        reply = get_ai_response(user_input)
        clean = parse_and_schedule(reply)
        print(f"[Monojog Shohochor] {clean}\n")
        speak(clean)

if __name__ == "__main__":
    main()
