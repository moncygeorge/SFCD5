from pathlib import Path
import shutil
import re
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
TEMPLATE = ROOT / "templates" / "member_home.html"
BACKUP = ROOT / "app.py.sfcd51.backup"

if not APP.exists():
    raise SystemExit("app.py was not found.")
if not TEMPLATE.exists():
    raise SystemExit("templates/member_home.html is missing.")

text = APP.read_text(encoding="utf-8")

old = """@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('announcements'))
"""

new = """@app.route('/', methods=['GET'])
def index():
    conn = get_db()
    latest_announcement = conn.execute(
        "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    upcoming_events = conn.execute(
        "SELECT * FROM events WHERE event_date >= date('now') ORDER BY event_date ASC, event_time ASC LIMIT 3"
    ).fetchall()
    gallery_photos = conn.execute(
        "SELECT * FROM gallery ORDER BY created_at DESC LIMIT 3"
    ).fetchall()

    election_open = False
    try:
        row = conn.execute(
            "SELECT id FROM election_sessions WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        election_open = row is not None
    except Exception:
        election_open = False

    conn.close()

    return render_template(
        'member_home.html',
        latest_announcement=latest_announcement,
        upcoming_events=upcoming_events,
        gallery_photos=gallery_photos,
        election_open=election_open,
        election_route_available=False
    )
"""

if new in text:
    print("SFCD 5.2 member home is already installed.")
    sys.exit(0)

if old not in text:
    raise SystemExit(
        "Safety stop: the expected SFCD 5.1 home route was not found. "
        "No changes were made."
    )

if not BACKUP.exists():
    shutil.copy2(APP, BACKUP)
    print(f"Backup created: {BACKUP.name}")

APP.write_text(text.replace(old, new, 1), encoding="utf-8")
print("SFCD 5.2 member home installed successfully.")
print("Run: python -m py_compile app.py")
