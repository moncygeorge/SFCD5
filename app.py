import sqlite3
import os
import uuid
import csv
import io
import secrets
import time
from werkzeug.utils import secure_filename
from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, session, jsonify, send_file, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from init_db import create_tables, migrate_files_to_db
from push import save_subscription, send_push_to_all, VAPID_PUBLIC_KEY, push_configured

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-aws')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB upload limit

# AWS-ready data configuration. Set DATA_DIR to an attached/persistent path
# (for example an EFS mount) or set DB_PATH directly. Local development
# defaults to ./data/sfcd.db.
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.environ.get('DB_PATH', os.path.join(DATA_DIR, 'sfcd.db'))

# ── uploads ────────────────────────────────────────────────────────────────
UPLOAD_ROOT      = os.path.join('static', 'uploads')
ALLOWED_UPLOAD_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

for sub in ('announcements', 'events', 'gallery'):
    os.makedirs(os.path.join(UPLOAD_ROOT, sub), exist_ok=True)


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_UPLOAD_EXTS


def save_uploaded_image(file_storage, subfolder):
    """Saves an uploaded image under static/uploads/<subfolder>/ and
    returns the web path to store in the DB, or None if no valid file."""
    if not file_storage or file_storage.filename == '':
        return None
    if not allowed_image(file_storage.filename):
        flash("Only image files (png, jpg, jpeg, gif, webp) are allowed.", "danger")
        return None

    ext      = file_storage.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filename = secure_filename(filename)
    rel_path = os.path.join(UPLOAD_ROOT, subfolder, filename)
    file_storage.save(rel_path)
    return '/' + rel_path.replace(os.sep, '/')

# ── file paths kept for backward-compat / PDF generation ──────────────────────
usernames_file = 'usernames.txt'
choices_file   = 'choices.txt'
votes_file     = 'votes.txt'
role_file      = 'roles.txt'

# ── initialise DB on every startup ────────────────────────────────────────────
with app.app_context():
    create_tables(DB_FILE)
    migrate_files_to_db(DB_FILE, role_file, choices_file, votes_file)

# ── helpers ───────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_dynamic_rsvp_tables():
    """Create the dynamic RSVP tables used by generated event links."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rsvp_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rsvp_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            first_name TEXT NOT NULL,
            attending TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES rsvp_events(id)
        )
    """)
    conn.commit()
    conn.close()


ensure_dynamic_rsvp_tables()

def load_role():
    """Return the current role from the DB."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key='current_role'"
    ).fetchone()
    conn.close()
    return row['value'] if row else None

def load_voting_status():
    """Return 'open' or 'closed' (defaults to 'closed' if not set)."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key='voting_status'"
    ).fetchone()
    conn.close()
    return row['value'] if row else 'closed'

# ── auth ──────────────────────────────────────────────────────────────────────
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash("Please enter both username and password.", "danger")
            return redirect(url_for('admin_login'))

        try:
            conn = get_db()
            admin = conn.execute(
                "SELECT * FROM admins WHERE username=?", (username,)
            ).fetchone()
            conn.close()

            if admin and check_password_hash(admin['password_hash'], password):
                session.clear()
                session['username'] = 'admin'
                session['is_admin'] = True
                return redirect(url_for('admin_dashboard'))
            else:
                flash("Invalid username or password.", "danger")
                return redirect(url_for('admin_login'))

        except Exception as e:
            flash(f"Database error: {e}", "danger")
            return redirect(url_for('admin_login'))

    return render_template('admin_login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if 'username' in session:
            return redirect(url_for('vote'))
        next_url = request.args.get('next', '') or url_for('vote')
        return render_template('login.html', next=next_url)

    session.clear()
    phone    = request.form.get('username', '').strip()
    phone    = ''.join(phone.split())
    next_url = request.form.get('next', '').strip()

    # only allow relative redirects, never an external URL
    if not next_url.startswith('/'):
        next_url = url_for('vote')

    if not phone:
        flash("Please enter a phone number.", "danger")
        return redirect(url_for('login', next=next_url))

    try:
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE phone_number=?", (phone,)
        ).fetchone()
        conn.close()

        if user:
            session['username'] = phone
            flash(f"Welcome!", "success")
            return redirect(next_url)
        else:
            flash("Phone number not authorized.", "danger")
            return redirect(url_for('login', next=next_url))

    except Exception as e:
        flash(f"Database error: {e}", "danger")
        return redirect(url_for('login', next=next_url))


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('index'))


@app.route('/admin_logout')
def admin_logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('admin_login'))


