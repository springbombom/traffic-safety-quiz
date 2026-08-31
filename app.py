import csv
from copy import copy
import io
import json
import os
import secrets
import socket
import sqlite3
import threading
from datetime import datetime
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

from flask import (
    Flask, Response, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("QUIZ_DATA_DIR", BASE_DIR / "data")).resolve()
TTS_DIR = DATA_DIR / "tts_cache"
DB_PATH = DATA_DIR / "results.db"
# 질문 원본은 배포 파일에 포함하고, 응답 DB만 영구 저장공간으로 분리합니다.
QUESTIONS_PATH = BASE_DIR / "data" / "questions.json"
TTS_LOCK = threading.Lock()

app = Flask(__name__)
app.secret_key = os.environ.get("QUIZ_SECRET_KEY", "local-traffic-safety-change-me")
app.config.update(JSON_AS_ASCII=False, MAX_CONTENT_LENGTH=1024 * 1024)
if os.environ.get("QUIZ_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def public_base_url():
    configured = os.environ.get("QUIZ_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().rstrip("/")
    return f"https://{render_hostname}" if render_hostname else ""


@contextmanager
def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    TTS_DIR.mkdir(exist_ok=True)
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS classrooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            respondent_code TEXT NOT NULL,
            test_id TEXT NOT NULL,
            test_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            total_score INTEGER,
            completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            question_number INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            choice_value INTEGER NOT NULL CHECK(choice_value BETWEEN 1 AND 5),
            choice_text TEXT NOT NULL,
            score INTEGER NOT NULL,
            answered_at TEXT NOT NULL,
            UNIQUE(attempt_id, question_id),
            FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
        );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(attempts)")}
        if "classroom_id" not in columns:
            db.execute("ALTER TABLE attempts ADD COLUMN classroom_id INTEGER")
        room_columns = {row["name"] for row in db.execute("PRAGMA table_info(classrooms)")}
        if "admin_pin_hash" not in room_columns:
            db.execute("ALTER TABLE classrooms ADD COLUMN admin_pin_hash TEXT")
        legacy_initialized = db.execute("SELECT value FROM app_settings WHERE key = 'legacy_room_initialized'").fetchone()
        default_room = db.execute("SELECT id FROM classrooms WHERE code = 'EXISTING'").fetchone()
        if not legacy_initialized:
            if not default_room:
                cursor = db.execute(
                    "INSERT INTO classrooms (name, code, created_at, active) VALUES (?, ?, ?, 1)",
                    ("기존 강의방", "EXISTING", now_iso()),
                )
                default_room_id = cursor.lastrowid
            else:
                default_room_id = default_room["id"]
            db.execute("INSERT INTO app_settings (key, value) VALUES ('legacy_room_initialized', '1')")
        else:
            default_room_id = default_room["id"] if default_room else None
        if default_room_id is not None:
            db.execute("UPDATE attempts SET classroom_id = ? WHERE classroom_id IS NULL", (default_room_id,))
        default_hash = generate_password_hash(os.environ.get("ADMIN_PIN", "1234"))
        db.execute("UPDATE classrooms SET admin_pin_hash = ? WHERE admin_pin_hash IS NULL OR admin_pin_hash = ''", (default_hash,))


def load_data():
    with QUESTIONS_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    choices = data["choices"]
    ordinal_words = [
        "첫", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열",
        "열한", "열두", "열세", "열네", "열다섯", "열여섯", "열일곱", "열여덟", "열아홉", "스무",
        "스물한", "스물두", "스물세", "스물네", "스물다섯", "스물여섯", "스물일곱", "스물여덟", "스물아홉", "서른",
    ]
    for test in data["tests"]:
        for question in test["questions"]:
            question.setdefault("choices", choices)
            question.setdefault("reverse_scored", False)
            question.setdefault("scoring", "5-1" if question["reverse_scored"] else "1-5")
            ordinal = ordinal_words[question["number"] - 1]
            question.setdefault("speech_text", f"{ordinal} 번째 질문입니다. {question['text']}")
            question.setdefault("help_text", "이 문장이 자신의 생각이나 평소 모습과 얼마나 일치하는지를 묻는 질문입니다.")
    return data


def get_test(test_id):
    return next((item for item in load_data()["tests"] if item["id"] == test_id), None)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_ok") and not session.get("room_admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def room_access_allowed(classroom_id):
    return bool(session.get("admin_ok") or session.get("room_admin_id") == classroom_id)


def get_classroom_by_code(code, active_only=True):
    query = "SELECT * FROM classrooms WHERE code = ?"
    if active_only:
        query += " AND active = 1"
    with get_db() as db:
        row = db.execute(query, (code,)).fetchone()
    return dict(row) if row else None


def latest_classroom():
    with get_db() as db:
        row = db.execute("SELECT * FROM classrooms WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


@app.get("/")
def index():
    return render_template("room_entry.html")


@app.post("/join")
def join_room():
    code = request.form.get("room_code", "").strip().upper()
    classroom = get_classroom_by_code(code)
    if not classroom:
        return render_template("room_entry.html", error="접속코드를 확인해 주세요."), 404
    return redirect(url_for("room_access", code=classroom["code"]))


@app.get("/room/<code>")
def room_access(code):
    classroom = get_classroom_by_code(code.strip().upper())
    if not classroom:
        return render_template("room_closed.html"), 404
    return render_template("index.html", tests=load_data()["tests"], classroom=classroom)


@app.post("/start")
def start():
    test_id = request.form.get("test_id", "").strip()
    respondent_code = request.form.get("respondent_code", "").strip()
    room_code = request.form.get("room_code", "").strip().upper()
    test = get_test(test_id)
    classroom = get_classroom_by_code(room_code)
    if not test or not classroom or not respondent_code or len(respondent_code) > 40:
        return render_template("index.html", tests=load_data()["tests"], classroom=classroom, error="접속코드와 좌석 번호를 확인한 뒤 Q1 또는 Q2를 눌러 주세요."), 400
    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO attempts (respondent_code, test_id, test_name, started_at, classroom_id) VALUES (?, ?, ?, ?, ?)",
            (respondent_code, test["id"], test["name"], now_iso(), classroom["id"]),
        )
        attempt_id = cursor.lastrowid
    return redirect(url_for("quiz", attempt_id=attempt_id))


@app.get("/quiz/<int:attempt_id>")
def quiz(attempt_id):
    with get_db() as db:
        attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        return "검사 기록을 찾을 수 없습니다.", 404
    if attempt["completed"]:
        return redirect(url_for("result", attempt_id=attempt_id))
    test = get_test(attempt["test_id"])
    if not test:
        return "질문 데이터를 찾을 수 없습니다.", 500
    return render_template("quiz.html", attempt=dict(attempt), test=test)


@app.post("/api/attempts/<int:attempt_id>/answer")
def save_answer(attempt_id):
    payload = request.get_json(silent=True) or {}
    question_id = str(payload.get("question_id", ""))
    try:
        value = int(payload.get("value"))
    except (TypeError, ValueError):
        return jsonify(error="답을 하나 선택해 주세요."), 400
    with get_db() as db:
        attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        if not attempt or attempt["completed"]:
            return jsonify(error="저장할 수 없는 검사입니다."), 400
        test = get_test(attempt["test_id"])
        question = next((q for q in test["questions"] if q["id"] == question_id), None)
        if not question or value not in range(1, 6):
            return jsonify(error="문항 또는 답변이 올바르지 않습니다."), 400
        choice_text = question["choices"][value - 1]
        score = 6 - value if question.get("reverse_scored") else value
        db.execute("""
            INSERT INTO answers
            (attempt_id, question_id, question_number, question_text, choice_value, choice_text, score, answered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attempt_id, question_id) DO UPDATE SET
              choice_value=excluded.choice_value, choice_text=excluded.choice_text,
              score=excluded.score, answered_at=excluded.answered_at
        """, (attempt_id, question_id, question["number"], question["text"], value, choice_text, score, now_iso()))
    return jsonify(ok=True, choice_text=choice_text)


@app.post("/api/attempts/<int:attempt_id>/complete")
def complete(attempt_id):
    with get_db() as db:
        attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        if not attempt:
            return jsonify(error="검사 기록을 찾을 수 없습니다."), 404
        test = get_test(attempt["test_id"])
        row = db.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(score), 0) AS total FROM answers WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if row["count"] != len(test["questions"]):
            return jsonify(error="모든 문항에 답해 주세요."), 400
        db.execute(
            "UPDATE attempts SET completed = 1, completed_at = ?, total_score = ? WHERE id = ?",
            (now_iso(), row["total"], attempt_id),
        )
    return jsonify(ok=True, redirect=url_for("result", attempt_id=attempt_id))


