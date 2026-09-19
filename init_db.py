import os
import sqlite3

def create_tables(db_file):
    os.makedirs(os.path.dirname(os.path.abspath(db_file)), exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS choices (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, choice TEXT NOT NULL, UNIQUE(role, choice));
    CREATE TABLE IF NOT EXISTS votes (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, role TEXT NOT NULL, choice TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(username, role));
    CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS rsvps (id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT UNIQUE NOT NULL, attending INTEGER NOT NULL DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS rsvp_events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, event_date TEXT NOT NULL, event_time TEXT NOT NULL, active INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS rsvp_responses (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, first_name TEXT NOT NULL, attending TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(event_id) REFERENCES rsvp_events(id));
    CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL, image_path TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, location TEXT, event_date TEXT NOT NULL, event_time TEXT, image_path TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS gallery (id INTEGER PRIMARY KEY AUTOINCREMENT, caption TEXT, image_path TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS push_subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT UNIQUE NOT NULL, subscription_json TEXT NOT NULL, username TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS voting_events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, question TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'closed', active INTEGER NOT NULL DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS voting_event_choices (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, choice TEXT NOT NULL, UNIQUE(event_id, choice), FOREIGN KEY(event_id) REFERENCES voting_events(id));
    CREATE TABLE IF NOT EXISTS voting_event_votes (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, username TEXT NOT NULL, choice TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(event_id, username), FOREIGN KEY(event_id) REFERENCES voting_events(id));
    ''')
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('voting_status', 'closed')")
    conn.commit(); conn.close()

def migrate_files_to_db(db_file, role_file, choices_file, votes_file):
    conn = sqlite3.connect(db_file)
    try:
        if role_file and os.path.exists(role_file):
            role = open(role_file, encoding='utf-8').read().strip()
            if role:
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('current_role', ?)", (role,))
        conn.commit()
    finally:
        conn.close()
