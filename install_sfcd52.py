from pathlib import Path
import shutil, sys, time

root = Path.cwd()
app = root / 'app.py'
templates = root / 'templates'
source_home = Path(__file__).resolve().parent / 'templates' / 'home.html'

if not app.exists() or not templates.exists():
    sys.exit('ERROR: Run this from the SFCD5 repository root (where app.py and templates/ exist).')

text = app.read_text(encoding='utf-8')
old = """@app.route('/', methods=['GET'])\ndef index():\n    return redirect(url_for('announcements'))"""
new = """@app.route('/', methods=['GET'])\ndef index():\n    # SFCD 5.2 member home. Read-only queries only; existing public/admin/voting routes remain unchanged.\n    ensure_dynamic_rsvp_tables()\n    conn = get_db()\n    announcements = conn.execute(\n        \"SELECT * FROM announcements ORDER BY created_at DESC LIMIT 3\"\n    ).fetchall()\n    events = conn.execute(\n        \"SELECT * FROM events WHERE event_date >= date('now') ORDER BY event_date ASC, event_time ASC LIMIT 3\"\n    ).fetchall()\n    photos = conn.execute(\n        \"SELECT * FROM gallery ORDER BY created_at DESC LIMIT 3\"\n    ).fetchall()\n    election = conn.execute(\n        \"SELECT * FROM election_sessions ORDER BY id DESC LIMIT 1\"\n    ).fetchone()\n    rsvp_event = conn.execute(\n        \"SELECT * FROM rsvp_events WHERE active=1 AND event_date >= date('now') ORDER BY event_date ASC, event_time ASC LIMIT 1\"\n    ).fetchone()\n    conn.close()\n    return render_template(\n        'home.html',\n        announcements=announcements,\n        events=events,\n        photos=photos,\n        election=election,\n        rsvp_event=rsvp_event\n    )"""

if new in text:
    print('app.py already contains the SFCD 5.2 home route; no route change needed.')
elif old not in text:
    sys.exit("ERROR: Expected current index route was not found. app.py was NOT changed. This protects your working deployment.")
else:
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = root / f'app.py.pre-sfcd52-{stamp}.bak'
    shutil.copy2(app, backup)
    app.write_text(text.replace(old, new, 1), encoding='utf-8')
    print(f'Updated app.py. Backup: {backup.name}')

shutil.copy2(source_home, templates / 'home.html')
print('Installed templates/home.html')
print('SFCD 5.2 Phase 1 installation complete.')
