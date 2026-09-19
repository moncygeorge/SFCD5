import json, os, sqlite3
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_CLAIMS_EMAIL = os.environ.get('VAPID_CLAIMS_EMAIL', '')
def push_configured(): return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and VAPID_CLAIMS_EMAIL)
def save_subscription(db_file, subscription, username=None):
    endpoint=(subscription or {}).get('endpoint')
    if not endpoint: return False
    conn=sqlite3.connect(db_file)
    conn.execute('CREATE TABLE IF NOT EXISTS push_subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT UNIQUE NOT NULL, subscription_json TEXT NOT NULL, username TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
    conn.execute('INSERT INTO push_subscriptions(endpoint, subscription_json, username) VALUES (?,?,?) ON CONFLICT(endpoint) DO UPDATE SET subscription_json=excluded.subscription_json, username=excluded.username',(endpoint,json.dumps(subscription),username))
    conn.commit(); conn.close(); return True
def send_push_to_all(db_file, title, body, url='/'):
    if not push_configured(): return {'skipped':True,'sent':0,'failed':0}
    try: from pywebpush import webpush
    except Exception: return {'skipped':True,'sent':0,'failed':0}
    conn=sqlite3.connect(db_file); rows=conn.execute('SELECT subscription_json FROM push_subscriptions').fetchall(); conn.close()
    sent=failed=0; payload=json.dumps({'title':title,'body':body,'url':url})
    for (raw,) in rows:
        try:
            webpush(json.loads(raw),payload,vapid_private_key=VAPID_PRIVATE_KEY,vapid_claims={'sub':'mailto:'+VAPID_CLAIMS_EMAIL}); sent+=1
        except Exception: failed+=1
    return {'skipped':False,'sent':sent,'failed':failed}