@app.get("/result/<int:attempt_id>")
def result(attempt_id):
    with get_db() as db:
        attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt or not attempt["completed"]:
        return redirect(url_for("index"))
    attempt = dict(attempt)
    category_results = None
    test = get_test(attempt["test_id"])
    if test and test.get("categories"):
        category_by_id = {question["id"]: question["category"] for question in test["questions"]}
        category_scores = {category["code"]: 0 for category in test["categories"]}
        with get_db() as db:
            answers = db.execute("SELECT question_id, score FROM answers WHERE attempt_id = ?", (attempt_id,)).fetchall()
        for answer in answers:
            category = category_by_id.get(answer["question_id"])
            if category in category_scores:
                category_scores[category] += answer["score"]
        category_results = [
            {"code": category["code"], "name": category["name"], "score": category_scores[category["code"]]}
            for category in test["categories"]
        ]
    return render_template("result.html", attempt=attempt, category_results=category_results)


@app.get("/admin/login")
def admin_login():
    with get_db() as db:
        classrooms = [dict(row) for row in db.execute("SELECT id, name, code, active FROM classrooms ORDER BY id DESC")]
    return render_template("admin_login.html", classrooms=classrooms)


@app.post("/admin/login")
def admin_login_post():
    configured_pin = os.environ.get("ADMIN_PIN", "1234")
    pin = request.form.get("pin", "")
    room_id = request.form.get("room_id", type=int)
    if not room_id and pin == configured_pin:
        session.clear()
        session["admin_ok"] = True
        return redirect(url_for("admin"))
    if room_id:
        with get_db() as db:
            classroom = db.execute("SELECT * FROM classrooms WHERE id = ?", (room_id,)).fetchone()
        if classroom and classroom["admin_pin_hash"] and check_password_hash(classroom["admin_pin_hash"], pin):
            session.clear()
            session["room_admin_id"] = classroom["id"]
            return redirect(url_for("admin", room_id=classroom["id"]))
    with get_db() as db:
        classrooms = [dict(row) for row in db.execute("SELECT id, name, code, active FROM classrooms ORDER BY id DESC")]
    return render_template("admin_login.html", classrooms=classrooms, error="선택한 교육장 또는 관리자 번호가 올바르지 않습니다."), 401


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