@app.route('/setup_admin', methods=['GET', 'POST'])
def setup_admin():
    # Self-healing first-admin setup for fresh AWS deployments.
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS admins (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL,
               created_at DATETIME DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.commit()
    existing = conn.execute("SELECT id FROM admins LIMIT 1").fetchone()
    conn.close()

    if existing:
        flash("Admin account already exists.", "warning")
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not username or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for('setup_admin'))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('setup_admin'))
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for('setup_admin'))

        conn = get_db()
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password))
        )
        conn.commit()
        conn.close()
        flash("Admin account created! Please log in.", "success")
        return redirect(url_for('admin_login'))

    # Inline page avoids a TemplateNotFound error if setup_admin.html was lost.
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Create Admin</title>
      <style>
        body{font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:40px 16px}
        .card{max-width:420px;margin:auto;background:white;padding:28px;border-radius:12px;box-shadow:0 2px 12px #0002}
        input{width:100%;box-sizing:border-box;padding:12px;margin:8px 0 16px;border:1px solid #ccc;border-radius:7px}
        button{width:100%;padding:12px;border:0;border-radius:7px;background:#1f5f4a;color:white;font-weight:bold}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>Create Admin Account</h2>
        <form method="post">
          <label>Username</label>
          <input name="username" required>
          <label>Password</label>
          <input type="password" name="password" minlength="8" required>
          <label>Confirm Password</label>
          <input type="password" name="confirm" minlength="8" required>
          <button type="submit">Create Admin</button>
        </form>
      </div>
    </body>
    </html>
    """)

# ── AWS / load balancer health check ─────────────────────────────────────────
@app.route('/health')
def health():
    try:
        conn = get_db()
        conn.execute('SELECT 1').fetchone()
        conn.close()
        return jsonify({'status': 'ok'}), 200
    except Exception as exc:
        return jsonify({'status': 'error', 'detail': str(exc)}), 500


# ── public pages ──────────────────────────────────────────────────────────────
@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('announcements'))


@app.route('/rsvp', methods=['GET', 'POST'])
def rsvp():
    if request.method == 'POST':
        first_name = ' '.join(request.form.get('first_name', '').strip().split())
        confirmed = request.form.get('attending') == 'yes'
        if not first_name:
            flash('Please enter your first name.', 'danger')
            return redirect(url_for('rsvp'))
        if len(first_name) > 60:
            flash('Please enter a shorter first name.', 'danger')
            return redirect(url_for('rsvp'))
        if not confirmed:
            flash('Please confirm that you are coming.', 'danger')
            return redirect(url_for('rsvp'))

        conn = get_db()
        conn.execute(
            "INSERT INTO rsvps (first_name, attending) VALUES (?, 1) "
            "ON CONFLICT(first_name) DO UPDATE SET attending=1, updated_at=CURRENT_TIMESTAMP",
            (first_name,)
        )
        conn.commit()
        conn.close()
        return render_template('rsvp_thanks.html', first_name=first_name, attending=True)
    return render_template('rsvp.html')

@app.route('/admin/rsvp')
def admin_rsvp():
    if not admin_required():
        flash('Access restricted to admin only.', 'danger')
        return redirect(url_for('admin_login'))
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM rsvps WHERE attending=1 ORDER BY first_name COLLATE NOCASE'
    ).fetchall()
    conn.close()
    attending_count = len(rows)
    return render_template('admin_rsvp.html', rsvps=rows, attending_count=attending_count, total_count=attending_count)

@app.route('/admin/rsvp/download')
def download_rsvps():
    if not admin_required():
        flash('Access restricted to admin only.', 'danger')
        return redirect(url_for('admin_login'))
    conn = get_db()
    rows = conn.execute('SELECT first_name, attending, created_at, updated_at FROM rsvps WHERE attending=1 ORDER BY first_name COLLATE NOCASE').fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['First Name', 'Attending', 'Created At', 'Updated At'])
    for row in rows:
        writer.writerow([row['first_name'], 'Yes' if row['attending'] else 'No', row['created_at'], row['updated_at']])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=practical_evangelism_rsvps.csv'
    return response


# ── dynamic RSVP event links ─────────────────────────────────────────────────
@app.route('/admin/rsvp/create', methods=['POST'])
def create_rsvp_event():
    if not admin_required():
        flash('Access restricted to admin only.', 'danger')
        return redirect(url_for('admin_login'))

    title = request.form.get('title', '').strip()
    event_date = request.form.get('event_date', '').strip()
    event_time = request.form.get('event_time', '').strip()

    if not title or not event_date or not event_time:
        flash('Event title, date, and time are required.', 'danger')
        return redirect(url_for('admin_dashboard'))

    ensure_dynamic_rsvp_tables()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO rsvp_events (title, event_date, event_time) VALUES (?, ?, ?)",
        (title, event_date, event_time)
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()

    flash('RSVP link created successfully.', 'success')
    return redirect(url_for('admin_dashboard', created=event_id))


@app.route('/rsvp/<int:event_id>', methods=['GET', 'POST'])
def rsvp_event(event_id):
    ensure_dynamic_rsvp_tables()
    conn = get_db()
    event = conn.execute(
        "SELECT * FROM rsvp_events WHERE id=? AND active=1",
        (event_id,)
    ).fetchone()

    if not event:
        conn.close()
        return 'RSVP event not found.', 404

    submitted = False
    if request.method == 'POST':
        first_name = ' '.join(request.form.get('first_name', '').strip().split())
        attending = request.form.get('attending', '').strip()
        normalized = {'yes': 'Yes', 'no': 'No'}.get(attending.lower())

        if not first_name:
            flash('Please enter your first name.', 'danger')
        elif len(first_name) > 60:
            flash('Please enter a shorter first name.', 'danger')
        elif not normalized:
            flash('Please select Yes or No.', 'danger')
        else:
            conn.execute(
                "INSERT INTO rsvp_responses (event_id, first_name, attending) VALUES (?, ?, ?)",
                (event_id, first_name, normalized)
            )
            conn.commit()
            submitted = True

    conn.close()
    return render_template('rsvp.html', event=event, submitted=submitted)


@app.route('/admin/rsvp/<int:event_id>')
def admin_rsvp_results(event_id):
    if not admin_required():
        flash('Access restricted to admin only.', 'danger')
        return redirect(url_for('admin_login'))

    ensure_dynamic_rsvp_tables()
    conn = get_db()
    event = conn.execute(
        "SELECT * FROM rsvp_events WHERE id=?",
        (event_id,)
    ).fetchone()

    if not event:
        conn.close()
        return 'RSVP event not found.', 404

    responses = conn.execute(
        "SELECT * FROM rsvp_responses WHERE event_id=? ORDER BY created_at DESC",
        (event_id,)
    ).fetchall()
    conn.close()

    return render_template('admin_rsvp_results.html', event=event, responses=responses)


@app.route('/vote')
def vote():
    if 'username' not in session:
        return redirect(url_for('login', next='/vote'))

    role   = load_role()
    status = load_voting_status()

    conn = get_db()
    rows = conn.execute(
        "SELECT choice FROM choices WHERE role=?", (role,)
    ).fetchall() if role else []

    has_voted = False
    tally     = {}
    if role:
        existing = conn.execute(
            "SELECT id FROM votes WHERE username=? AND role=?",
            (session['username'], role)
        ).fetchone()
        has_voted = existing is not None

        if status == 'closed':
            tally_rows = conn.execute(
                "SELECT choice, COUNT(*) as cnt FROM votes WHERE role=? GROUP BY choice",
                (role,)
            ).fetchall()
            tally = {r['choice']: r['cnt'] for r in tally_rows}

    conn.close()
    choices = [r['choice'] for r in rows]

    return render_template(
        'vote.html',
        role=role,
        status=status,
        choices=choices,
        has_voted=has_voted,
        tally=tally,
    )


@app.route('/view_role')
def view_role():
    role = load_role()
    return render_template('view_role.html', role=role)

# ── announcements (public) ──────────────────────────────────────────────────
@app.route('/announcements')
def announcements():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM announcements ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template('announcements.html', announcements=rows)

# ── events (public) ─────────────────────────────────────────────────────────
@app.route('/events')
def events():
    conn = get_db()
    upcoming = conn.execute(
        "SELECT * FROM events WHERE event_date >= date('now') ORDER BY event_date ASC, event_time ASC"
    ).fetchall()
    past = conn.execute(
        "SELECT * FROM events WHERE event_date < date('now') ORDER BY event_date DESC, event_time DESC"
    ).fetchall()
    conn.close()
    return render_template('events.html', upcoming=upcoming, past=past)

# ── gallery (public) ────────────────────────────────────────────────────────
@app.route('/gallery')
def gallery():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM gallery ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template('gallery.html', photos=rows)

# ── push notifications ──────────────────────────────────────────────────────
@app.route('/vapid_public_key')
def vapid_public_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY, "configured": push_configured()})


@app.route('/save_subscription', methods=['POST'])
def save_subscription_route():
    # No login required — announcements/events are public, so anyone who
    # installs the app can opt in to notifications, not just voters.
    subscription = request.get_json(silent=True)
    if not subscription:
        return jsonify({"error": "Missing subscription payload"}), 400
    ok = save_subscription(DB_FILE, subscription, username=session.get('username'))
    if not ok:
        return jsonify({"error": "Invalid subscription payload"}), 400
    return jsonify({"message": "Subscribed"}), 200

# ── voting ────────────────────────────────────────────────────────────────────
@app.route('/submit_vote', methods=['POST'])
def submit_vote():
    if 'username' not in session:
        return redirect(url_for('login', next='/vote'))

    role   = load_role()
    status = load_voting_status()

    if not role:
        flash("No active role to vote on.", "danger")
        return redirect(url_for('vote'))

    if status != 'open':
        flash("Voting is currently closed.", "danger")
        return redirect(url_for('vote'))

    choice = request.form.get('choice')
    if not choice:
        flash("Please select a choice to vote for.", "danger")
        return redirect(url_for('vote'))

    username = session['username']
    try:
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM votes WHERE username=? AND role=?", (username, role)
        ).fetchone()

        if existing:
            flash(f"You have already voted for '{role}'.", "danger")
        else:
            conn.execute(
                "INSERT INTO votes (username, role, choice) VALUES (?, ?, ?)",
                (username, role, choice)
            )
            conn.commit()
            flash(f"Your vote for {choice} has been recorded!", "success")
        conn.close()

    except Exception as e:
        flash(f"An error occurred: {e}", "danger")

    return redirect(url_for('vote'))

# ── API endpoints ─────────────────────────────────────────────────────────────
@app.route('/api/current_role', methods=['GET'])
def get_current_role_api():
    return jsonify({"role": load_role()}), 200


@app.route('/api/voter_status', methods=['GET'])
def voter_status():
    if 'username' not in session:
        return jsonify({"error": "Not logged in"}), 401

    role   = load_role()
    status = load_voting_status()

    if not role:
        return jsonify({"role": None, "status": "closed", "choices": [], "has_voted": False, "tally": {}})

    conn = get_db()
    rows = conn.execute(
        "SELECT choice FROM choices WHERE role=?", (role,)
    ).fetchall()
    existing = conn.execute(
        "SELECT id FROM votes WHERE username=? AND role=?",
        (session['username'], role)
    ).fetchone()

    tally = {}
    if status == 'closed':
        tally_rows = conn.execute(
            "SELECT choice, COUNT(*) as cnt FROM votes WHERE role=? GROUP BY choice",
            (role,)
        ).fetchall()
        tally = {r['choice']: r['cnt'] for r in tally_rows}

    conn.close()

    return jsonify({
        "role":      role,
        "status":    status,
        "choices":   [r['choice'] for r in rows],
        "has_voted": existing is not None,
        "tally":     tally,
    })


@app.route('/api/submit_vote', methods=['POST'])
def submit_vote_api():
    if 'username' not in session:
        return jsonify({"error": "Please log in first."}), 401

    role   = load_role()
    status = load_voting_status()

    if status != 'open':
        return jsonify({"error": "Voting is currently closed."}), 400

    data   = request.get_json()
    choice = data.get('choice') if data else None
    if not choice:
        return jsonify({"error": "Please select a choice."}), 400

    username = session['username']
    try:
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM votes WHERE username=? AND role=?", (username, role)
        ).fetchone()

        if existing:
            conn.close()
            return jsonify({"error": "You have already voted."}), 400

        conn.execute(
            "INSERT INTO votes (username, role, choice) VALUES (?, ?, ?)",
            (username, role, choice)
        )
        conn.commit()
        conn.close()
        return jsonify({"message": f"Your vote for {choice} has been recorded!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Phased election session ────────────────────────────────────────────────────
ELECTION_OTP_TTL = 300
ELECTION_AUTH_TTL = 14400

def ensure_election_tables():
    conn=get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS election_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'closed',created_at DATETIME DEFAULT CURRENT_TIMESTAMP,opened_at DATETIME,closed_at DATETIME);
    CREATE TABLE IF NOT EXISTS election_phases (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER NOT NULL,position TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'closed',opened_at DATETIME,closed_at DATETIME);
    CREATE TABLE IF NOT EXISTS election_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT,phase_id INTEGER NOT NULL,name TEXT NOT NULL,UNIQUE(phase_id,name));
    CREATE TABLE IF NOT EXISTS election_voter_status (id INTEGER PRIMARY KEY AUTOINCREMENT,phase_id INTEGER NOT NULL,voter_id INTEGER NOT NULL,voted_at DATETIME DEFAULT CURRENT_TIMESTAMP,UNIQUE(phase_id,voter_id));
    CREATE TABLE IF NOT EXISTS election_ballots (id INTEGER PRIMARY KEY AUTOINCREMENT,phase_id INTEGER NOT NULL,candidate_id INTEGER NOT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS election_otp (id INTEGER PRIMARY KEY AUTOINCREMENT,voter_id INTEGER NOT NULL,code_hash TEXT NOT NULL,expires_at INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    """); conn.commit(); conn.close()
ensure_election_tables()

def current_election(conn):
    return conn.execute("SELECT * FROM election_sessions WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()

def current_phase(conn,eid):
    return conn.execute("SELECT * FROM election_phases WHERE session_id=? AND status='open' ORDER BY id DESC LIMIT 1",(eid,)).fetchone()

def election_verified():
    return bool(session.get('election_voter_id') and int(time.time())-int(session.get('election_verified_at',0)) <= ELECTION_AUTH_TTL)

def send_election_otp(phone, code):
    # TEST MODE: code is written to the SFCD5 service log.
    # Replace this function with Twilio before production.
    print(f"[SFCD OTP] {phone}: {code}", flush=True)
    return True

@app.route('/election')
def election_home():
    conn=get_db(); e=current_election(conn)
    if not e:
        conn.close(); return render_template('election_wait.html',election=None,message='The voting session is currently closed.')
    if not election_verified():
        conn.close(); return redirect(url_for('election_login'))
    p=current_phase(conn,e['id'])
    if not p:
        conn.close(); return render_template('election_wait.html',election=e,message='You are verified. Please wait for the next voting phase.')
    voter=session['election_voter_id']
    voted=conn.execute("SELECT 1 FROM election_voter_status WHERE phase_id=? AND voter_id=?",(p['id'],voter)).fetchone()
    candidates=conn.execute("SELECT id,name FROM election_candidates WHERE phase_id=? ORDER BY id",(p['id'],)).fetchall()
    conn.close()
    if voted:
        return render_template('election_wait.html',election=e,phase=p,message=f"Your vote for {p['position']} has been recorded. Please wait for the next voting phase.")
    return render_template('election_ballot.html',election=e,phase=p,candidates=candidates)

@app.route('/election/status')
def election_status():
    conn=get_db(); e=current_election(conn); p=current_phase(conn,e['id']) if e else None; conn.close()
    return jsonify(session_open=bool(e),session_id=e['id'] if e else None,phase_id=p['id'] if p else None,position=p['position'] if p else None)

@app.route('/election/login',methods=['GET','POST'])
def election_login():
    if request.method=='GET': return render_template('election_login.html')
    phone=''.join(request.form.get('phone','').split())
    conn=get_db(); e=current_election(conn); voter=conn.execute("SELECT id,phone_number FROM users WHERE phone_number=?",(phone,)).fetchone()
    if not e:
        conn.close(); flash('The voting session is currently closed.','danger'); return redirect(url_for('election_login'))
    if not voter:
        conn.close(); flash('This phone number is not registered to vote.','danger'); return redirect(url_for('election_login'))
    code=f"{secrets.randbelow(1000000):06d}"
    conn.execute("UPDATE election_otp SET used=1 WHERE voter_id=? AND used=0",(voter['id'],))
    conn.execute("INSERT INTO election_otp(voter_id,code_hash,expires_at) VALUES(?,?,?)",(voter['id'],generate_password_hash(code),int(time.time())+ELECTION_OTP_TTL))
    conn.commit(); conn.close()
    send_election_otp(phone,code)
    session['pending_election_voter_id']=voter['id']; session['pending_election_phone']=phone
    return redirect(url_for('election_verify'))

@app.route('/election/verify',methods=['GET','POST'])
def election_verify():
    voter=session.get('pending_election_voter_id')
    if not voter: return redirect(url_for('election_login'))
    if request.method=='GET': return render_template('election_verify.html',phone=session.get('pending_election_phone'))
    code=request.form.get('code','').strip(); conn=get_db()
    otp=conn.execute("SELECT * FROM election_otp WHERE voter_id=? AND used=0 ORDER BY id DESC LIMIT 1",(voter,)).fetchone()
    if not otp or otp['expires_at']<int(time.time()) or otp['attempts']>=5:
        conn.close(); flash('Verification code expired. Request a new one.','danger'); return redirect(url_for('election_login'))
    if not check_password_hash(otp['code_hash'],code):
        conn.execute("UPDATE election_otp SET attempts=attempts+1 WHERE id=?",(otp['id'],)); conn.commit(); conn.close()
        flash('Invalid verification code.','danger'); return redirect(url_for('election_verify'))
    conn.execute("UPDATE election_otp SET used=1 WHERE id=?",(otp['id'],)); conn.commit(); conn.close()
    session.pop('pending_election_voter_id',None); session.pop('pending_election_phone',None)
    session['election_voter_id']=voter; session['election_verified_at']=int(time.time())
    return redirect(url_for('election_home'))

@app.route('/election/vote',methods=['POST'])
def election_vote():
    if not election_verified(): return redirect(url_for('election_login'))
    cid=request.form.get('candidate_id',type=int); voter=session['election_voter_id']; conn=get_db(); e=current_election(conn); p=current_phase(conn,e['id']) if e else None
    if not e or not p:
        conn.close(); flash('Voting is not currently open.','danger'); return redirect(url_for('election_home'))
    valid=conn.execute("SELECT 1 FROM election_candidates WHERE id=? AND phase_id=?",(cid,p['id'])).fetchone()
    if not valid:
        conn.close(); flash('Select a valid candidate.','danger'); return redirect(url_for('election_home'))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO election_voter_status(phase_id,voter_id) VALUES(?,?)",(p['id'],voter))
        conn.execute("INSERT INTO election_ballots(phase_id,candidate_id) VALUES(?,?)",(p['id'],cid))
        conn.commit(); flash('Your vote has been recorded.','success')
    except sqlite3.IntegrityError:
        conn.rollback(); flash('You have already voted in this phase.','warning')
    finally: conn.close()
    return redirect(url_for('election_home'))

@app.route('/admin/election/create',methods=['POST'])
def admin_create_election():
    if not admin_required(): return redirect(url_for('admin_login'))
    title=request.form.get('title','').strip()
    if not title: flash('Election title is required.','danger'); return redirect(url_for('admin_dashboard'))
    conn=get_db(); conn.execute("INSERT INTO election_sessions(title) VALUES(?)",(title,)); conn.commit(); conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/election/<int:eid>/toggle',methods=['POST'])
def admin_toggle_election(eid):
    if not admin_required(): return redirect(url_for('admin_login'))
    conn=get_db(); e=conn.execute("SELECT * FROM election_sessions WHERE id=?",(eid,)).fetchone()
    if not e: conn.close(); return 'Election not found',404
    if e['status']=='open':
        conn.execute("UPDATE election_phases SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE session_id=? AND status='open'",(eid,))
        conn.execute("UPDATE election_sessions SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE id=?",(eid,))
    else:
        conn.execute("UPDATE election_sessions SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE status='open'")
        conn.execute("UPDATE election_sessions SET status='open',opened_at=CURRENT_TIMESTAMP,closed_at=NULL WHERE id=?",(eid,))
    conn.commit(); conn.close(); return redirect(url_for('admin_dashboard'))

@app.route('/admin/election/<int:eid>/phase/create',methods=['POST'])
def admin_create_phase(eid):
    if not admin_required(): return redirect(url_for('admin_login'))
    position=request.form.get('position','').strip(); names=[x.strip() for x in request.form.get('candidates','').splitlines() if x.strip()]
    if not position or len(names)<2: flash('Position and at least two candidates are required.','danger'); return redirect(url_for('admin_dashboard'))
    conn=get_db(); cur=conn.execute("INSERT INTO election_phases(session_id,position) VALUES(?,?)",(eid,position)); pid=cur.lastrowid
    conn.executemany("INSERT INTO election_candidates(phase_id,name) VALUES(?,?)",[(pid,n) for n in names]); conn.commit(); conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/election/phase/<int:pid>/toggle',methods=['POST'])
def admin_toggle_phase(pid):
    if not admin_required(): return redirect(url_for('admin_login'))
    conn=get_db(); p=conn.execute("SELECT * FROM election_phases WHERE id=?",(pid,)).fetchone()
    if not p: conn.close(); return 'Phase not found',404
    e=conn.execute("SELECT * FROM election_sessions WHERE id=?",(p['session_id'],)).fetchone()
    if not e or e['status']!='open': conn.close(); flash('Open the voting session first.','danger'); return redirect(url_for('admin_dashboard'))
    if p['status']=='open': conn.execute("UPDATE election_phases SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE id=?",(pid,))
    else:
        conn.execute("UPDATE election_phases SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE session_id=? AND status='open'",(p['session_id'],))
        conn.execute("UPDATE election_phases SET status='open',opened_at=CURRENT_TIMESTAMP,closed_at=NULL WHERE id=?",(pid,))
    conn.commit(); conn.close(); return redirect(url_for('admin_dashboard'))

@app.route('/admin/election/phase/<int:pid>/results')
def admin_phase_results(pid):
    if not admin_required(): return redirect(url_for('admin_login'))
    conn=get_db(); p=conn.execute("SELECT * FROM election_phases WHERE id=?",(pid,)).fetchone()
    tally=conn.execute("SELECT c.name,COUNT(b.id) cnt FROM election_candidates c LEFT JOIN election_ballots b ON b.candidate_id=c.id WHERE c.phase_id=? GROUP BY c.id,c.name ORDER BY cnt DESC,c.id",(pid,)).fetchall()
    total=conn.execute("SELECT COUNT(*) cnt FROM election_ballots WHERE phase_id=?",(pid,)).fetchone()['cnt']; conn.close()
    return render_template('election_results.html',phase=p,tally=tally,total=total)


# ── SFCD5 reusable voting-event links ─────────────────────────────────────────
def ensure_voting_event_tables():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS voting_events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, question TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'closed', active INTEGER NOT NULL DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS voting_event_choices (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, choice TEXT NOT NULL, UNIQUE(event_id, choice), FOREIGN KEY(event_id) REFERENCES voting_events(id));
        CREATE TABLE IF NOT EXISTS voting_event_votes (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, username TEXT NOT NULL, choice TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(event_id, username), FOREIGN KEY(event_id) REFERENCES voting_events(id));
    """)
    conn.commit(); conn.close()

ensure_voting_event_tables()

@app.route('/admin/voting/create', methods=['POST'])
def create_voting_event():
    if not admin_required():
        return redirect(url_for('admin_login'))
    title = request.form.get('title', '').strip()
    question = request.form.get('question', '').strip()
    choices = [c.strip() for c in request.form.get('choices', '').splitlines() if c.strip()]
    if not title or not question or len(choices) < 2:
        flash('Voting title, question, and at least two choices are required.', 'danger')
        return redirect(url_for('admin_dashboard'))
    conn = get_db()
    cur = conn.execute("INSERT INTO voting_events(title, question, status) VALUES (?, ?, 'closed')", (title, question))
    event_id = cur.lastrowid
    conn.executemany("INSERT INTO voting_event_choices(event_id, choice) VALUES (?, ?)", [(event_id, c) for c in choices])
    conn.commit(); conn.close()
    flash('Voting link created. Review it, then open voting when ready.', 'success')
    return redirect(url_for('admin_dashboard', vote_created=event_id))

@app.route('/admin/voting/<int:event_id>/toggle', methods=['POST'])
def toggle_voting_event(event_id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    conn = get_db(); event = conn.execute('SELECT * FROM voting_events WHERE id=?', (event_id,)).fetchone()
    if not event:
        conn.close(); return 'Voting event not found.', 404
    new_status = 'closed' if event['status'] == 'open' else 'open'
    conn.execute('UPDATE voting_events SET status=? WHERE id=?', (new_status, event_id)); conn.commit(); conn.close()
    flash(f'Voting is now {new_status}.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/vote/<int:event_id>')
def vote_event(event_id):
    if 'username' not in session or session.get('is_admin'):
        return redirect(url_for('login', next=f'/vote/{event_id}'))
    conn = get_db(); event = conn.execute('SELECT * FROM voting_events WHERE id=? AND active=1', (event_id,)).fetchone()
    if not event:
        conn.close(); return 'Voting event not found.', 404
    choices = [r['choice'] for r in conn.execute('SELECT choice FROM voting_event_choices WHERE event_id=? ORDER BY id', (event_id,)).fetchall()]
    existing = conn.execute('SELECT choice FROM voting_event_votes WHERE event_id=? AND username=?', (event_id, session['username'])).fetchone(); conn.close()
    return render_template('vote_event.html', event=event, choices=choices, has_voted=existing is not None)

@app.route('/vote/<int:event_id>/submit', methods=['POST'])
def submit_vote_event(event_id):
    if 'username' not in session or session.get('is_admin'):
        return redirect(url_for('login', next=f'/vote/{event_id}'))
    choice = request.form.get('choice', '').strip(); conn = get_db()
    event = conn.execute('SELECT * FROM voting_events WHERE id=? AND active=1', (event_id,)).fetchone()
    valid = conn.execute('SELECT 1 FROM voting_event_choices WHERE event_id=? AND choice=?', (event_id, choice)).fetchone()
    if not event or event['status'] != 'open':
        conn.close(); flash('Voting is currently closed.', 'danger'); return redirect(url_for('vote_event', event_id=event_id))
    if not valid:
        conn.close(); flash('Please select a valid choice.', 'danger'); return redirect(url_for('vote_event', event_id=event_id))
    try:
        conn.execute('INSERT INTO voting_event_votes(event_id, username, choice) VALUES (?, ?, ?)', (event_id, session['username'], choice)); conn.commit(); flash('Your vote has been recorded.', 'success')
    except sqlite3.IntegrityError:
        flash('You have already voted in this ballot.', 'warning')
    finally:
        conn.close()
    return redirect(url_for('vote_event', event_id=event_id))

@app.route('/admin/voting/<int:event_id>')
def admin_voting_results(event_id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    conn = get_db(); event = conn.execute('SELECT * FROM voting_events WHERE id=?', (event_id,)).fetchone()
    if not event:
        conn.close(); return 'Voting event not found.', 404
    tally = conn.execute("SELECT c.choice, COUNT(v.id) AS cnt FROM voting_event_choices c LEFT JOIN voting_event_votes v ON v.event_id=c.event_id AND v.choice=c.choice WHERE c.event_id=? GROUP BY c.id, c.choice ORDER BY c.id", (event_id,)).fetchall()
    total = conn.execute('SELECT COUNT(*) AS cnt FROM voting_event_votes WHERE event_id=?', (event_id,)).fetchone()['cnt']; conn.close()
    return render_template('admin_voting_results.html', event=event, tally=tally, total=total)

# ── admin dashboard ───────────────────────────────────────────────────────────
def admin_required():
    return session.get('is_admin') is True


@app.route('/admin_dashboard', methods=['GET'])
def admin_dashboard():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('admin_login'))

    role        = load_role()
    voting_open = load_voting_status() == 'open'

    ensure_dynamic_rsvp_tables()
    conn = get_db()
    events = conn.execute("""
        SELECT e.*,
               SUM(CASE WHEN r.attending='Yes' THEN 1 ELSE 0 END) AS yes_count,
               SUM(CASE WHEN r.attending='No' THEN 1 ELSE 0 END) AS no_count
        FROM rsvp_events e
        LEFT JOIN rsvp_responses r ON r.event_id=e.id
        GROUP BY e.id
        ORDER BY e.created_at DESC
    """).fetchall()
    voting_events = conn.execute("SELECT ve.*, COUNT(v.id) AS vote_count FROM voting_events ve LEFT JOIN voting_event_votes v ON v.event_id=ve.id GROUP BY ve.id ORDER BY ve.created_at DESC").fetchall()
    election_sessions = conn.execute("SELECT * FROM election_sessions ORDER BY id DESC").fetchall()
    election_phases = conn.execute("SELECT p.*,COUNT(v.id) vote_count FROM election_phases p LEFT JOIN election_voter_status v ON v.phase_id=p.id GROUP BY p.id ORDER BY p.id").fetchall()
    registered_voter_count = conn.execute("SELECT COUNT(*) cnt FROM users").fetchone()['cnt']
    conn.close()

    return render_template(
        'admin_dashboard.html',
        role=role,
        voting_open=voting_open,
        events=events,
        voting_events=voting_events,
        election_sessions=election_sessions,
        election_phases=election_phases,
        registered_voter_count=registered_voter_count,
        created=request.args.get('created', type=int),
        vote_created=request.args.get('vote_created', type=int)
    )


@app.route('/toggle_voting', methods=['POST'])
def toggle_voting():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    current    = load_voting_status()
    new_status = 'closed' if current == 'open' else 'open'

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('voting_status', ?)",
        (new_status,)
    )
    conn.commit()
    conn.close()

    if new_status == 'open':
        flash("Voting is now open. Voters can cast their ballots.", "success")
    else:
        flash("Voting is now closed. Tally is visible to all voters.", "success")

    return redirect(url_for('admin_dashboard'))


@app.route('/update_role', methods=['POST'])
def update_role():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    if load_voting_status() == 'open':
        flash("Close voting before changing the role.", "danger")
        return redirect(url_for('admin_dashboard'))

    new_role = request.form.get('new_role', '').strip()
    if not new_role:
        flash("Role cannot be empty.", "danger")
        return redirect(url_for('admin_dashboard'))

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('current_role', ?)",
        (new_role,)
    )
    conn.commit()
    conn.close()

    with open(role_file, 'w') as f:
        f.write(new_role)

    flash(f"Role updated to '{new_role}'!", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/update_choices', methods=['POST'])
def update_choices():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    if load_voting_status() == 'open':
        flash("Close voting before changing choices.", "danger")
        return redirect(url_for('admin_dashboard'))

    role = load_role()
    if not role:
        flash("Set a role first before adding choices.", "warning")
        return redirect(url_for('admin_dashboard'))

    raw         = request.form.get('choices', '')
    new_choices = [c.strip() for c in raw.splitlines() if c.strip()]

    try:
        conn = get_db()
        conn.execute("DELETE FROM choices WHERE role=?", (role,))
        conn.executemany(
            "INSERT OR IGNORE INTO choices (role, choice) VALUES (?, ?)",
            [(role, c) for c in new_choices]
        )
        conn.commit()
        conn.close()
        flash("Choices updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating choices: {e}", "danger")

    return redirect(url_for('admin_dashboard'))


@app.route('/view_choices', methods=['GET'])
def view_choices():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    role = load_role()
    conn = get_db()
    rows = conn.execute("SELECT choice FROM choices WHERE role=?", (role,)).fetchall() if role else []
    conn.close()
    choices = [r['choice'] for r in rows]
    return render_template('view_choices.html', choices=choices)


@app.route('/generate_tally', methods=['GET', 'POST'])
def generate_tally():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    role = load_role()
    if not role:
        flash("No role is currently set.", "warning")
        return redirect(url_for('admin_dashboard'))

    conn = get_db()
    rows = conn.execute(
        "SELECT choice, COUNT(*) as cnt FROM votes WHERE role=? GROUP BY choice",
        (role,)
    ).fetchall()
    conn.close()
    tally = {r['choice']: r['cnt'] for r in rows}
    return render_template('tally.html', role=role, tally=tally)

# ── admin: announcements ────────────────────────────────────────────────────
@app.route('/admin/announcements')
def admin_announcements():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))
    conn = get_db()
    rows = conn.execute("SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template('admin_announcements.html', announcements=rows)


@app.route('/admin/announcements/create', methods=['POST'])
def create_announcement():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    title = request.form.get('title', '').strip()
    body  = request.form.get('body', '').strip()
    if not title or not body:
        flash("Title and message are required.", "danger")
        return redirect(url_for('admin_announcements'))

    image_path = save_uploaded_image(request.files.get('image'), 'announcements')

    conn = get_db()
    conn.execute(
        "INSERT INTO announcements (title, body, image_path) VALUES (?, ?, ?)",
        (title, body, image_path)
    )
    conn.commit()
    conn.close()

    result = send_push_to_all(DB_FILE, title=f"📢 {title}", body=body[:120], url='/announcements')
    if result.get('skipped'):
        flash("Announcement posted! (Push notifications aren't configured yet.)", "success")
    else:
        flash(f"Announcement posted and pushed to {result['sent']} device(s).", "success")

    return redirect(url_for('admin_announcements'))


@app.route('/admin/announcements/delete/<int:announcement_id>', methods=['POST'])
def delete_announcement(announcement_id):
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))
    conn = get_db()
    conn.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))
    conn.commit()
    conn.close()
    flash("Announcement deleted.", "success")
    return redirect(url_for('admin_announcements'))

# ── admin: events ────────────────────────────────────────────────────────────
@app.route('/admin/events')
def admin_events():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))
    conn = get_db()
    rows = conn.execute("SELECT * FROM events ORDER BY event_date DESC").fetchall()
    conn.close()
    return render_template('admin_events.html', events=rows)


@app.route('/admin/events/create', methods=['POST'])
def create_event():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    title       = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    location    = request.form.get('location', '').strip()
    event_date  = request.form.get('event_date', '').strip()
    event_time  = request.form.get('event_time', '').strip()

    if not title or not event_date:
        flash("Title and date are required.", "danger")
        return redirect(url_for('admin_events'))

    image_path = save_uploaded_image(request.files.get('image'), 'events')

    conn = get_db()
    conn.execute(
        """INSERT INTO events (title, description, location, event_date, event_time, image_path)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title, description, location, event_date, event_time, image_path)
    )
    conn.commit()
    conn.close()

    when = f"{event_date}" + (f" at {event_time}" if event_time else "")
    push_body = f"{when}" + (f" — {location}" if location else "")
    result = send_push_to_all(DB_FILE, title=f"📅 {title}", body=push_body[:120], url='/events')
    if result.get('skipped'):
        flash("Event posted! (Push notifications aren't configured yet.)", "success")
    else:
        flash(f"Event posted and pushed to {result['sent']} device(s).", "success")

    return redirect(url_for('admin_events'))


@app.route('/admin/events/delete/<int:event_id>', methods=['POST'])
def delete_event(event_id):
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))
    conn = get_db()
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    flash("Event deleted.", "success")
    return redirect(url_for('admin_events'))

