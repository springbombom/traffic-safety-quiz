import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("quiz_app", ROOT / "app.py")
quiz_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiz_app)


class QuizFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        quiz_app.DB_PATH = Path(self.temp.name) / "test.db"
        quiz_app.app.config.update(TESTING=True, SECRET_KEY="test")
        quiz_app.init_db()
        self.client = quiz_app.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_flow_and_admin(self):
        response = self.client.post("/start", data={"respondent_code": "T-001", "test_id": "drinking-driving-tendency-q1", "room_code": "EXISTING"})
        self.assertEqual(response.status_code, 302)
        attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
        test = quiz_app.get_test("drinking-driving-tendency-q1")
        for q in test["questions"]:
            saved = self.client.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": q["id"], "value": 3})
            self.assertEqual(saved.status_code, 200)
        complete = self.client.post(f"/api/attempts/{attempt_id}/complete")
        self.assertEqual(complete.status_code, 200)
        result_page = self.client.get(f"/result/{attempt_id}").get_data(as_text=True)
        self.assertIn("항목별 합산 점수", result_page)
        self.assertIn("잘못된 손익계산", result_page)
        self.assertIn("운전능력 과신", result_page)
        self.assertIn("죄책감", result_page)
        self.assertIn("12점", result_page)
        self.assertIn("21점", result_page)
        self.assertIn("24점", result_page)
        with self.client.session_transaction() as session:
            session["admin_ok"] = True
        self.assertEqual(self.client.get("/admin").status_code, 200)
        csv_response = self.client.get("/admin/export.csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("T-001", csv_response.get_data(as_text=True))
        xlsx_response = self.client.get("/admin/export.xlsx")
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertTrue(xlsx_response.data.startswith(b"PK"))

    def test_cannot_complete_without_all_answers(self):
        response = self.client.post("/start", data={"respondent_code": "T-002", "test_id": "drinking-driving-tendency-q1", "room_code": "EXISTING"})
        attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
        self.assertEqual(self.client.post(f"/api/attempts/{attempt_id}/complete").status_code, 400)

    def test_main_screen_buttons_open_correct_tests(self):
        entry_page = self.client.get("/").get_data(as_text=True)
        self.assertIn("교육장 접속코드", entry_page)
        self.assertIn("qr-guide-line", entry_page)
        self.assertIn("교수가 보여주는 QR코드를 촬영해 접속해 주세요", entry_page)
        self.assertNotIn("Q1", entry_page)
        page = self.client.get("/room/EXISTING").get_data(as_text=True)
        self.assertIn("음주운전 성향검사", page)
        self.assertIn("koroad-ci.png", page)
        self.assertIn("한국도로교통공단 KOROAD", page)
        self.assertIn("내 좌석 번호", page)
        self.assertNotIn("현재 강의방", page)
        self.assertNotIn("기존 강의방", page)
        self.assertIn('value="drinking-driving-tendency-q1"', page)
        self.assertIn('value="drinking-driving-tendency-q2"', page)
        self.assertEqual(self.client.post("/start", data={"respondent_code": "", "test_id": "drinking-driving-tendency-q1", "room_code": "EXISTING"}).status_code, 400)
        q1 = self.client.post("/start", data={"respondent_code": "왼쪽-12", "test_id": "drinking-driving-tendency-q1", "room_code": "EXISTING"}, follow_redirects=True)
        self.assertIn("1 / 19", q1.get_data(as_text=True))
        self.assertIn("답안 모두 듣기", q1.get_data(as_text=True))
        q2 = self.client.post("/start", data={"respondent_code": "오른쪽-13", "test_id": "drinking-driving-tendency-q2", "room_code": "EXISTING"}, follow_redirects=True)
        self.assertIn("1 / 30", q2.get_data(as_text=True))

    def test_q2_result_shows_six_category_scores(self):
        response = self.client.post("/start", data={"respondent_code": "Q2-좌석", "test_id": "drinking-driving-tendency-q2", "room_code": "EXISTING"})
        attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
        test = quiz_app.get_test("drinking-driving-tendency-q2")
        for question in test["questions"]:
            self.client.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": question["id"], "value": 3})
        self.client.post(f"/api/attempts/{attempt_id}/complete")
        result_page = self.client.get(f"/result/{attempt_id}").get_data(as_text=True)
        self.assertIn("항목별 합산 점수", result_page)
        for label in ["도덕성", "내부귀인", "외부귀인", "자기통제력", "충동성", "감각추구성향"]:
            self.assertIn(label, result_page)
        for expected_score in ["18점", "12점", "9점", "21점"]:
            self.assertIn(expected_score, result_page)

    def test_classroom_create_separate_and_delete(self):
        with self.client.session_transaction() as session:
            session["admin_ok"] = True
        created = self.client.post("/admin/classrooms", data={"name": "오후 특별반", "admin_pin": "5678"})
        self.assertEqual(created.status_code, 302)
        with quiz_app.get_db() as db:
            room = db.execute("SELECT * FROM classrooms WHERE name = ?", ("오후 특별반",)).fetchone()
        self.assertIsNotNone(room)
        self.assertEqual(len(room["code"]), 6)
        self.assertTrue(room["code"].isdigit())
        room_page = self.client.get(f"/room/{room['code']}")
        self.assertNotIn("오후 특별반", room_page.get_data(as_text=True))
        self.assertIn("음주운전 성향검사", room_page.get_data(as_text=True))
        response = self.client.post("/start", data={"respondent_code": "분리좌석", "test_id": "drinking-driving-tendency-q1", "room_code": room["code"]})
        self.assertEqual(response.status_code, 302)
        admin_page = self.client.get(f"/admin?room_id={room['id']}").get_data(as_text=True)
        self.assertIn("분리좌석", admin_page)
        self.assertIn("음주진단 체크리스트", admin_page)
        self.assertIn("관리자모드", admin_page)
        self.assertIn("교수 전용", admin_page)
        self.assertNotIn("강사 전용", admin_page)
        self.assertIn("koroad-ci.png", admin_page)
        self.assertIn("실시간 강의 참여 현황", admin_page)
        self.assertIn("전체 참여", admin_page)
        self.assertIn("검사 완료", admin_page)
        self.assertNotIn("전체 답안 선택 분포", admin_page)
        qr = self.client.get(f"/admin/classrooms/{room['id']}/qr.png")
        self.assertEqual(qr.status_code, 200)
        self.assertTrue(qr.data.startswith(b"\x89PNG"))
        qr_page = self.client.get(f"/admin/classrooms/{room['id']}/qr")
        self.assertEqual(qr_page.status_code, 200)
        self.assertIn("강의방 QR코드", qr_page.get_data(as_text=True))
        self.assertIn(room["code"], qr_page.get_data(as_text=True))
        self.client.post("/admin/logout")
        login_page = self.client.get("/admin/login").get_data(as_text=True)
        self.assertIn("관리할 교육장 선택", login_page)
        self.assertIn("오후 특별반", login_page)
        room_login = self.client.post("/admin/login", data={"room_id": room["id"], "pin": "5678"})
        self.assertEqual(room_login.status_code, 302)
        room_admin_page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("오후 특별반", room_admin_page)
        self.assertNotIn("새 강의방 개설", room_admin_page)
        self.assertEqual(self.client.post("/admin/classrooms", data={"name": "금지된 방", "admin_pin": "9999"}).status_code, 403)
        settings_page = self.client.get(f"/admin/classrooms/{room['id']}/settings")
        self.assertIn("관리자 번호 변경", settings_page.get_data(as_text=True))
        changed = self.client.post(f"/admin/classrooms/{room['id']}/settings", data={"current_pin": "5678", "new_pin": "6789", "confirm_pin": "6789"})
        self.assertIn("관리자 번호가 변경되었습니다", changed.get_data(as_text=True))
        self.client.post("/admin/logout")
        self.assertEqual(self.client.post("/admin/login", data={"room_id": room["id"], "pin": "5678"}).status_code, 401)
        self.assertEqual(self.client.post("/admin/login", data={"room_id": room["id"], "pin": "6789"}).status_code, 302)
        with self.client.session_transaction() as session:
            session.clear()
            session["admin_ok"] = True
        deleted = self.client.post(f"/admin/classrooms/{room['id']}/delete")
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get(f"/room/{room['code']}").status_code, 404)

    def test_deleted_legacy_room_is_not_recreated(self):
        with self.client.session_transaction() as session:
            session["admin_ok"] = True
        with quiz_app.get_db() as db:
            legacy = db.execute("SELECT id FROM classrooms WHERE code = 'EXISTING'").fetchone()
        self.assertIsNotNone(legacy)
        self.client.post(f"/admin/classrooms/{legacy['id']}/delete")
        quiz_app.init_db()
        with quiz_app.get_db() as db:
            recreated = db.execute("SELECT id FROM classrooms WHERE code = 'EXISTING'").fetchone()
        self.assertIsNone(recreated)


if __name__ == "__main__":
    unittest.main()