def admin_rows(classroom_id):
    with get_db() as db:
        attempts = [dict(row) for row in db.execute("SELECT * FROM attempts WHERE classroom_id = ? ORDER BY id DESC", (classroom_id,))]
        stats = [dict(row) for row in db.execute("""
            SELECT a.test_name, n.question_number, n.question_text,
                   COUNT(*) AS response_count, ROUND(AVG(choice_value), 2) AS average,
                   SUM(choice_value=1) AS c1, SUM(choice_value=2) AS c2,
                   SUM(choice_value=3) AS c3, SUM(choice_value=4) AS c4,
                   SUM(choice_value=5) AS c5
            FROM answers n JOIN attempts a ON a.id = n.attempt_id
            WHERE a.classroom_id = ?
            GROUP BY a.test_id, n.question_id ORDER BY a.test_name, n.question_number
        """, (classroom_id,))]
    return attempts, stats


@app.get("/admin")
@admin_required
def admin():
    with get_db() as db:
        if session.get("admin_ok"):
            classrooms = [dict(row) for row in db.execute("SELECT * FROM classrooms ORDER BY id DESC")]
        else:
            classrooms = [dict(row) for row in db.execute("SELECT * FROM classrooms WHERE id = ?", (session.get("room_admin_id"),))]
    requested_id = request.args.get("room_id", type=int)
    selected = next((room for room in classrooms if room["id"] == requested_id), None) or (classrooms[0] if classrooms else None)
    attempts, stats = admin_rows(selected["id"]) if selected else ([], [])
    total = len(attempts)
    completed = sum(item["completed"] for item in attempts)
    in_progress = total - completed
    completion_rate = round(completed * 100 / total, 1) if total else 0
    return render_template("admin.html", attempts=attempts, stats=stats, completion_rate=completion_rate,
                           completed_count=completed, in_progress_count=in_progress,
                           classrooms=classrooms, selected_room=selected,
                           room_url=(f"http://{local_ip()}:5000/room/{selected['code']}" if selected else ""))