# ── admin: gallery ───────────────────────────────────────────────────────────
@app.route('/admin/gallery')
def admin_gallery():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))
    conn = get_db()
    rows = conn.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template('admin_gallery.html', photos=rows)


@app.route('/admin/gallery/upload', methods=['POST'])
def upload_gallery_photo():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    caption = request.form.get('caption', '').strip()
    files   = request.files.getlist('images')

    if not files or all(f.filename == '' for f in files):
        flash("Please choose at least one photo.", "danger")
        return redirect(url_for('admin_gallery'))

    conn   = get_db()
    added  = 0
    for f in files:
        image_path = save_uploaded_image(f, 'gallery')
        if image_path:
            conn.execute(
                "INSERT INTO gallery (caption, image_path) VALUES (?, ?)",
                (caption, image_path)
            )
            added += 1
    conn.commit()
    conn.close()

    if added:
        flash(f"{added} photo(s) added to the gallery.", "success")
    return redirect(url_for('admin_gallery'))


@app.route('/admin/gallery/delete/<int:photo_id>', methods=['POST'])
def delete_gallery_photo(photo_id):
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))
    conn = get_db()
    conn.execute("DELETE FROM gallery WHERE id=?", (photo_id,))
    conn.commit()
    conn.close()
    flash("Photo removed.", "success")
    return redirect(url_for('admin_gallery'))

