import os
import sqlite3
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

sunday_school = Blueprint("sunday_school", __name__, url_prefix="/sunday-school")

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_FILE = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "sfcd.db"))

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_VERIFY_SERVICE_SID = os.environ.get("TWILIO_VERIFY_SERVICE_SID", "").strip()

def normalize_us_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return "+1" + digits

def twilio_verify_client():
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_VERIFY_SERVICE_SID):
        raise RuntimeError("Twilio Verify is not configured.")
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


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

        CREATE TABLE IF NOT EXISTS sunday_school_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            instructions TEXT,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (class_id) REFERENCES sunday_school_classes(id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES sunday_school_users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sunday_school_quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            question_order INTEGER NOT NULL,
            question_type TEXT NOT NULL DEFAULT 'mcq' CHECK(question_type IN ('mcq','true_false')),
            question_text TEXT NOT NULL,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            correct_answer TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 1 CHECK(points > 0),
            FOREIGN KEY (quiz_id) REFERENCES sunday_school_quizzes(id) ON DELETE CASCADE,
            UNIQUE(quiz_id, question_order)
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


def teacher_required(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if session.get("ss_user_id") is None or session.get("ss_role") != "teacher":
            flash("Please log in as a Sunday School Teacher.", "warning")
            return redirect(url_for("sunday_school.teacher_login"))
        return func(*args, **kwargs)
    return wrapped


@sunday_school.route("/")
def home():
    if session.get("ss_role") == "director":
        return redirect(url_for("sunday_school.dashboard"))
    if session.get("ss_role") == "teacher":
        return redirect(url_for("sunday_school.teacher_dashboard"))
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
    if len(class_ids) > 1:
        flash("Each teacher can be assigned to only one class.", "danger")
        return redirect(url_for("sunday_school.dashboard"))

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
    if len(class_ids) > 1:
        flash("Each teacher can be assigned to only one class.", "danger")
        return redirect(url_for("sunday_school.dashboard"))
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


@sunday_school.route("/director/change-password", methods=["GET", "POST"])
@director_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            flash("New password must contain at least 8 characters.", "danger")
            return redirect(url_for("sunday_school.change_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("sunday_school.change_password"))

        conn = get_db()
        director = conn.execute(
            """SELECT id, password_hash
               FROM sunday_school_users
               WHERE id=? AND role='director' AND active=1""",
            (session.get("ss_user_id"),),
        ).fetchone()

        if not director:
            conn.close()
            session.clear()
            flash("Director account was not found. Please log in again.", "danger")
            return redirect(url_for("sunday_school.login"))

        if not check_password_hash(director["password_hash"], current_password):
            conn.close()
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("sunday_school.change_password"))

        conn.execute(
            "UPDATE sunday_school_users SET password_hash=? WHERE id=? AND role='director'",
            (generate_password_hash(new_password), director["id"]),
        )
        conn.commit()
        conn.close()

        flash("Password changed successfully.", "success")
        return redirect(url_for("sunday_school.dashboard"))

    return render_template("sunday_school/change_password.html")


@sunday_school.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()

        # Always show the same outward message so account existence is not revealed.
        generic_message = "If the account information is valid, a verification code has been sent."

        conn = get_db()
        user = conn.execute(
            """SELECT id, username, phone
               FROM sunday_school_users
               WHERE username=? AND role='director' AND active=1""",
            (username,),
        ).fetchone()
        conn.close()

        if user:
            phone = normalize_us_phone(user["phone"])
            if phone:
                try:
                    client = twilio_verify_client()
                    client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verifications.create(
                        to=phone,
                        channel="sms",
                    )
                    session["ss_reset_user_id"] = user["id"]
                    session["ss_reset_username"] = user["username"]
                    flash(generic_message, "success")
                    return redirect(url_for("sunday_school.verify_reset_code"))
                except (TwilioRestException, RuntimeError):
                    # Do not expose provider details on the public page.
                    flash("Password recovery is temporarily unavailable. Please contact the site administrator.", "danger")
                    return redirect(url_for("sunday_school.forgot_password"))

        # Generic response even when username/phone doesn't match.
        flash(generic_message, "success")
        return render_template("sunday_school/forgot_password.html", submitted=True)

    return render_template("sunday_school/forgot_password.html", submitted=False)


@sunday_school.route("/forgot-password/verify", methods=["GET", "POST"])
def verify_reset_code():
    user_id = session.get("ss_reset_user_id")
    username = session.get("ss_reset_username")

    if not user_id or not username:
        flash("Start password recovery again.", "warning")
        return redirect(url_for("sunday_school.forgot_password"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        conn = get_db()
        user = conn.execute(
            """SELECT id, username, phone
               FROM sunday_school_users
               WHERE id=? AND username=? AND role='director' AND active=1""",
            (user_id, username),
        ).fetchone()
        conn.close()

        if not user:
            session.pop("ss_reset_user_id", None)
            session.pop("ss_reset_username", None)
            flash("Password recovery session is no longer valid.", "danger")
            return redirect(url_for("sunday_school.forgot_password"))

        phone = normalize_us_phone(user["phone"])
        if not phone:
            flash("Password recovery is temporarily unavailable. Please contact the site administrator.", "danger")
            return redirect(url_for("sunday_school.forgot_password"))

        try:
            client = twilio_verify_client()
            check = client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verification_checks.create(
                to=phone,
                code=code,
            )
        except (TwilioRestException, RuntimeError):
            flash("The code could not be verified. Please try again.", "danger")
            return redirect(url_for("sunday_school.verify_reset_code"))

        if check.status == "approved":
            session["ss_reset_verified"] = True
            return redirect(url_for("sunday_school.reset_password"))

        flash("Invalid or expired verification code.", "danger")

    return render_template("sunday_school/verify_reset_code.html")


@sunday_school.route("/forgot-password/reset", methods=["GET", "POST"])
def reset_password():
    user_id = session.get("ss_reset_user_id")
    username = session.get("ss_reset_username")
    verified = session.get("ss_reset_verified")

    if not user_id or not username or not verified:
        flash("Verify your recovery code first.", "warning")
        return redirect(url_for("sunday_school.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            flash("New password must contain at least 8 characters.", "danger")
            return redirect(url_for("sunday_school.reset_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("sunday_school.reset_password"))

        conn = get_db()
        conn.execute(
            """UPDATE sunday_school_users
               SET password_hash=?
               WHERE id=? AND username=? AND role='director' AND active=1""",
            (generate_password_hash(new_password), user_id, username),
        )
        conn.commit()
        conn.close()

        for key in ("ss_reset_user_id", "ss_reset_username", "ss_reset_verified"):
            session.pop(key, None)

        flash("Password reset successfully. Please log in.", "success")
        return redirect(url_for("sunday_school.login"))

    return render_template("sunday_school/reset_password.html")


@sunday_school.route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    if session.get("ss_user_id") and session.get("ss_role") == "teacher":
        return redirect(url_for("sunday_school.teacher_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        teacher = conn.execute(
            """SELECT id, name, username, password_hash
               FROM sunday_school_users
               WHERE username=? AND role='teacher' AND active=1""",
            (username,),
        ).fetchone()
        conn.close()

        if teacher and check_password_hash(teacher["password_hash"], password):
            # Clear any Director/recovery state before creating the teacher session.
            session.clear()
            session["ss_user_id"] = teacher["id"]
            session["ss_role"] = "teacher"
            session["ss_name"] = teacher["name"]
            return redirect(url_for("sunday_school.teacher_dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("sunday_school/teacher_login.html")


@sunday_school.route("/teacher")
@teacher_required
def teacher_dashboard():
    teacher_id = session.get("ss_user_id")

    conn = get_db()
    teacher = conn.execute(
        """SELECT id, name, username, email, phone
           FROM sunday_school_users
           WHERE id=? AND role='teacher' AND active=1""",
        (teacher_id,),
    ).fetchone()

    classes = conn.execute(
        """SELECT c.id, c.name, c.grade, c.school_year
           FROM sunday_school_classes c
           INNER JOIN sunday_school_teacher_classes tc ON tc.class_id=c.id
           WHERE tc.teacher_id=? AND c.active=1
           ORDER BY c.name COLLATE NOCASE""",
        (teacher_id,),
    ).fetchall()
    conn.close()

    if not teacher:
        session.clear()
        flash("Your teacher account is not active. Please contact the Sunday School Director.", "warning")
        return redirect(url_for("sunday_school.teacher_login"))

    return render_template(
        "sunday_school/teacher_dashboard.html",
        teacher=teacher,
        classes=classes,
    )


@sunday_school.route("/teacher/class/<int:class_id>")
@teacher_required
def teacher_class(class_id):
    teacher_id = session.get("ss_user_id")
    conn = get_db()
    class_row = conn.execute(
        """SELECT c.id, c.name, c.grade, c.school_year
           FROM sunday_school_classes c
           INNER JOIN sunday_school_teacher_classes tc ON tc.class_id=c.id
           WHERE c.id=? AND tc.teacher_id=? AND c.active=1""",
        (class_id, teacher_id),
    ).fetchone()
    conn.close()

    if not class_row:
        flash("You do not have access to that class.", "danger")
        return redirect(url_for("sunday_school.teacher_dashboard"))

    return render_template("sunday_school/teacher_class.html", class_row=class_row)


@sunday_school.route("/teacher/change-password", methods=["GET", "POST"])
@teacher_required
def teacher_change_password():
    teacher_id = session.get("ss_user_id")

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            flash("New password must contain at least 8 characters.", "danger")
            return redirect(url_for("sunday_school.teacher_change_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("sunday_school.teacher_change_password"))

        conn = get_db()
        teacher = conn.execute(
            """SELECT id, password_hash
               FROM sunday_school_users
               WHERE id=? AND role='teacher' AND active=1""",
            (teacher_id,),
        ).fetchone()

        if not teacher:
            conn.close()
            session.clear()
            flash("Teacher account not found. Please contact the Director.", "danger")
            return redirect(url_for("sunday_school.teacher_login"))

        if not check_password_hash(teacher["password_hash"], current_password):
            conn.close()
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("sunday_school.teacher_change_password"))

        conn.execute(
            """UPDATE sunday_school_users
               SET password_hash=?
               WHERE id=? AND role='teacher'""",
            (generate_password_hash(new_password), teacher_id),
        )
        conn.commit()
        conn.close()

        flash("Password changed successfully.", "success")
        return redirect(url_for("sunday_school.teacher_dashboard"))

    return render_template("sunday_school/teacher_change_password.html")


@sunday_school.route("/teacher/logout")
def teacher_logout():
    for key in ("ss_user_id", "ss_role", "ss_name"):
        session.pop(key, None)
    flash("You have been logged out.", "success")
    return redirect(url_for("sunday_school.teacher_login"))


def get_teacher_class(conn, teacher_id):
    return conn.execute(
        """SELECT c.id, c.name, c.grade, c.school_year
           FROM sunday_school_classes c
           INNER JOIN sunday_school_teacher_classes tc ON tc.class_id=c.id
           WHERE tc.teacher_id=? AND c.active=1
           ORDER BY c.id LIMIT 1""",
        (teacher_id,),
    ).fetchone()


def get_teacher_quiz(conn, quiz_id, teacher_id):
    return conn.execute(
        """SELECT q.*, c.name AS class_name
           FROM sunday_school_quizzes q
           INNER JOIN sunday_school_classes c ON c.id=q.class_id
           WHERE q.id=? AND q.teacher_id=?""",
        (quiz_id, teacher_id),
    ).fetchone()


@sunday_school.route("/teacher/quizzes")
@teacher_required
def teacher_quizzes():
    teacher_id = session.get("ss_user_id")
    conn = get_db()
    class_row = get_teacher_class(conn, teacher_id)
    quizzes = []
    if class_row:
        quizzes = conn.execute(
            """SELECT q.*,
                      COUNT(qq.id) AS question_count,
                      COALESCE(SUM(qq.points),0) AS total_points
               FROM sunday_school_quizzes q
               LEFT JOIN sunday_school_quiz_questions qq ON qq.quiz_id=q.id
               WHERE q.teacher_id=? AND q.class_id=?
               GROUP BY q.id
               ORDER BY q.updated_at DESC, q.id DESC""",
            (teacher_id, class_row["id"]),
        ).fetchall()
    conn.close()
    return render_template("sunday_school/teacher_quizzes.html",
                           class_row=class_row, quizzes=quizzes)


@sunday_school.route("/teacher/quizzes/create", methods=["GET","POST"])
@teacher_required
def create_quiz():
    teacher_id = session.get("ss_user_id")
    conn = get_db()
    class_row = get_teacher_class(conn, teacher_id)
    if not class_row:
        conn.close()
        flash("A class must be assigned to your teacher account before creating a quiz.", "danger")
        return redirect(url_for("sunday_school.teacher_dashboard"))

    if request.method == "POST":
        title = request.form.get("title","").strip()
        instructions = request.form.get("instructions","").strip()
        if not title:
            conn.close()
            flash("Quiz title is required.", "danger")
            return redirect(url_for("sunday_school.create_quiz"))
        cur = conn.execute(
            """INSERT INTO sunday_school_quizzes
               (class_id,teacher_id,title,instructions,status)
               VALUES(?,?,?,?,'draft')""",
            (class_row["id"], teacher_id, title, instructions),
        )
        conn.commit()
        quiz_id=cur.lastrowid
        conn.close()
        flash("Quiz created as a draft. Add questions next.", "success")
        return redirect(url_for("sunday_school.edit_quiz", quiz_id=quiz_id))

    conn.close()
    return render_template("sunday_school/create_quiz.html", class_row=class_row)


@sunday_school.route("/teacher/quizzes/<int:quiz_id>/edit")
@teacher_required
def edit_quiz(quiz_id):
    teacher_id=session.get("ss_user_id")
    conn=get_db()
    quiz=get_teacher_quiz(conn,quiz_id,teacher_id)
    if not quiz:
        conn.close()
        flash("Quiz not found or access denied.", "danger")
        return redirect(url_for("sunday_school.teacher_quizzes"))
    questions=conn.execute(
        """SELECT * FROM sunday_school_quiz_questions
           WHERE quiz_id=? ORDER BY question_order,id""",(quiz_id,)
    ).fetchall()
    conn.close()
    return render_template("sunday_school/edit_quiz.html",quiz=quiz,questions=questions)


@sunday_school.route("/teacher/quizzes/<int:quiz_id>/questions/add", methods=["POST"])
@teacher_required
def add_quiz_question(quiz_id):
    teacher_id=session.get("ss_user_id")
    conn=get_db()
    quiz=get_teacher_quiz(conn,quiz_id,teacher_id)
    if not quiz:
        conn.close()
        flash("Quiz not found or access denied.", "danger")
        return redirect(url_for("sunday_school.teacher_quizzes"))

    qtype=request.form.get("question_type","mcq")
    text=request.form.get("question_text","").strip()
    points=request.form.get("points","1").strip()
    try: points=int(points)
    except ValueError: points=0
    if not text or points < 1:
        conn.close()
        flash("Question text and positive points are required.", "danger")
        return redirect(url_for("sunday_school.edit_quiz",quiz_id=quiz_id))

    if qtype=="true_false":
        a,b,c,d="True","False",None,None
        correct=request.form.get("tf_correct","").strip()
        if correct not in ("A","B"):
            conn.close(); flash("Choose True or False as the correct answer.","danger")
            return redirect(url_for("sunday_school.edit_quiz",quiz_id=quiz_id))
    else:
        qtype="mcq"
        a=request.form.get("option_a","").strip()
        b=request.form.get("option_b","").strip()
        c=request.form.get("option_c","").strip()
        d=request.form.get("option_d","").strip()
        correct=request.form.get("mcq_correct","").strip()
        if not all((a,b,c,d)) or correct not in ("A","B","C","D"):
            conn.close(); flash("MCQ questions require all four choices and a correct answer.","danger")
            return redirect(url_for("sunday_school.edit_quiz",quiz_id=quiz_id))

    next_order=conn.execute(
        "SELECT COALESCE(MAX(question_order),0)+1 FROM sunday_school_quiz_questions WHERE quiz_id=?",
        (quiz_id,)
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO sunday_school_quiz_questions
           (quiz_id,question_order,question_type,question_text,option_a,option_b,option_c,option_d,correct_answer,points)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (quiz_id,next_order,qtype,text,a,b,c,d,correct,points)
    )
    conn.execute("UPDATE sunday_school_quizzes SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(quiz_id,))
    conn.commit(); conn.close()
    flash("Question added.","success")
    return redirect(url_for("sunday_school.edit_quiz",quiz_id=quiz_id))


@sunday_school.route("/teacher/quizzes/<int:quiz_id>/questions/<int:question_id>/delete", methods=["POST"])
@teacher_required
def delete_quiz_question(quiz_id,question_id):
    teacher_id=session.get("ss_user_id")
    conn=get_db()
    quiz=get_teacher_quiz(conn,quiz_id,teacher_id)
    if quiz:
        conn.execute("DELETE FROM sunday_school_quiz_questions WHERE id=? AND quiz_id=?",(question_id,quiz_id))
        rows=conn.execute("SELECT id FROM sunday_school_quiz_questions WHERE quiz_id=? ORDER BY question_order,id",(quiz_id,)).fetchall()
        for i,row in enumerate(rows,1):
            conn.execute("UPDATE sunday_school_quiz_questions SET question_order=? WHERE id=?",(i,row["id"]))
        conn.execute("UPDATE sunday_school_quizzes SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(quiz_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("sunday_school.edit_quiz",quiz_id=quiz_id))


@sunday_school.route("/teacher/quizzes/<int:quiz_id>/preview")
@teacher_required
def preview_quiz(quiz_id):
    teacher_id=session.get("ss_user_id")
    conn=get_db(); quiz=get_teacher_quiz(conn,quiz_id,teacher_id)
    if not quiz:
        conn.close(); flash("Quiz not found or access denied.","danger")
        return redirect(url_for("sunday_school.teacher_quizzes"))
    questions=conn.execute("SELECT * FROM sunday_school_quiz_questions WHERE quiz_id=? ORDER BY question_order",(quiz_id,)).fetchall()
    total=sum(q["points"] for q in questions)
    conn.close()
    return render_template("sunday_school/preview_quiz.html",quiz=quiz,questions=questions,total=total)


@sunday_school.route("/teacher/quizzes/<int:quiz_id>/toggle-publish", methods=["POST"])
@teacher_required
def toggle_quiz_publish(quiz_id):
    teacher_id=session.get("ss_user_id")
    conn=get_db(); quiz=get_teacher_quiz(conn,quiz_id,teacher_id)
    if not quiz:
        conn.close(); flash("Quiz not found or access denied.","danger")
        return redirect(url_for("sunday_school.teacher_quizzes"))
    count=conn.execute("SELECT COUNT(*) FROM sunday_school_quiz_questions WHERE quiz_id=?",(quiz_id,)).fetchone()[0]
    if quiz["status"]=="draft" and count==0:
        conn.close(); flash("Add at least one question before publishing.","danger")
        return redirect(url_for("sunday_school.edit_quiz",quiz_id=quiz_id))
    status="draft" if quiz["status"]=="published" else "published"
    conn.execute("UPDATE sunday_school_quizzes SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,quiz_id))
    conn.commit(); conn.close()
    flash("Quiz published." if status=="published" else "Quiz returned to draft.","success")
    return redirect(url_for("sunday_school.teacher_quizzes"))


@sunday_school.route("/teacher/quizzes/<int:quiz_id>/delete", methods=["POST"])
@teacher_required
def delete_quiz(quiz_id):
    teacher_id=session.get("ss_user_id")
    conn=get_db()
    conn.execute("DELETE FROM sunday_school_quizzes WHERE id=? AND teacher_id=?",(quiz_id,teacher_id))
    conn.commit(); conn.close()
    flash("Quiz deleted.","success")
    return redirect(url_for("sunday_school.teacher_quizzes"))