def new_room_code():
    while True:
        code = str(secrets.randbelow(900000) + 100000)
        with get_db() as db:
            exists = db.execute("SELECT 1 FROM classrooms WHERE code = ?", (code,)).fetchone()
        if not exists:
            return code


@app.post("/admin/classrooms")
@admin_required
def create_classroom():
    if not session.get("admin_ok"):
        return "총괄 관리자만 강의방을 만들 수 있습니다.", 403
    name = request.form.get("name", "").strip()
    admin_pin = request.form.get("admin_pin", "").strip()
    if not name or len(name) > 80 or not admin_pin.isdigit() or not 4 <= len(admin_pin) <= 8:
        return redirect(url_for("admin"))
    with get_db() as db:
        cursor = db.execute("INSERT INTO classrooms (name, code, created_at, active, admin_pin_hash) VALUES (?, ?, ?, 1, ?)",
                            (name, new_room_code(), now_iso(), generate_password_hash(admin_pin)))
        room_id = cursor.lastrowid
    return redirect(url_for("admin", room_id=room_id))


@app.post("/admin/classrooms/<int:classroom_id>/toggle")
@admin_required
def toggle_classroom(classroom_id):
    if not room_access_allowed(classroom_id):
        return "접근 권한이 없습니다.", 403
    with get_db() as db:
        db.execute("UPDATE classrooms SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (classroom_id,))
    return redirect(url_for("admin", room_id=classroom_id))


@app.post("/admin/classrooms/<int:classroom_id>/delete")
@admin_required
def delete_classroom(classroom_id):
    if not session.get("admin_ok"):
        return "총괄 관리자만 강의방을 삭제할 수 있습니다.", 403
    with get_db() as db:
        attempt_ids = [row["id"] for row in db.execute("SELECT id FROM attempts WHERE classroom_id = ?", (classroom_id,))]
        for attempt_id in attempt_ids:
            db.execute("DELETE FROM answers WHERE attempt_id = ?", (attempt_id,))
        db.execute("DELETE FROM attempts WHERE classroom_id = ?", (classroom_id,))
        db.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
    return redirect(url_for("admin"))


@app.post("/admin/classrooms/<int:classroom_id>/clear-results")
@admin_required
def clear_classroom_results(classroom_id):
    if not room_access_allowed(classroom_id):
        return "접근 권한이 없습니다.", 403
    with get_db() as db:
        attempt_ids = [row["id"] for row in db.execute("SELECT id FROM attempts WHERE classroom_id = ?", (classroom_id,))]
        for attempt_id in attempt_ids:
            db.execute("DELETE FROM answers WHERE attempt_id = ?", (attempt_id,))
        db.execute("DELETE FROM attempts WHERE classroom_id = ?", (classroom_id,))
    return redirect(url_for("admin", room_id=classroom_id))


@app.post("/admin/attempts/<int:attempt_id>/delete")
@admin_required
def delete_attempt(attempt_id):
    with get_db() as db:
        attempt = db.execute("SELECT classroom_id FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        if attempt and not room_access_allowed(attempt["classroom_id"]):
            return "접근 권한이 없습니다.", 403
        if attempt:
            db.execute("DELETE FROM answers WHERE attempt_id = ?", (attempt_id,))
            db.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))
    return redirect(url_for("admin", room_id=attempt["classroom_id"])) if attempt else redirect(url_for("admin"))