# ── voter management ──────────────────────────────────────────────────────────
@app.route('/enter_voters', methods=['POST'])
def enter_voters():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    raw    = request.form.get('phone_numbers', '')
    phones = [p.strip() for p in raw.splitlines() if p.strip()]

    if not phones:
        flash("Please enter at least one phone number.", "danger")
        return redirect(url_for('admin_dashboard'))

    try:
        conn    = get_db()
        added   = 0
        skipped = 0
        for p in phones:
            try:
                conn.execute("INSERT INTO users (phone_number) VALUES (?)", (p,))
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
        conn.close()

        msg = f"{added} voter(s) added."
        if skipped:
            msg += f" {skipped} duplicate(s) skipped."
        flash(msg, "success")

    except Exception as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for('admin_dashboard'))


@app.route('/view_usernames')
def view_usernames():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    conn      = get_db()
    rows      = conn.execute("SELECT phone_number FROM users").fetchall()
    conn.close()
    usernames = [r['phone_number'] for r in rows]
    return render_template('view_usernames.html', usernames=usernames)


@app.route('/delete_all_voters', methods=['POST'])
def delete_all_voters():
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    conn = get_db()
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    flash("All voters deleted.", "success")
    return redirect(url_for('view_usernames'))


@app.route('/delete_voter/<username>', methods=['POST'])
def delete_voter(username):
    if not admin_required():
        flash("Access restricted to admin only.", "danger")
        return redirect(url_for('index'))

    conn   = get_db()
    result = conn.execute("DELETE FROM users WHERE phone_number=?", (username,))
    conn.commit()
    conn.close()

    if result.rowcount:
        flash(f"Voter {username} removed.", "success")
    else:
        flash(f"Voter {username} not found.", "warning")

    return redirect(url_for('view_usernames'))


