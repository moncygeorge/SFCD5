import os, sqlite3
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
sunday_school=Blueprint('sunday_school',__name__,url_prefix='/sunday-school')
DATA_DIR=os.environ.get('DATA_DIR',os.path.join(os.path.dirname(os.path.abspath(__file__)),'data'))
DB_FILE=os.environ.get('DB_PATH',os.path.join(DATA_DIR,'sfcd.db'))
def get_db():
 c=sqlite3.connect(DB_FILE,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA busy_timeout=15000'); c.execute('PRAGMA foreign_keys=ON'); return c
def initialize_sunday_school():
 c=get_db(); c.executescript("""CREATE TABLE IF NOT EXISTS sunday_school_users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,username TEXT NOT NULL UNIQUE COLLATE NOCASE,email TEXT,phone TEXT,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('director','teacher')),active INTEGER NOT NULL DEFAULT 1,created_at DATETIME DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS sunday_school_classes(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,grade TEXT,school_year TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,UNIQUE(name,school_year));"""); c.commit(); c.close()
initialize_sunday_school()
def director_required(f):
 @wraps(f)
 def w(*a,**k):
  if session.get('ss_user_id') is None or session.get('ss_role')!='director': flash('Please log in as Sunday School Director.','warning'); return redirect(url_for('sunday_school.login'))
  return f(*a,**k)
 return w
@sunday_school.route('/')
def home(): return redirect(url_for('sunday_school.dashboard' if session.get('ss_role')=='director' else 'sunday_school.login'))
@sunday_school.route('/setup',methods=['GET','POST'])
def setup():
 c=get_db(); d=c.execute("SELECT id FROM sunday_school_users WHERE role='director' LIMIT 1").fetchone(); c.close()
 if d: flash('Sunday School Director account already exists.','warning'); return redirect(url_for('sunday_school.login'))
 if request.method=='POST':
  n=request.form.get('name','').strip(); u=request.form.get('username','').strip(); e=request.form.get('email','').strip(); p=request.form.get('password',''); q=request.form.get('confirm','')
  if not n or not u or not p: flash('Name, username and password are required.','danger'); return redirect(url_for('sunday_school.setup'))
  if len(u)<4: flash('Username must contain at least 4 characters.','danger'); return redirect(url_for('sunday_school.setup'))
  if len(p)<8: flash('Password must contain at least 8 characters.','danger'); return redirect(url_for('sunday_school.setup'))
  if p!=q: flash('Passwords do not match.','danger'); return redirect(url_for('sunday_school.setup'))
  c=get_db()
  try: c.execute("INSERT INTO sunday_school_users(name,username,email,password_hash,role) VALUES(?,?,?,?,'director')",(n,u,e,generate_password_hash(p))); c.commit()
  except sqlite3.IntegrityError: flash('That username already exists.','danger'); return redirect(url_for('sunday_school.setup'))
  finally: c.close()
  flash('Sunday School Director account created. Please log in.','success'); return redirect(url_for('sunday_school.login'))
 return render_template('sunday_school/setup.html')
@sunday_school.route('/login',methods=['GET','POST'])
def login():
 if session.get('ss_user_id') and session.get('ss_role')=='director': return redirect(url_for('sunday_school.dashboard'))
 if request.method=='POST':
  u=request.form.get('username','').strip(); p=request.form.get('password',''); c=get_db(); d=c.execute("SELECT * FROM sunday_school_users WHERE username=? AND role='director' AND active=1",(u,)).fetchone(); c.close()
  if d and check_password_hash(d['password_hash'],p): session['ss_user_id']=d['id']; session['ss_role']='director'; session['ss_name']=d['name']; return redirect(url_for('sunday_school.dashboard'))
  flash('Invalid username or password.','danger')
 return render_template('sunday_school/login.html')
@sunday_school.route('/logout')
def logout():
 for x in ('ss_user_id','ss_role','ss_name'): session.pop(x,None)
 flash('You have been logged out.','success'); return redirect(url_for('sunday_school.login'))
@sunday_school.route('/director')
@director_required
def dashboard():
 c=get_db(); rows=c.execute('SELECT * FROM sunday_school_classes ORDER BY active DESC,name COLLATE NOCASE').fetchall(); c.close(); return render_template('sunday_school/dashboard.html',classes=rows)
@sunday_school.route('/director/classes/create',methods=['POST'])
@director_required
def create_class():
 n=request.form.get('name','').strip(); g=request.form.get('grade','').strip(); y=request.form.get('school_year','').strip()
 if not n or not y: flash('Class name and school year are required.','danger'); return redirect(url_for('sunday_school.dashboard'))
 c=get_db()
 try: c.execute('INSERT INTO sunday_school_classes(name,grade,school_year) VALUES(?,?,?)',(n,g,y)); c.commit(); flash(f'{n} created successfully.','success')
 except sqlite3.IntegrityError: flash('That class already exists for this school year.','danger')
 finally: c.close()
 return redirect(url_for('sunday_school.dashboard'))
@sunday_school.route('/director/classes/<int:class_id>/toggle',methods=['POST'])
@director_required
def toggle_class(class_id):
 c=get_db(); c.execute('UPDATE sunday_school_classes SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(class_id,)); c.commit(); c.close(); flash('Class status updated.','success'); return redirect(url_for('sunday_school.dashboard'))