@app.get("/admin/classrooms/<int:classroom_id>/qr.png")
@admin_required
def classroom_qr(classroom_id):
    if not room_access_allowed(classroom_id):
        return "접근 권한이 없습니다.", 403
    with get_db() as db:
        classroom = db.execute("SELECT * FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
    if not classroom:
        return "강의방을 찾을 수 없습니다.", 404
    try:
        import qrcode
    except ImportError:
        return "QR 구성요소가 설치되지 않았습니다. install.bat를 다시 실행해 주세요.", 503
    public_url = public_base_url()
    room_url = f"{public_url}/room/{classroom['code']}" if public_url else f"http://{local_ip()}:5000/room/{classroom['code']}"
    image = qrcode.make(room_url)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return send_file(stream, mimetype="image/png", download_name=f"room-{classroom['code']}-qr.png")


@app.get("/admin/classrooms/<int:classroom_id>/qr")
@admin_required
def classroom_qr_page(classroom_id):
    if not room_access_allowed(classroom_id):
        return "접근 권한이 없습니다.", 403
    with get_db() as db:
        classroom = db.execute("SELECT * FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
    if not classroom:
        return "강의방을 찾을 수 없습니다.", 404
    classroom = dict(classroom)
    return render_template(
        "admin_qr.html",
        classroom=classroom,
        room_url=f"http://{local_ip()}:5000/room/{classroom['code']}",
    )


@app.route("/admin/classrooms/<int:classroom_id>/settings", methods=["GET", "POST"])
@admin_required
def classroom_settings(classroom_id):
    if not room_access_allowed(classroom_id):
        return "접근 권한이 없습니다.", 403
    with get_db() as db:
        classroom = db.execute("SELECT * FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
    if not classroom:
        return "교육장을 찾을 수 없습니다.", 404
    classroom = dict(classroom)
    if request.method == "POST":
        current_pin = request.form.get("current_pin", "")
        new_pin = request.form.get("new_pin", "")
        confirm_pin = request.form.get("confirm_pin", "")
        if not session.get("admin_ok") and not check_password_hash(classroom["admin_pin_hash"], current_pin):
            return render_template("admin_settings.html", classroom=classroom, error="현재 관리자 번호가 올바르지 않습니다."), 400
        if not new_pin.isdigit() or not 4 <= len(new_pin) <= 8 or new_pin != confirm_pin:
            return render_template("admin_settings.html", classroom=classroom, error="새 번호는 동일한 4~8자리 숫자로 입력해 주세요."), 400
        with get_db() as db:
            db.execute("UPDATE classrooms SET admin_pin_hash = ? WHERE id = ?", (generate_password_hash(new_pin), classroom_id))
        return render_template("admin_settings.html", classroom=classroom, success="관리자 번호가 변경되었습니다.")
    return render_template("admin_settings.html", classroom=classroom)


@app.get("/admin/export.csv")
@admin_required
def export_csv():
    classroom_id = request.args.get("room_id", type=int)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["강의방", "응답ID", "좌석번호", "검사명", "시작시간", "종료시간", "완료", "총점", "문항번호", "질문", "선택값", "선택내용", "채점점수"])
    with get_db() as db:
        rows = db.execute("""
            SELECT c.name, a.id, a.respondent_code, a.test_name, a.started_at, a.completed_at,
                   a.completed, a.total_score, n.question_number, n.question_text,
                   n.choice_value, n.choice_text, n.score
            FROM attempts a JOIN classrooms c ON c.id = a.classroom_id
            LEFT JOIN answers n ON n.attempt_id = a.id
            WHERE (? IS NULL OR a.classroom_id = ?)
            ORDER BY a.id, n.question_number
        """, (classroom_id, classroom_id))
        for row in rows:
            writer.writerow(list(row))
    return Response(output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=traffic_safety_results.csv"})


@app.get("/admin/export.xlsx")
@admin_required
def export_xlsx():
    classroom_id = request.args.get("room_id", type=int)
    try:
        from openpyxl import Workbook
    except ImportError:
        return "Excel 내보내기 구성요소가 없습니다. requirements.txt를 다시 설치해 주세요.", 503
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "응답 결과"
    sheet.append(["강의방", "응답ID", "좌석번호", "검사명", "시작시간", "종료시간", "완료", "총점", "문항번호", "질문", "선택값", "선택내용", "채점점수"])
    with get_db() as db:
        for row in db.execute("""
            SELECT c.name, a.id, a.respondent_code, a.test_name, a.started_at, a.completed_at,
                   a.completed, a.total_score, n.question_number, n.question_text,
                   n.choice_value, n.choice_text, n.score
            FROM attempts a JOIN classrooms c ON c.id = a.classroom_id
            LEFT JOIN answers n ON n.attempt_id = a.id
            WHERE (? IS NULL OR a.classroom_id = ?)
            ORDER BY a.id, n.question_number
        """, (classroom_id, classroom_id)):
            sheet.append(list(row))
    for cell in sheet[1]:
        font = copy(cell.font)
        font.bold = True
        cell.font = font
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return send_file(stream, as_attachment=True, download_name="traffic_safety_results.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/tts")
def tts():
    text = request.args.get("text", "").strip()
    rate = request.args.get("rate", "normal")
    if not text or len(text) > 500:
        return jsonify(error="읽을 문장이 없습니다."), 400
    import hashlib
    key = hashlib.sha256(f"{rate}|{text}".encode("utf-8")).hexdigest()
    path = TTS_DIR / f"{key}.wav"
    if not path.exists():
        try:
            import pyttsx3
            with TTS_LOCK:
                if not path.exists():
                    engine = pyttsx3.init()
                    voices = engine.getProperty("voices")
                    korean = next((v for v in voices if "ko" in str(getattr(v, "languages", "")).lower() or "korean" in v.name.lower() or "heami" in v.name.lower()), None)
                    if korean:
                        engine.setProperty("voice", korean.id)
                    engine.setProperty("rate", 135 if rate == "slow" else 165)
                    engine.save_to_file(text, str(path))
                    engine.runAndWait()
                    engine.stop()
        except Exception as exc:
            return jsonify(error="교수 PC의 오프라인 음성을 만들 수 없습니다.", detail=str(exc)), 503
    if not path.exists() or path.stat().st_size == 0:
        return jsonify(error="음성 파일을 만들 수 없습니다."), 503
    return send_file(path, mimetype="audio/wav", conditional=True)


@app.get("/health")
def health():
    return jsonify(ok=True, time=now_iso())


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


# Gunicorn 같은 인터넷용 실행기에서도 데이터베이스를 준비합니다.
init_db()


if __name__ == "__main__":
    print(f"교육생 접속 주소: http://{local_ip()}:5000")
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=5000, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=5000, debug=False)