@app.route('/download_voters_pdf')
def download_voters_pdf():
    file_path = os.path.join('static', 'voters_list.pdf')
    if not os.path.exists(file_path):
        flash("Voters list PDF not found.", "danger")
        return redirect(url_for('admin_dashboard'))
    return send_file(file_path, as_attachment=True)

# ── document helpers ──────────────────────────────────────────────────────────
def create_word_document(usernames, output_file='static/voters_list.docx'):
    doc = Document()
    doc.add_heading('Voters List', level=1)
    for u in usernames:
        doc.add_paragraph(u)
    doc.save(output_file)


def generate_pdf(usernames, output_file='static/voters_list.pdf'):
    os.makedirs('static', exist_ok=True)
    c            = canvas.Canvas(output_file, pagesize=letter)
    width, height = letter
    margin        = 50
    column_width  = (width - 3 * margin) / 2
    label_height  = 50
    font_size     = 12
    max_per_col   = 10

    c.setFont("Helvetica", font_size)
    left_col  = usernames[:max_per_col]
    right_col = usernames[max_per_col:max_per_col * 2]
    y_left    = height - margin - label_height
    y_right   = height - margin - label_height

    for username in left_col:
        c.setStrokeColor(colors.black)
        c.setFillColor(colors.white)
        c.rect(margin, y_left - label_height, column_width, label_height, fill=1)
        c.setFillColor(colors.black)
        c.drawString(margin + 10, y_left - label_height + 15, username)
        y_left -= label_height + 5

    for username in right_col:
        c.setStrokeColor(colors.black)
        c.setFillColor(colors.white)
        c.rect(margin + column_width + margin, y_right - label_height, column_width, label_height, fill=1)
        c.setFillColor(colors.black)
        c.drawString(margin + column_width + margin + 10, y_right - label_height + 15, username)
        y_right -= label_height + 5

    c.save()

# ── entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)
