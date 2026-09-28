import os
import sqlite3
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

sunday_school = Blueprint("sunday_school", __name__, url_prefix="/sunday-school")

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_FILE = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "sfcd.db"))


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_sunday_school():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sunday_school_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            email TEXT,
            phone TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('director','teacher')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sunday_school_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            grade TEXT,
            school_year TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, school_year)
        );

        CREATE TABLE IF NOT EXISTS sunday_school_teacher_classes (
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (teacher_id, class_id),
            FOREIGN KEY (teacher_id) REFERENCES sunday_school_users(id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES sunday_school_classes(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


initialize_sunday_school()


def director_required(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if session.get("ss_user_id") is None or session.get("ss_role") != "director":
            flash("Please log in as Sunday School Director.", "warning")
            return redirect(url_for("sunday_school.login"))
        return func(*args, **kwargs)
    return wrapped


@sunday_school.route("/")
def home():
    if session.get("ss_role") == "director":
        return redirect(url_for("sunday_school.dashboard"))
    return redirect(url_for("sunday_school.login"))


@sunday_school.route("/setup", methods=["GET", "POST"])
def setup():
    conn = get_db()
    director = conn.execute("SELECT id FROM sunday_school_users WHERE role='director' LIMIT 1").fetchone()
    conn.close()

    if director:
        flash("Sunday School Director account already exists.", "warning")
        return redirect(url_for("sunday_school.login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not name or not username or not password:
            flash("Name, username and password are required.", "danger")
            return redirect(url_for("sunday_school.setup"))
        if len(username) < 4:
            flash("Username must contain at least 4 characters.", "danger")
            return redirect(url_for("sunday_school.setup"))
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return redirect(url_for("sunday_school.setup"))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("sunday_school.setup"))

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO sunday_school_users(name,username,email,password_hash,role) VALUES(?,?,?,?,'director')",
                (name, username, email, generate_password_hash(password)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("That username already exists.", "danger")
            return redirect(url_for("sunday_school.setup"))
        finally:
            conn.close()

        flash("Sunday School Director account created. Please log in.", "success")
        return redirect(url_for("sunday_school.login"))

    return render_template("sunday_school/setup.html")


@sunday_school.route("/login", methods=["GET", "POST"])
def login():
    if session.get("ss_user_id") and session.get("ss_role") == "director":
        return redirect(url_for("sunday_school.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        director = conn.execute(
            "SELECT * FROM sunday_school_users WHERE username=? AND role='director' AND active=1",
            (username,),
        ).fetchone()
        conn.close()

        if director and check_password_hash(director["password_hash"], password):
            session["ss_user_id"] = director["id"]
            session["ss_role"] = "director"
            session["ss_name"] = director["name"]
            return redirect(url_for("sunday_school.dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("sunday_school/login.html")


@sunday_school.route("/logout")
def logout():
    for key in ("ss_user_id", "ss_role", "ss_name"):
        session.pop(key, None)
    flash("You have been logged out.", "success")
    return redirect(url_for("sunday_school.login"))


@sunday_school.route("/director")
@director_required
def dashboard():
    conn = get_db()
    classes = conn.execute(
        "SELECT * FROM sunday_school_classes ORDER BY active DESC, name COLLATE NOCASE"
    ).fetchall()
    teachers = conn.execute(
        """SELECT u.*,
                  GROUP_CONCAT(c.name, ', ') AS class_names
           FROM sunday_school_users u
           LEFT JOIN sunday_school_teacher_classes tc ON tc.teacher_id=u.id
           LEFT JOIN sunday_school_classes c ON c.id=tc.class_id
           WHERE u.role='teacher'
           GROUP BY u.id
           ORDER BY u.active DESC, u.name COLLATE NOCASE"""
    ).fetchall()
    conn.close()
    return render_template("sunday_school/dashboard.html", classes=classes, teachers=teachers)


@sunday_school.route("/director/classes/create", methods=["POST"])
@director_required
def create_class():
    name = request.form.get("name", "").strip()
    grade = request.form.get("grade", "").strip()
    school_year = request.form.get("school_year", "").strip()
    if not name or not school_year:
        flash("Class name and school year are required.", "danger")
        return redirect(url_for("sunday_school.dashboard"))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO sunday_school_classes(name,grade,school_year) VALUES(?,?,?)",
            (name, grade, school_year),
        )
        conn.commit()
        flash(f"{name} created successfully.", "success")
    except sqlite3.IntegrityError:
        flash("That class already exists for this school year.", "danger")
    finally:
        conn.close()
    return redirect(url_for("sunday_school.dashboard"))


@sunday_school.route("/director/classes/<int:class_id>/toggle", methods=["POST"])
@director_required
def toggle_class(class_id):
    conn = get_db()
    conn.execute(
        "UPDATE sunday_school_classes SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
        (class_id,),
    )
    conn.commit()
    conn.close()
    flash("Class status updated.", "success")
    return redirect(url_for("sunday_school.dashboard"))


@sunday_school.route("/director/teachers/create", methods=["POST"])
@director_required
def create_teacher():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "")
    class_ids = request.form.getlist("class_ids")

    if not name or not username or not password:
        flash("Teacher name, username and temporary password are required.", "danger")
        return redirect(url_for("sunday_school.dashboard"))
    if len(username) < 4:
        flash("Teacher username must contain at least 4 characters.", "danger")
        return redirect(url_for("sunday_school.dashboard"))
    if len(password) < 8:
        flash("Temporary password must contain at least 8 characters.", "danger")
        return redirect(url_for("sunday_school.dashboard"))

    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO sunday_school_users
               (name,username,email,phone,password_hash,role)
               VALUES(?,?,?,?,?,'teacher')""",
            (name, username, email, phone, generate_password_hash(password)),
        )
        teacher_id = cursor.lastrowid
        for class_id in class_ids:
            conn.execute(
                "INSERT OR IGNORE INTO sunday_school_teacher_classes(teacher_id,class_id) VALUES(?,?)",
                (teacher_id, class_id),
            )
        conn.commit()
        flash(f"Teacher profile created for {name}.", "success")
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("That teacher username is already in use.", "danger")
    finally:
        conn.close()

    return redirect(url_for("sunday_school.dashboard"))


@sunday_school.route("/director/teachers/<int:teacher_id>/toggle", methods=["POST"])
@director_required
def toggle_teacher(teacher_id):
    conn = get_db()
    conn.execute(
        """UPDATE sunday_school_users
           SET active=CASE active WHEN 1 THEN 0 ELSE 1 END
           WHERE id=? AND role='teacher'""",
        (teacher_id,),
    )
    conn.commit()
    conn.close()
    flash("Teacher status updated.", "success")
    return redirect(url_for("sunday_school.dashboard"))


@sunday_school.route("/director/teachers/<int:teacher_id>/assign", methods=["POST"])
@director_required
def update_teacher_classes(teacher_id):
    class_ids = request.form.getlist("class_ids")
    conn = get_db()
    teacher = conn.execute(
        "SELECT id FROM sunday_school_users WHERE id=? AND role='teacher'",
        (teacher_id,),
    ).fetchone()

    if not teacher:
        conn.close()
        flash("Teacher not found.", "danger")
        return redirect(url_for("sunday_school.dashboard"))

    conn.execute("DELETE FROM sunday_school_teacher_classes WHERE teacher_id=?", (teacher_id,))
    for class_id in class_ids:
        conn.execute(
            "INSERT OR IGNORE INTO sunday_school_teacher_classes(teacher_id,class_id) VALUES(?,?)",
            (teacher_id, class_id),
        )
    conn.commit()
    conn.close()
    flash("Teacher class assignments updated.", "success")
    return redirect(url_for("sunday_school.dashboard"))


@sunday_school.route("/director/teachers/<int:teacher_id>/password", methods=["POST"])
@director_required
def reset_teacher_password(teacher_id):
    password = request.form.get("password", "")
    if len(password) < 8:
        flash("New temporary password must contain at least 8 characters.", "danger")
        return redirect(url_for("sunday_school.dashboard"))

    conn = get_db()
    conn.execute(
        """UPDATE sunday_school_users SET password_hash=?
           WHERE id=? AND role='teacher'""",
        (generate_password_hash(password), teacher_id),
    )
    conn.commit()
    conn.close()
    flash("Teacher password reset.", "success")
    return redirect(url_for("sunday_school.dashboard"))
