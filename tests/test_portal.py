"""Unit tests for CSIE Student Portal Rich Menu and features."""

import os
import sys
from datetime import date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock, patch

os.environ.setdefault("LINE_CHANNEL_SECRET", "mock_secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "mock_token")

# Stub external libraries if not installed in the testing environment
for mod in ["dotenv", "gspread", "gspread.exceptions", "google", "google.oauth2", "google.oauth2.service_account", "fastapi"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "linebot" not in sys.modules:
    linebot_mock = MagicMock()
    sys.modules["linebot"] = linebot_mock
    sys.modules["linebot.v3"] = linebot_mock
    sys.modules["linebot.v3.messaging"] = linebot_mock
    sys.modules["linebot.v3.webhooks"] = linebot_mock
    sys.modules["linebot.v3.exceptions"] = linebot_mock

    # Provide real container and action mocks that behave like line-bot-sdk
    class MockFlexContainer:
        @classmethod
        def from_dict(cls, data):
            inst = cls()
            inst.data = data
            return inst

    class MockFlexMessage:
        def __init__(self, alt_text, contents, quick_reply=None):
            self.alt_text = alt_text
            self.contents = contents
            self.quick_reply = quick_reply

    class MockPostbackAction:
        def __init__(self, label, data, display_text=None):
            self.label = label
            self.data = data
            self.display_text = display_text
        def to_dict(self):
            d = {"type": "postback", "label": self.label, "data": self.data}
            if self.display_text:
                d["displayText"] = self.display_text
            return d

    class MockRichMenuBounds:
        def __init__(self, x, y, width, height):
            self.x, self.y, self.width, self.height = x, y, width, height

    class MockRichMenuSize:
        def __init__(self, width, height):
            self.width, self.height = width, height

    class MockRichMenuArea:
        def __init__(self, bounds, action):
            self.bounds, self.action = bounds, action

    class MockRichMenuRequest:
        def __init__(self, size, selected, name, chat_bar_text, areas):
            self.size, self.selected, self.name = size, selected, name
            self.chat_bar_text, self.areas = chat_bar_text, areas

    linebot_mock.FlexContainer = MockFlexContainer
    linebot_mock.FlexMessage = MockFlexMessage
    linebot_mock.PostbackAction = MockPostbackAction
    linebot_mock.RichMenuBounds = MockRichMenuBounds
    linebot_mock.RichMenuSize = MockRichMenuSize
    linebot_mock.RichMenuArea = MockRichMenuArea
    linebot_mock.RichMenuRequest = MockRichMenuRequest
    linebot_mock.QuickReply = MagicMock
    linebot_mock.QuickReplyItem = MagicMock

from attendance.salary import calculate_salary, SalaryEstimate
from bot.line_ui import (
    CARD_BG,
    DARK_GREEN,
    BUTTON_GREEN,
    help_center_message,
    initialization_message,
    leave_history_message,
    leave_request_menu_message,
    my_attendance_message,
    salary_breakdown_message,
    salary_overview_message,
    terms_agreement_confirmed_message,
    welcome_message,
    work_schedule_message,
)
from bot.rich_menu import build_rich_menu_request
from bot.commands import try_handle_natural_portal_query, normalize_command
from ui.leave_confirmation import (
    leave_confirmation_message,
    withdrawal_confirmation_message,
)
from database.google_sheets import get_student_attendance_summary
from attendance.student_directory import find_students_by_display_name
from app import resolve_student_from_event


class TestSalaryCalculation(TestCase):
    def test_calculate_salary_basic(self):
        est = calculate_salary(full_days=20, half_days=2)
        # 20 * 8 + 2 * 4 = 168 hours
        self.assertEqual(est.total_hours, 168)
        self.assertEqual(est.gross_salary, Decimal(168 * 196))
        self.assertEqual(est.labor_insurance, Decimal("679"))
        self.assertEqual(est.health_insurance, Decimal("460"))
        self.assertEqual(est.income_tax, est.gross_salary * Decimal("0.05"))
        self.assertEqual(est.welfare_fund, est.gross_salary * Decimal("0.005"))
        self.assertEqual(
            est.net_salary,
            est.gross_salary - est.total_deductions,
        )

    def test_calculate_salary_overtime(self):
        est = calculate_salary(full_days=10, half_days=0, overtime_hours=5)
        # 80 base hours + 5 OT hours = 85 hours
        self.assertEqual(est.total_hours, 85)
        self.assertEqual(est.overtime_hours, 5)
        self.assertEqual(est.overtime_pay, Decimal(5 * 263))
        self.assertEqual(est.gross_salary, Decimal(80 * 196 + 5 * 263))


class TestRichMenuRequest(TestCase):
    def test_rich_menu_request_structure(self):
        req = build_rich_menu_request()
        self.assertEqual(req.name, "CSIE Student Portal")
        self.assertEqual(req.size.width, 2500)
        self.assertEqual(req.size.height, 1686)
        self.assertEqual(len(req.areas), 6)

        # Verify area 1 (My Attendance) - Row 1, Col 1
        a1 = req.areas[0]
        self.assertEqual((a1.bounds.x, a1.bounds.y, a1.bounds.width, a1.bounds.height), (0, 0, 833, 843))
        self.assertEqual(a1.action.data, "action=richmenu_attendance")

        # Verify area 2 (Leave History) - Row 1, Col 2
        a2 = req.areas[1]
        self.assertEqual((a2.bounds.x, a2.bounds.y, a2.bounds.width, a2.bounds.height), (833, 0, 834, 843))
        self.assertEqual(a2.action.data, "action=richmenu_leave_history")

        # Verify area 3 (Salary Inquiry) - Row 1, Col 3
        a3 = req.areas[2]
        self.assertEqual((a3.bounds.x, a3.bounds.y, a3.bounds.width, a3.bounds.height), (1667, 0, 833, 843))
        self.assertEqual(a3.action.data, "action=richmenu_salary")

        # Verify area 4 (Work Schedule) - Row 2, Col 1
        a4 = req.areas[3]
        self.assertEqual((a4.bounds.x, a4.bounds.y, a4.bounds.width, a4.bounds.height), (0, 843, 833, 843))
        self.assertEqual(a4.action.data, "action=richmenu_schedule")

        # Verify area 5 (Leave Request) - Row 2, Col 2
        a5 = req.areas[4]
        self.assertEqual((a5.bounds.x, a5.bounds.y, a5.bounds.width, a5.bounds.height), (833, 843, 834, 843))
        self.assertEqual(a5.action.data, "action=richmenu_leave_request")

        # Verify area 6 (Help Center) - Row 2, Col 3
        a6 = req.areas[5]
        self.assertEqual((a6.bounds.x, a6.bounds.y, a6.bounds.width, a6.bounds.height), (1667, 843, 833, 843))
        self.assertEqual(a6.action.data, "action=richmenu_help")


class TestFlexMessageBuilders(TestCase):
    def test_salary_overview_message_design(self):
        est = calculate_salary(full_days=22, half_days=0)
        msg = salary_overview_message(est, month_label="October 2026")
        data = msg.contents.data
        self.assertEqual(data["type"], "bubble")
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_salary_breakdown_message_design(self):
        est = calculate_salary(full_days=20, half_days=2)
        msg = salary_breakdown_message(est, month_label="October 2026")
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_my_attendance_message_design(self):
        summary = {
            "scheduled_days": 23,
            "completed_scheduled_workdays": 9,
            "remaining_scheduled_workdays": 14,
            "elapsed_workdays": 9,
            "attended_days": 9,
            "absent_days": 0,
            "half_days": 0,
            "late_days": 0,
            "attendance_pct": 100,
            "today_status": "Rest Day",
        }
        msg = my_attendance_message(summary, month_label="October 2026")
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)
        texts = [c.get("text") for c in data["body"]["contents"] if c.get("type") == "text"]
        self.assertIn("My Attendance", texts)
        self.assertIn("Attendance Rate (Month-to-Date)", texts)
        self.assertIn("100%", texts)
        self.assertIn("100%", msg.alt_text)

    def test_my_attendance_message_na_design(self):
        summary = {
            "scheduled_days": 22,
            "completed_scheduled_workdays": 0,
            "remaining_scheduled_workdays": 22,
            "elapsed_workdays": 0,
            "attended_days": 0,
            "absent_days": 0,
            "half_days": 0,
            "late_days": 0,
            "attendance_pct": None,
            "today_status": "Upcoming",
        }
        msg = my_attendance_message(summary, month_label="November 2026")
        data = msg.contents.data
        self.assertIn("N/A", msg.alt_text)
        texts = [c.get("text") for c in data["body"]["contents"] if c.get("type") == "text"]
        self.assertIn("N/A", texts)

    def test_leave_history_message_design(self):
        records = [
            {"type": "Sick Leave", "date": "2026-10-08", "status": "Recorded"},
            {"type": "Personal Leave", "date": "2026-09-17", "status": "Recorded"},
        ]
        msg = leave_history_message(records, month_label="October 2026")
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_work_schedule_message_design(self):
        days = [
            {"date_str": "2026-10-14", "weekday_en": "Wed", "is_workday": True, "type": "Workday", "note": "8 hrs"},
            {"date_str": "2026-10-15", "weekday_en": "Thu", "is_workday": True, "type": "Workday", "note": "8 hrs"},
        ]
        msg = work_schedule_message(days)
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_leave_request_menu_message_design(self):
        msg = leave_request_menu_message("Juan Dela Cruz")
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_help_center_message_design(self):
        tickets = [
            {"Ticket ID": "A101", "Status": "OPEN", "Message": "Correction request for attendance"}
        ]
        msg = help_center_message(tickets)
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_welcome_message_design(self):
        msg = welcome_message()
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_welcome_message_with_recognized_student(self):
        student = {"student_id": "ST101", "name": "Romel Jr.", "chinese_name": "杜榮瑪"}
        msg = welcome_message(student)
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)
        self.assertIn("CSIE Student Portal", msg.alt_text)

    def test_initialization_message_recognized(self):
        student = {"student_id": "ST101", "name": "Romel Jr.", "chinese_name": "杜榮瑪"}
        msg = initialization_message(student, display_name="Romel Jr.", is_registered=True)
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)
        self.assertIn("Recognized", msg.alt_text)

    def test_initialization_message_unmatched(self):
        msg = initialization_message(None, display_name="RandomUser", error_status="unmatched")
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)
        self.assertIn("Unmatched", msg.alt_text)

    def test_terms_agreement_confirmed_message_design(self):
        student = {"student_id": "ST101", "name": "Romel Jr.", "chinese_name": "杜榮瑪"}
        msg = terms_agreement_confirmed_message(student)
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)
        self.assertIn("Terms Accepted", msg.alt_text)

    def test_leave_confirmation_message_design(self):
        msg = leave_confirmation_message(
            student_name="Romel Jr.",
            leave_date="2026/10/08",
            category="病假",
            record_id="REC001",
        )
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

    def test_withdrawal_confirmation_message_design(self):
        msg = withdrawal_confirmation_message(
            category="病假",
            leave_date="2026/10/08",
            record_id="REC001",
            confirmation_data="action=confirm",
        )
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)


class TestCommandHandling(TestCase):
    def test_normalize_command(self):
        self.assertEqual(normalize_command("/hello"), "hello")
        self.assertEqual(normalize_command("/salary 2026-10"), "salary")
        self.assertEqual(normalize_command("plain text"), "")

    def test_natural_query_leaves(self):
        with patch("database.google_sheets.get_student_leave_records", return_value=[]):
            res = try_handle_natural_portal_query("Show me all my sick leaves in September", "ST001")
            self.assertIsNotNone(res)


class TestAttendanceCalculation(TestCase):
    def summary(self, entries, today=date(2026, 10, 12), month=date(2026, 10, 1)):
        with patch("database.google_sheets.datetime") as clock, patch(
            "database.google_sheets.get_monthly_report_entries", return_value=entries
        ), patch("database.google_sheets.get_attendance_rows", side_effect=AssertionError("Leave logs must not be read")):
            clock.now.return_value.date.return_value = today
            return get_student_attendance_summary("ST001", month)

    def test_report_overrides_logs_and_ignores_future_leave(self):
        entries = {date(2026, 10, day): "" for day in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 23)}
        entries[date(2026, 10, 7)] = "病假"
        entries[date(2026, 10, 8)] = "半天"
        entries[date(2026, 10, 9)] = "遲到"
        entries[date(2026, 10, 23)] = "事假"
        summary = self.summary(entries)
        self.assertEqual(summary["completed_scheduled_workdays"], 9)
        self.assertEqual(summary["remaining_scheduled_workdays"], 2)
        self.assertEqual(summary["attended_days"], 7)
        self.assertEqual(summary["absent_days"], 1)
        self.assertEqual(summary["half_days"], 1)
        self.assertEqual(summary["late_days"], 1)
        self.assertEqual(summary["attendance_pct"], 83)
        self.assertEqual(summary["today_status"], "Rest Day")

    def test_today_pending_then_finalized_from_report(self):
        entries = {date(2026, 10, 7): "", date(2026, 10, 14): ""}
        summary = self.summary(entries, today=date(2026, 10, 14))
        self.assertEqual(summary["today_status"], "Pending")
        self.assertEqual(summary["completed_scheduled_workdays"], 1)
        entries[date(2026, 10, 14)] = "病假"
        summary = self.summary(entries, today=date(2026, 10, 14))
        self.assertEqual(summary["today_status"], "Sick Leave")
        self.assertEqual(summary["attendance_pct"], 50)

    def test_future_month_returns_na(self):
        summary = self.summary({date(2026, 11, 4): "病假"}, month=date(2026, 11, 1))
        self.assertIsNone(summary["attendance_pct"])
        self.assertEqual(summary["today_status"], "Upcoming")

    def test_missing_report_does_not_infer_perfect_attendance(self):
        with patch("database.google_sheets.get_monthly_report_entries", side_effect=ValueError("Missing month")):
            with self.assertRaises(ValueError):
                get_student_attendance_summary("ST001", date(2026, 10, 1))

    def test_scheduled_present_preserves_manual_report_leave(self):
        from database.google_sheets import mark_present_in_monthly_report
        target = date(2026, 10, 23)
        with patch("database.google_sheets.get_report_students", return_value=({"ST001": "Name", "ST002": "Other"}, {})), patch(
            "database.google_sheets.get_attendance_rows", return_value=[]
        ), patch("database.google_sheets.get_monthly_report_entries", side_effect=[{target: "事假"}, {target: ""}]), patch(
            "database.google_sheets.update_monthly_report_cell"
        ) as write:
            mark_present_in_monthly_report(target)
        write.assert_called_once_with("ST002", target, "出席")

    def test_real_grid_reader_selects_student_and_month(self):
        from database.google_sheets import get_monthly_report_entries
        sheet = MagicMock()
        sheet.get_all_values.return_value = [
            ["", "", "October 2026"],
            ["", "", "1", "2", "3", "4", "7"],
            ["OTHER", "Other", "病假"],
            ["ST001", "Name", "", "半天", "病假", "遲到", ""],
            ["", "", "November 2026"],
            ["ST001", "Name", "事假"],
        ]
        with patch("database.google_sheets._get_monthly_report_sheet", return_value=sheet):
            entries = get_monthly_report_entries("ST001", date(2026, 10, 1))
        self.assertEqual(entries[date(2026, 10, 2)], "半天")
        self.assertEqual(len(entries), 5)


class TestAdvanceLeave(TestCase):
    def test_dates(self):
        from attendance.leave_message import parse_attendance_date
        today = date(2026, 10, 12)
        for message, expected in (
            ("hi I already filed leave for tomorrow cannot work", date(2026, 10, 13)),
            ("I will be absent on oct 23 because of an appointment", date(2026, 10, 23)),
            ("I will be absent on October 23rd, 2026", date(2026, 10, 23)),
            ("I will be absent on 23 Oct", date(2026, 10, 23)),
            ("10月23日請假", date(2026, 10, 23)),
            ("day after tomorrow cannot work", date(2026, 10, 14)),
            ("leave on 2027-01-02", date(2027, 1, 2)),
        ):
            with self.subTest(message=message):
                self.assertEqual(parse_attendance_date(message, today=today), expected)
        with self.assertRaises(ValueError):
            parse_attendance_date("absent on Feb 30", today=today)

    def test_advance_leave_classified_without_ai(self):
        from attendance.ai_classifier import classify_attendance_message
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            for message, category in (
                ("hi I already filed leave for tomorrow cannot work", "事假"),
                ("I will be absent on oct 23 because of an appointment", "不出來"),
            ):
                with self.subTest(message=message):
                    result = classify_attendance_message(message)
                    self.assertEqual(result.intent, "LEAVE")
                    self.assertEqual(result.category, category)


class TestStudentDirectoryMatching(TestCase):
    def test_find_students_by_display_name_primary(self):
        students = [
            {"student_id": "ST101", "name": "Romel", "display_name": "Romel Jr.", "active": "true"},
            {"student_id": "ST102", "name": "Juan", "display_name": "Juan Dela Cruz", "active": "true"},
        ]
        matches = find_students_by_display_name(students, "Romel Jr.")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["student_id"], "ST101")

    def test_find_students_by_display_name_fallback_to_name(self):
        students = [
            {"student_id": "ST101", "name": "Romel Jr.", "display_name": "", "active": "true"},
            {"student_id": "ST102", "name": "Juan", "display_name": "Juan Dela Cruz", "active": "true"},
        ]
        matches = find_students_by_display_name(students, "romel jr.")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["student_id"], "ST101")

    def test_find_students_by_display_name_fallback_to_chinese_name(self):
        students = [
            {"student_id": "ST101", "name": "Romel", "chinese_name": "杜榮瑪", "display_name": "", "active": "true"},
        ]
        matches = find_students_by_display_name(students, "杜榮瑪")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["student_id"], "ST101")

    @patch("app.find_student_by_line_user_id")
    def test_resolve_student_from_event_already_registered(self, mock_find):
        mock_find.return_value = {"student_id": "ST101", "name": "Romel Jr."}
        event = MagicMock()
        event.source.user_id = "U12345"
        student = resolve_student_from_event(event)
        self.assertIsNotNone(student)
        self.assertEqual(student["student_id"], "ST101")

    @patch("app.identify_or_register_student")
    @patch("app.find_student_by_line_user_id", return_value=None)
    def test_resolve_student_from_event_auto_connect(self, mock_find, mock_ident):
        from app import StudentIdentification
        mock_ident.return_value = StudentIdentification(
            status="registered",
            student={"student_id": "ST102", "name": "Juan"},
            display_name="Juan",
        )
        event = MagicMock()
        event.source.user_id = "U99999"
        student = resolve_student_from_event(event)
        self.assertIsNotNone(student)
        self.assertEqual(student["student_id"], "ST102")


class TestLanguageSettings(TestCase):
    def test_title_and_language_options(self):
        from bot.line_ui import language_settings_message
        import json
        card = initialization_message()
        content = json.dumps(card.contents.data)
        self.assertIn('"text": "CSIE Student"', content)
        self.assertNotIn('"text": "CSIE Student Portal"', content)
        menu = json.dumps(language_settings_message().contents.data)
        self.assertIn("action=set_language&language=en", menu)
        self.assertIn("action=set_language&language=zh-TW", menu)

    def test_saved_preference_and_default(self):
        from database.google_sheets import get_user_language, set_user_language
        sheet = MagicMock()
        sheet.get_all_values.return_value = [["LINE User ID", "Language"], ["U1", "zh-TW"]]
        with patch("database.google_sheets._ensure_named_sheet", return_value=sheet):
            self.assertEqual(get_user_language("U1"), "zh-TW")
            self.assertEqual(get_user_language("U2"), "en")
            set_user_language("U1", "en")
            sheet.update_cell.assert_called_once_with(2, 2, "en")
            set_user_language("U2", "zh-TW")
            sheet.append_row.assert_called_once_with(["U2", "zh-TW"], value_input_option="RAW")

    def test_ai_translates_only_visible_text(self):
        from bot.language import localize_message
        class FakeMessage:
            def to_dict(self):
                return {"type": "flex", "altText": "My Attendance", "contents": {
                    "type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [
                        {"type": "text", "text": "Student Name"},
                        {"type": "text", "text": "趙浩然"},
                        {"type": "text", "text": "S06674"},
                        {"type": "button", "action": {"type": "postback", "label": "View", "data": "action=view&id=S06674"}},
                    ]},
                }}
        def translate(texts, language):
            self.assertEqual(language, "zh-TW")
            self.assertNotIn("趙浩然", texts)
            self.assertNotIn("S06674", texts)
            return tuple("譯文" for _ in texts)
        with patch("database.google_sheets.get_user_language", return_value="zh-TW"), patch(
            "database.google_sheets.find_student_by_line_user_id", return_value={"chinese_name": "趙浩然", "student_id": "S06674"}
        ), patch("bot.language.translate_texts", side_effect=translate), patch(
            "linebot.v3.messaging.FlexMessage.from_dict", side_effect=lambda value: value, create=True
        ):
            result = localize_message(FakeMessage(), "U1")
        items = result["contents"]["body"]["contents"]
        self.assertEqual(items[0]["text"], "譯文")
        self.assertEqual(items[1]["text"], "趙浩然")
        self.assertEqual(items[3]["action"]["data"], "action=view&id=S06674")

    def test_translation_failure_preserves_message(self):
        from bot.language import localize_message
        with patch("database.google_sheets.get_user_language", return_value="zh-TW"), patch(
            "database.google_sheets.find_student_by_line_user_id", return_value=None
        ), patch("bot.language.translate_texts", side_effect=RuntimeError("Unavailable")):
            self.assertEqual(localize_message("My Attendance", "U1"), "My Attendance")

    def test_group_context_and_reset(self):
        from bot.language import private_language_context, recipient
        from types import SimpleNamespace
        @private_language_context
        def read(event):
            return recipient.get()
        self.assertEqual(read(SimpleNamespace(source=SimpleNamespace(type="user", user_id="U1"))), "U1")
        self.assertIsNone(read(SimpleNamespace(source=SimpleNamespace(type="group", user_id="U1"))))
        self.assertIsNone(recipient.get())


class TestAccountAuthorization(TestCase):
    def test_authorize_button_is_last_for_both_account_states(self):
        for student in (None, {"student_id": "ST101", "name": "Romel"}):
            card = initialization_message(student)
            button = card.contents.data["footer"]["contents"][-1]
            self.assertEqual(button["action"]["label"], "Authorize")
            self.assertEqual(button["action"]["data"], "action=authorize_account")

    def test_first_chat_saves_line_id_to_matching_roster_row(self):
        from app import identify_or_register_student
        from types import SimpleNamespace
        student = {"student_id": "ST101", "name": "Romel", "line_user_id": ""}
        event = SimpleNamespace(source=SimpleNamespace(user_id="U1", type="user"))
        with patch("app.find_student_by_line_user_id", return_value=None), patch(
            "app.get_line_display_name", return_value="Romel"
        ), patch("app.find_students_by_display_name", return_value=[student]), patch(
            "app.register_line_user"
        ) as register:
            result = identify_or_register_student(event)
        self.assertEqual(result.status, "registered")
        register.assert_called_once_with(student, "U1")
        self.assertEqual(result.student["line_user_id"], "U1")

    def test_authorization_persists_and_repeat_is_idempotent(self):
        from database.google_sheets import save_account_authorization
        sheet = MagicMock()
        sheet.get_all_values.return_value = [["LINE User ID", "Student ID", "Authorized At", "Terms Version"]]
        with patch("database.google_sheets.find_student_by_line_user_id", return_value={"student_id": "ST101"}), patch(
            "database.google_sheets._ensure_named_sheet", return_value=sheet
        ):
            save_account_authorization("U1", "ST101")
            values = sheet.append_row.call_args.args[0]
            self.assertEqual(values[:2], ["U1", "ST101"])
            self.assertTrue(values[2])
            self.assertEqual(values[3], "2026-10-12")
            sheet.get_all_values.return_value.append(values)
            save_account_authorization("U1", "ST101")
            sheet.append_row.assert_called_once()

    def test_authorization_rejects_wrong_student(self):
        from database.google_sheets import save_account_authorization
        with patch("database.google_sheets.find_student_by_line_user_id", return_value={"student_id": "ST102"}), patch(
            "database.google_sheets._ensure_named_sheet"
        ) as sheet:
            with self.assertRaises(ValueError):
                save_account_authorization("U1", "ST101")
            sheet.assert_not_called()


class TestSpamProtection(TestCase):
    def test_second_limit_and_boundary(self):
        from bot.rate_limit import EventRateLimiter
        limit = EventRateLimiter()
        self.assertEqual(limit.check("U1", "e1", now=0), (True, False))
        self.assertEqual(limit.check("U1", "e2", now=0.1), (False, False))
        self.assertEqual(limit.check("U1", "e3", now=0.2), (False, False))
        self.assertEqual(limit.check("U1", "e4", now=0.3), (False, False))
        self.assertTrue(limit.check("U2", "e5", now=0.3)[0])
        self.assertTrue(limit.check("U1", "e6", now=1)[0])

    def test_minute_limit_and_recovery(self):
        from bot.rate_limit import EventRateLimiter
        limit = EventRateLimiter()
        for i in range(20):
            self.assertTrue(limit.check("U1", now=i * 2)[0])
        self.assertFalse(limit.check("U1", now=40)[0])
        self.assertTrue(limit.check("U1", now=60)[0])

    def test_duplicate_event_does_not_consume_quota(self):
        from bot.rate_limit import EventRateLimiter
        limit = EventRateLimiter()
        self.assertTrue(limit.check("U1", "event1", now=0)[0])
        self.assertEqual(limit.check("U1", "event1", now=0.1), (False, False))
        self.assertTrue(limit.check("U1", "event2", now=1)[0])

    def test_parallel_requests_share_limit(self):
        from bot.rate_limit import EventRateLimiter
        from concurrent.futures import ThreadPoolExecutor
        limit = EventRateLimiter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda i: limit.check("U1", str(i), now=0), range(8)))
        self.assertEqual(sum(allowed for allowed, _ in results), 1)
        self.assertEqual(sum(notify for _, notify in results), 0)

    def test_user_cache_is_bounded(self):
        from bot.rate_limit import EventRateLimiter
        limit = EventRateLimiter(max_users=2)
        for i in range(3):
            limit.check(str(i), now=i)
        self.assertEqual(len(limit.users), 2)


class TestLeaveWorkdaysAndAutofill(TestCase):
    def test_rest_day_rejected_and_override_allowed(self):
        from attendance.leave_message import validate_leave_workday
        from scheduler.work_calendar import WORKDAY_OVERRIDES, DAY_OFF_OVERRIDES
        rest_day = date(2026, 10, 12)
        with self.assertRaisesRegex(ValueError, "rest day"):
            validate_leave_workday(rest_day)
        with patch("scheduler.work_calendar.WORKDAY_OVERRIDES", WORKDAY_OVERRIDES | {rest_day}):
            validate_leave_workday(rest_day)
        work_day = date(2026, 10, 14)
        with patch("scheduler.work_calendar.DAY_OFF_OVERRIDES", DAY_OFF_OVERRIDES | {work_day}):
            with self.assertRaises(ValueError):
                validate_leave_workday(work_day)

    def test_all_write_paths_reject_rest_day_before_sheet_access(self):
        from database.google_sheets import append_attendance_row, upsert_attendance_record
        with patch("database.google_sheets.ensure_attendance_sheet") as sheet, patch(
            "database.google_sheets._attendance_header_layout"
        ) as layout:
            with self.assertRaisesRegex(ValueError, "rest day"):
                append_attendance_row(["ST101", "Name", "2026-10-12", "病假", "Confirmed", "sick leave"])
            with self.assertRaisesRegex(ValueError, "rest day"):
                upsert_attendance_record("ST101", "Name", date(2026, 10, 12), "事假", "U1")
            sheet.assert_not_called()
            layout.assert_not_called()

    def test_templates_open_keyboard_and_default_to_next_workday(self):
        with patch("bot.line_ui.datetime") as clock:
            clock.now.return_value.date.return_value = date(2026, 10, 12)
            card = leave_request_menu_message()
        buttons = [item for item in card.contents.data["body"]["contents"] if item.get("type") == "button"]
        self.assertEqual(len(buttons), 5)
        for button in buttons:
            action = button["action"]
            self.assertEqual(action["inputOption"], "openKeyboard")
            self.assertIn("2026-10-14", action["fillInText"])
            self.assertIn("[your reason]", action["fillInText"])
            self.assertLessEqual(len(action["fillInText"]), 300)

    def test_all_form_categories_parse_and_blank_reason_rejected(self):
        from attendance.leave_message import LEAVE_TEMPLATE_CATEGORIES, parse_leave_template
        for category, status in LEAVE_TEMPLATE_CATEGORIES.items():
            result = parse_leave_template(f"Leave 2026-10-14 {category} Reason: Family appointment")
            self.assertEqual(result.status, status)
        for reason in ("", "[your reason]", "<reason>"):
            with self.assertRaisesRegex(ValueError, "reason"):
                parse_leave_template(f"Leave 2026-10-14 Sick Leave Reason: {reason}")
        self.assertIsNone(parse_leave_template("Hello"))


class TestInitializationGuidance(TestCase):
    def test_no_redundant_open_rich_menu_buttons(self):
        import json
        from bot.line_ui import terms_agreement_confirmed_message
        student = {"student_id": "ST101", "name": "Romel"}
        for card in (welcome_message(student), initialization_message(student), initialization_message(), terms_agreement_confirmed_message(student)):
            self.assertNotIn("Open Rich Menu", json.dumps(card.contents.data))

    def test_name_mismatch_shows_exact_sheet_correction(self):
        import json
        card = initialization_message(display_name="Quidall/dharls", error_status="unmatched")
        text = json.dumps(card.contents.data)
        self.assertIn("LINE Display Name", text)
        self.assertIn("Quidall/dharls", text)
        self.assertIn("Name Not Matched", text)
        self.assertNotIn("Pending Verification", text)
        self.assertIn("does not approve a name mismatch", text)

    def test_distinct_authorization_failures(self):
        import json
        for status, expected in (("ambiguous", "duplicate"), ("conflict", "different LINE account"), ("profile_unavailable", "retrieve your LINE profile")):
            with self.subTest(status=status):
                card = initialization_message(display_name="Name", error_status=status)
                self.assertIn(expected, json.dumps(card.contents.data))


class TestNamesRemainOriginal(TestCase):
    def test_unmatched_card_never_translates_profile_name(self):
        from bot.language import localize_message
        profile_name = "奎姐兒/dharls"
        card = initialization_message(display_name=profile_name, error_status="unmatched")
        class FakeMessage:
            def to_dict(self):
                return {"type": "flex", "altText": card.alt_text, "contents": card.contents.data}
        def translate(texts, language):
            self.assertFalse(any(profile_name in text for text in texts))
            return tuple(text.replace("Your LINE profile name", "您的 LINE 個人檔案名稱") for text in texts)
        with patch("database.google_sheets.get_user_language", return_value="zh-TW"), patch(
            "database.google_sheets.find_student_by_line_user_id", return_value=None
        ), patch("bot.language.translate_texts", side_effect=translate), patch(
            "linebot.v3.messaging.FlexMessage.from_dict", side_effect=lambda payload: payload, create=True
        ):
            result = localize_message(FakeMessage(), "U1")
        import json
        self.assertIn(profile_name, json.dumps(result, ensure_ascii=False))
        self.assertNotIn("Quidall", json.dumps(result))

    def test_english_unmatched_name_is_not_sent_to_ai(self):
        from bot.language import localize_message
        card = initialization_message(display_name="奎姐兒/dharls", error_status="unmatched")
        class FakeMessage:
            def to_dict(self):
                return {"type": "flex", "altText": card.alt_text, "contents": card.contents.data}
        message = FakeMessage()
        # The Chinese name also appears in the English correction instructions;
        # those embedded occurrences must be masked before reaching AI.
        def translate(texts, language):
            self.assertEqual(language, "en")
            self.assertFalse(any("奎姐兒" in text for text in texts))
            return texts
        with patch("database.google_sheets.get_user_language", return_value="en"), patch(
            "database.google_sheets.find_student_by_line_user_id", return_value=None
        ), patch("bot.language.translate_texts", side_effect=translate), patch(
            "linebot.v3.messaging.FlexMessage.from_dict", side_effect=lambda payload: payload, create=True
        ):
            result = localize_message(message, "U1")
        import json
        self.assertIn("奎姐兒/dharls", json.dumps(result, ensure_ascii=False))

    def test_slash_spacing_matches_but_different_names_do_not(self):
        from attendance.student_directory import find_students_by_display_name
        students = [{"student_id": "ST101", "display_name": "奎姐兒 /dharls"}]
        self.assertEqual(len(find_students_by_display_name(students, "奎姐兒/dharls")), 1)
        self.assertEqual(find_students_by_display_name(students, "Different/dharls"), [])

    def test_slash_normalization_keeps_duplicate_matches_ambiguous(self):
        from attendance.student_directory import find_students_by_display_name
        students = [{"student_id": "ST101", "display_name": "Name / nick"}, {"student_id": "ST102", "display_name": "Name/nick"}]
        self.assertEqual(len(find_students_by_display_name(students, "Name/nick")), 2)


class TestCompactAuthorizationCard(TestCase):
    def test_bottom_buttons_and_no_language_option(self):
        import json
        from bot.line_ui import DEDUCTION_RED
        for student in (None, {"student_id": "ST101", "name": "Romel"}):
            card = initialization_message(student)
            data = card.contents.data
            buttons = data["footer"]["contents"]
            self.assertEqual(buttons[0]["action"]["label"], "Terms & Usage")
            self.assertEqual(buttons[0]["action"]["data"], "action=view_terms")
            self.assertEqual(buttons[-1]["action"]["label"], "Authorize")
            self.assertEqual(buttons[-1]["color"], DEDUCTION_RED)
            self.assertNotIn("language_settings", json.dumps(data))
            self.assertNotIn("Terms & Usage Notice", json.dumps(data))
            self.assertIsNone(card.quick_reply)

    def test_complete_supplied_terms_fit_separate_bubbles(self):
        import json
        import re
        from pathlib import Path
        from bot.line_ui import terms_of_use_message
        card = terms_of_use_message()
        data = card.contents.data
        self.assertEqual(data["type"], "carousel")
        bubbles = data["contents"]
        self.assertLessEqual(len(bubbles), 12)
        displayed = "\n\n".join(item["text"] for bubble in bubbles for item in bubble["body"]["contents"][1:])
        policy = (Path(__file__).resolve().parent.parent / "assets" / "terms.md").read_text()
        for paragraph in policy.split("\n\n"):
            normalized = re.sub(r"^#{1,6}\s*", "", paragraph.strip(), flags=re.MULTILINE).replace("**", "").replace("*", "")
            if normalized and normalized != "---":
                self.assertIn(normalized, displayed)
        for bubble in bubbles:
            self.assertLess(len(json.dumps(bubble).encode()), 30000)
            for item in bubble["body"]["contents"]:
                self.assertLessEqual(len(item["text"]), 2000)
        self.assertEqual(bubbles[-1]["footer"]["contents"][-1]["action"]["label"], "Authorize")


class TestPrivateCardDelivery(TestCase):
    def test_group_and_room_responses_never_use_public_tokens(self):
        from bot.delivery import private_responses
        from types import SimpleNamespace
        from app import reply_to_line
        @private_responses
        def respond(event):
            return reply_to_line(event.reply_token, "Private result")
        for source_type in ("group", "room"):
            with patch("app.push_to_line", return_value=True) as push, patch("app.ApiClient") as api:
                event = SimpleNamespace(source=SimpleNamespace(type=source_type, user_id="U1"), reply_token="PUBLIC_TOKEN")
                respond(event)
                push.assert_called_once_with("U1", "Private result")
                api.assert_not_called()

    def test_group_push_failure_has_no_public_fallback(self):
        from bot.delivery import destination, ReplyDestination
        from app import reply_to_line
        token = destination.set(ReplyDestination("U1", False))
        try:
            with patch("app.push_to_line", return_value=False), patch("app.ApiClient") as api:
                self.assertFalse(reply_to_line("PUBLIC_TOKEN", "Sensitive result"))
                api.assert_not_called()
        finally:
            destination.reset(token)

    def test_unknown_sender_is_silent(self):
        from bot.delivery import destination, ReplyDestination
        from app import reply_to_line
        token = destination.set(ReplyDestination(None, False))
        try:
            with patch("app.push_to_line") as push, patch("app.ApiClient") as api:
                self.assertFalse(reply_to_line("PUBLIC_TOKEN", "Error"))
                push.assert_not_called()
                api.assert_not_called()
        finally:
            destination.reset(token)

    def test_private_reply_is_a_card(self):
        from bot.delivery import destination, ReplyDestination
        from app import reply_to_line
        from types import SimpleNamespace
        token = destination.set(ReplyDestination("U1", True))
        try:
            with patch("app.ApiClient"), patch("app.MessagingApi") as api, patch(
                "app.localize_message", side_effect=lambda message: message
            ), patch("app.ReplyMessageRequest", side_effect=lambda **args: SimpleNamespace(**args)):
                self.assertTrue(reply_to_line("PRIVATE_TOKEN", "Ticket Created\n\nYour request was saved."))
                request = api.return_value.reply_message.call_args.kwargs["reply_message_request"]
                self.assertEqual(request.reply_token, "PRIVATE_TOKEN")
                self.assertEqual(request.messages[0].contents.data["type"], "bubble")
        finally:
            destination.reset(token)

    def test_push_accepts_only_user_ids_and_sends_cards(self):
        from app import push_to_line
        from types import SimpleNamespace
        with patch("app.ApiClient"), patch("app.MessagingApi") as api, patch(
            "app.localize_message", side_effect=lambda message, user_id: message
        ), patch("app.PushMessageRequest", side_effect=lambda **args: SimpleNamespace(**args)):
            self.assertFalse(push_to_line("Cgroup", "Sensitive data"))
            api.assert_not_called()
            self.assertTrue(push_to_line("U1", "Saved"))
            request = api.return_value.push_message.call_args.kwargs["push_message_request"]
            self.assertEqual(request.to, "U1")
            self.assertEqual(request.messages[0].contents.data["type"], "bubble")

    def test_long_response_card_preserves_all_text(self):
        from bot.line_ui import response_card_message
        text = "A" * 6000
        data = response_card_message(text).contents.data
        displayed = "".join(item["text"] for bubble in data["contents"] for item in bubble["body"]["contents"] if item.get("text") != "CSIE Student" and "text" in item)
        self.assertEqual(displayed, text)

    def test_daily_report_goes_to_configured_group(self):
        import importlib
        with patch.dict(sys.modules, {"apscheduler": MagicMock(), "apscheduler.schedulers": MagicMock(), "apscheduler.schedulers.background": MagicMock()}):
            jobs = importlib.import_module("scheduler.daily_report")
        with patch.object(jobs, "is_workday", return_value=True), patch.object(
            jobs, "generate_daily_report", return_value="Class report"
        ), patch("app.send_report_to_group", return_value=True) as send, patch("app.push_to_line") as private:
            jobs.daily_attendance_job()
        send.assert_called_once_with("Class report")
        private.assert_not_called()


class TestTicketCodeIsInert(TestCase):
    def test_python_and_formula_payloads_stored_literally(self):
        from database.google_sheets import create_ticket
        for payload in ('eval("__import__(\'os\').system(\'echo exploited\')")', '=IMPORTXML("https://example.invalid", "//text()")'):
            sheet = MagicMock()
            with patch("database.google_sheets._ensure_named_sheet", return_value=sheet), patch("os.system") as system:
                create_ticket("ST101", "U1", payload)
                values = sheet.append_row.call_args.args[0]
                self.assertEqual(values[4], payload)
                self.assertEqual(sheet.append_row.call_args.kwargs["value_input_option"], "RAW")
                system.assert_not_called()

    def test_oversized_ticket_rejected_before_sheet_access(self):
        from database.google_sheets import create_ticket
        with patch("database.google_sheets._ensure_named_sheet") as sheet:
            with self.assertRaises(ValueError):
                create_ticket("ST101", "U1", "x" * 4001)
            sheet.assert_not_called()


class TestSingleResponseBursts(TestCase):
    def test_five_attendance_requests_produce_one_response(self):
        from bot.rate_limit import EventRateLimiter, rate_limited
        from types import SimpleNamespace
        response = MagicMock()
        @rate_limited
        def handle(event):
            response("My Attendance")
        with patch("bot.rate_limit.limiter", EventRateLimiter()), patch("app.reply_to_line") as warning:
            for i in range(5):
                handle(SimpleNamespace(source=SimpleNamespace(user_id="U1"), timestamp=100000 + i * 100, webhook_event_id=f"event-{i}"))
            response.assert_called_once_with("My Attendance")
            warning.assert_not_called()
            handle(SimpleNamespace(source=SimpleNamespace(user_id="U1"), timestamp=101000, webhook_event_id="later"))
            self.assertEqual(response.call_count, 2)

    def test_slow_webhook_processing_does_not_turn_burst_into_five_replies(self):
        from bot.rate_limit import EventRateLimiter
        limit = EventRateLimiter()
        allowed = [limit.check("U1", str(i), now=i * 3, request_time=100 + i * 0.1)[0] for i in range(5)]
        self.assertEqual(allowed, [True, False, False, False, False])

    def test_out_of_order_requests_do_not_bypass_limit(self):
        from bot.rate_limit import EventRateLimiter
        limit = EventRateLimiter()
        self.assertTrue(limit.check("U1", request_time=100)[0])
        self.assertEqual(limit.check("U1", request_time=90), (False, False))


class TestPaidAnnualLeave(TestCase):
    def test_annual_leave_counts_as_attended_without_absence(self):
        entries = {date(2026, 10, 7): "出席", date(2026, 10, 8): "特休", date(2026, 10, 23): "特休"}
        summary = TestAttendanceCalculation().summary(entries)
        self.assertEqual(summary["attended_days"], 2)
        self.assertEqual(summary["absent_days"], 0)
        self.assertEqual(summary["attendance_pct"], 100)
        self.assertEqual(summary["remaining_scheduled_workdays"], 1)

    def test_annual_leave_today_keeps_its_label_and_full_attendance(self):
        summary = TestAttendanceCalculation().summary({date(2026, 10, 14): "特休"}, today=date(2026, 10, 14))
        self.assertEqual(summary["today_status"], "Annual Leave")
        self.assertEqual(summary["attendance_pct"], 100)
        self.assertEqual(summary["absent_days"], 0)

    def test_salary_annual_leave_has_same_pay_as_present(self):
        from database.google_sheets import get_monthly_attendance_counts
        day = date(2026, 10, 7)
        with patch("database.google_sheets.datetime") as clock, patch(
            "database.google_sheets.get_monthly_report_entries"
        ) as entries:
            clock.now.return_value.date.return_value = date(2026, 10, 12)
            entries.return_value = {day: "出席"}
            present_pay = calculate_salary(*get_monthly_attendance_counts("ST101", day))
            entries.return_value = {day: "特休", date(2026, 10, 23): "特休"}
            annual_pay = calculate_salary(*get_monthly_attendance_counts("ST101", day))
        self.assertEqual(annual_pay, present_pay)
        self.assertEqual(annual_pay.total_hours, 8)

    def test_annual_leave_report_does_not_reduce_attending_count(self):
        from attendance.attendance import AttendanceRecord
        from attendance.report import build_report
        report = build_report(report_date=date(2026, 10, 7), total_students=1, expected_students=1, records=[
            AttendanceRecord(student_id="ST101", status="special_leave", attendance_date=date(2026, 10, 7)),
        ])
        self.assertIn("實到人數：1", report)
        self.assertIn("特休：1人", report)


class TestAdminPortal(TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin", "LINE_CHANNEL_SECRET": "secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.day = date(2026, 10, 14)
        self.student = {"student_id": "ST101", "name": "Student", "chinese_name": "學生"}
        self.ticket = {"Ticket ID": "ABCD", "Student ID": "ST101", "LINE User ID": "Ustudent", "Status": "OPEN", "Message": "Please correct 2026-10-14 to sick leave.", "Admin Note": ""}

    def data(self, action, **values):
        from urllib.parse import parse_qs
        from bot.admin_portal import action as build_action
        return parse_qs(build_action(action, **values))

    def preview(self, ticket=None, status="sick"):
        from bot.admin_portal import preview_message
        with patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "出席"}), patch(
            "database.google_sheets.get_attendance_record", return_value=None
        ), patch("database.google_sheets.get_ticket", return_value=self.ticket):
            return preview_message("Uadmin", self.student, self.day, status, ticket)

    def test_admin_portal_has_requested_six_actions(self):
        from bot.admin_portal import portal_message
        labels = [item["action"]["label"] for item in portal_message().contents.data["footer"]["contents"]]
        self.assertIn("Attendance Status", labels)
        self.assertIn("Help Center · Tickets", labels)
        self.assertNotIn("Leave Request", labels)
        self.assertEqual(len(labels), 6)

    def test_every_admin_action_rejects_nonadmin(self):
        from bot.admin_portal import handle_postback
        for action in ("admin_tickets", "admin_ticket", "admin_attendance", "admin_student", "admin_preview", "admin_apply", "admin_ticket_commit"):
            with self.subTest(action=action), patch("database.google_sheets.get_ticket") as read, patch("database.google_sheets.upsert_attendance_record") as write:
                with self.assertRaisesRegex(ValueError, "administrators only"):
                    handle_postback(self.data(action), "Ustudent")
                read.assert_not_called()
                write.assert_not_called()

    def test_preview_does_not_mutate_database(self):
        with patch("database.google_sheets.upsert_attendance_record") as write:
            preview = self.preview()
        self.assertEqual(preview.contents.data["footer"]["contents"][0]["action"]["label"], "Confirm Change")
        write.assert_not_called()

    def test_confirmed_change_updates_both_log_and_monthly_report(self):
        from urllib.parse import parse_qs
        from bot.admin_portal import handle_postback
        data = parse_qs(self.preview(ticket="ABCD").contents.data["footer"]["contents"][0]["action"]["data"])
        with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch(
            "database.google_sheets.get_monthly_report_entries", return_value={self.day: "出席"}
        ), patch("database.google_sheets.get_attendance_record", return_value=None), patch(
            "database.google_sheets.get_ticket", return_value=self.ticket
        ), patch("database.google_sheets.upsert_attendance_record", return_value={"action_id": "AUDIT1"}) as log, patch(
            "database.google_sheets.update_monthly_report_cell", return_value=True
        ) as grid, patch("bot.admin_portal.save_ticket_note") as note, patch("database.google_sheets.update_ticket") as close:
            result = handle_postback(data, "Uadmin")
        self.assertIn("Attendance Updated", result.alt_text)
        self.assertEqual(log.call_args.args[3], "病假")
        self.assertEqual(log.call_args.args[4], "Uadmin")
        grid.assert_called_once_with("ST101", self.day, "病假")
        self.assertIn("AUDIT1", note.call_args.args[1])
        close.assert_not_called()

    def test_changed_record_blocks_old_confirmation(self):
        from urllib.parse import parse_qs
        from bot.admin_portal import handle_postback
        data = parse_qs(self.preview().contents.data["footer"]["contents"][0]["action"]["data"])
        with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch(
            "database.google_sheets.get_monthly_report_entries", return_value={self.day: "事假"}
        ), patch("database.google_sheets.get_attendance_record", return_value=None), patch("database.google_sheets.upsert_attendance_record") as write:
            with self.assertRaisesRegex(ValueError, "changed since"):
                handle_postback(data, "Uadmin")
            write.assert_not_called()

    def test_tampered_expired_and_cross_admin_confirmations_rejected(self):
        from urllib.parse import parse_qs
        from bot.admin_portal import verify_action
        data = parse_qs(self.preview().contents.data["footer"]["contents"][0]["action"]["data"])
        with self.assertRaises(ValueError):
            verify_action("Uotheradmin", data)
        tampered = {**data, "status": ["present"]}
        with self.assertRaises(ValueError):
            verify_action("Uadmin", tampered)
        with patch("bot.admin_portal.time.time", return_value=int(data["expires"][0]) + 1):
            with self.assertRaises(ValueError):
                verify_action("Uadmin", data)

    def test_manual_remove_leave_sets_present(self):
        from bot.admin_portal import preview_message, handle_postback
        from urllib.parse import parse_qs
        with patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假"}), patch("database.google_sheets.get_attendance_record", return_value=None):
            card = preview_message("Uadmin", self.student, self.day, "present", None)
            data = parse_qs(card.contents.data["footer"]["contents"][0]["action"]["data"])
            with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch(
                "database.google_sheets.upsert_attendance_record", return_value={"action_id": "AUDIT"}
            ) as log, patch("database.google_sheets.update_monthly_report_cell", return_value=True) as grid:
                handle_postback(data, "Uadmin")
            self.assertEqual(log.call_args.args[3], "出席")
            grid.assert_called_once_with("ST101", self.day, "出席")

    def test_partial_report_failure_does_not_resolve_ticket(self):
        from bot.admin_portal import handle_postback
        from urllib.parse import parse_qs
        data = parse_qs(self.preview(ticket="ABCD").contents.data["footer"]["contents"][0]["action"]["data"])
        with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch(
            "database.google_sheets.get_monthly_report_entries", return_value={self.day: "出席"}
        ), patch("database.google_sheets.get_attendance_record", return_value=None), patch("database.google_sheets.get_ticket", return_value=self.ticket), patch(
            "database.google_sheets.upsert_attendance_record", return_value={"action_id": "AUDIT"}
        ), patch("database.google_sheets.update_monthly_report_cell", return_value=False), patch("database.google_sheets.update_ticket") as close:
            with self.assertRaisesRegex(RuntimeError, "Monthly Report"):
                handle_postback(data, "Uadmin")
            close.assert_not_called()

    def test_ticket_resolution_is_confirmed_and_notifies_student(self):
        from bot.admin_portal import handle_postback
        from urllib.parse import parse_qs
        with patch("database.google_sheets.get_ticket", return_value=self.ticket), patch("database.google_sheets.find_student_by_id", return_value=self.student), patch("database.google_sheets.update_ticket", return_value=True) as update:
            preview = handle_postback(self.data("admin_ticket_resolve", ticket="ABCD"), "Uadmin")
            update.assert_not_called()
            data = parse_qs(preview.contents.data["footer"]["contents"][0]["action"]["data"])
            notice = MagicMock()
            result = handle_postback(data, "Uadmin", notify=notice)
            update.assert_called_once()
            self.assertTrue(update.call_args.kwargs["close"])
            self.assertIn("ABCD", notice.call_args.args[1])
            self.assertEqual(notice.call_args.args[0], "Ustudent")

    def test_closed_ticket_cannot_edit_another_student(self):
        from bot.admin_portal import handle_postback
        wrong_ticket = {**self.ticket, "Student ID": "ST102"}
        with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch("database.google_sheets.get_ticket", return_value=wrong_ticket):
            with self.assertRaisesRegex(ValueError, "different student"):
                handle_postback(self.data("admin_student", student="ST101", ticket="ABCD"), "Uadmin")

    def test_date_picker_selects_requested_date(self):
        from bot.admin_portal import handle_postback
        selected = date(2026, 10, 23)
        with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch("database.google_sheets.get_monthly_report_entries", return_value={selected: "病假"}):
            card = handle_postback(self.data("admin_student", student="ST101"), "Uadmin", params={"date": selected.isoformat()})
        import json
        self.assertIn(selected.isoformat(), json.dumps(card.contents.data))

    def test_current_report_preview_and_paid_leave_summary(self):
        from bot.admin_portal import daily_report_message, attendance_message
        from attendance.report import DailyReportText, GroupReportText
        rows = [{"student_id": str(index), "name": "Student", "type": "特休"} for index in range(12)]
        with patch("database.google_sheets.get_daily_monthly_report", return_value=rows), \
             patch("database.google_sheets.get_report_students", return_value=({}, 12)), \
             patch("bot.commands._records_for_date", return_value=[]), \
             patch("attendance.time_out.save_morning") as save:
            report = daily_report_message(self.day)
            summary = attendance_message(self.day)
        self.assertIsInstance(report, DailyReportText)
        self.assertNotIsInstance(report, GroupReportText)
        self.assertIn("應到人數：12", report)
        save.assert_not_called()
        labels = [button["action"]["label"] for button in summary.contents.data["footer"]["contents"]]
        self.assertEqual(labels, ["View Daily Report", "Edit Leave", "Choose Date"])
        stat_rows = summary.contents.data["body"]["contents"]
        values = {row["contents"][0]["text"]: row["contents"][1]["text"] for row in stat_rows if row.get("layout") == "horizontal"}
        self.assertEqual(values["Present / Paid Leave"], "12")
        self.assertEqual(values["Absences"], "0")


class TestAdminRichMenu(TestCase):
    def test_admin_tile_names_and_routes(self):
        menu = build_rich_menu_request(admin=True)
        self.assertEqual(menu.name, "CSIE Admin Portal")
        self.assertEqual(menu.areas[4].action.label, "Attendance Status")
        self.assertEqual(menu.areas[4].action.data, "action=admin_attendance")
        self.assertEqual(menu.areas[5].action.data, "action=admin_tickets")
        student = build_rich_menu_request()
        self.assertEqual(student.areas[4].action.label, "Leave Request")

    def test_admin_menu_is_linked_per_user_without_changing_default(self):
        import bot.rich_menu as menus
        from types import SimpleNamespace
        api = MagicMock()
        api.get_rich_menu_list.return_value.richmenus = [SimpleNamespace(name="CSIE Admin Portal (hash-layout)", size=SimpleNamespace(width=2500, height=1686), rich_menu_id="ADMIN_MENU")]
        with patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}), patch.object(menus, "get_image_hash", return_value="hash"), patch.object(menus, "get_layout_hash", return_value="layout"), patch.object(menus, "prepare_menu_image", return_value=(b"image", "image/png", 2500, 1686)), patch.object(menus, "ApiClient"), patch.object(menus, "MessagingApi", return_value=api), patch.object(menus, "_ADMIN_MENU_ID", None):
            self.assertEqual(menus.setup_rich_menu(admin=True), "ADMIN_MENU")
            api.link_rich_menu_id_to_user.assert_called_once_with("Uadmin", "ADMIN_MENU")
            api.set_default_rich_menu.assert_not_called()
            api.delete_rich_menu.assert_not_called()

    def test_removed_admin_loses_per_user_admin_menu(self):
        import bot.rich_menu as menus
        api = MagicMock()
        api.get_rich_menu_id_of_user.return_value.rich_menu_id = "ADMIN_MENU"
        with patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": ""}), patch.object(menus, "_ADMIN_MENU_ID", "ADMIN_MENU"), patch.object(menus, "_MENU_ROLE_CACHE", {}), patch.object(menus, "ApiClient"), patch.object(menus, "MessagingApi", return_value=api):
            menus.sync_user_menu("Uformeradmin")
            api.unlink_rich_menu_id_from_user.assert_called_once_with("Uformeradmin")

    def test_daily_report_reads_month_block_once_for_all_students(self):
        from database.google_sheets import get_daily_monthly_report
        from attendance.report import StudentDisplay
        sheet = MagicMock()
        sheet.get_all_values.return_value = [
            ["", "", "October 2026"], ["", "", "1", "2", "3", "4", "7"],
            ["ST101", "One", "", "半天", "病假", "遲到", "特休"],
            ["ST102", "Two", "", "", "", "", "事假"],
        ]
        students = {sid: StudentDisplay(student_id=sid, display_name=sid) for sid in ("ST101", "ST102")}
        with patch("database.google_sheets._get_monthly_report_sheet", return_value=sheet), patch("database.google_sheets.get_report_students", return_value=(students, 2)):
            rows = get_daily_monthly_report(date(2026, 10, 7))
        self.assertEqual([row["type"] for row in rows], ["特休", "事假"])
        sheet.get_all_values.assert_called_once()


class TestAdminSafeguards(TestCase):
    setUp = TestAdminPortal.setUp
    data = TestAdminPortal.data
    preview = TestAdminPortal.preview

    def test_rest_day_leave_preview_rejected(self):
        from bot.admin_portal import preview_message
        with self.assertRaisesRegex(ValueError, "rest day"):
            preview_message("Uadmin", self.student, date(2026, 10, 12), "sick", None)

    def test_closed_ticket_blocks_correction(self):
        from bot.admin_portal import preview_message
        with patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "出席"}), patch(
            "database.google_sheets.get_attendance_record", return_value=None
        ), patch("database.google_sheets.get_ticket", return_value={**self.ticket, "Status": "CLOSED"}):
            with self.assertRaisesRegex(ValueError, "closed"):
                preview_message("Uadmin", self.student, self.day, "sick", "ABCD")

    def test_paid_annual_leave_preview_preserves_category(self):
        import json
        preview = self.preview(status="annual")
        self.assertIn("Annual Leave", json.dumps(preview.contents.data))
        self.assertIn("Paid", json.dumps(preview.contents.data))

    def test_ticket_change_blocks_stale_resolution(self):
        from bot.admin_portal import handle_postback
        from urllib.parse import parse_qs
        with patch("database.google_sheets.get_ticket", return_value=self.ticket):
            preview = handle_postback(self.data("admin_ticket_resolve", ticket="ABCD"), "Uadmin")
        data = parse_qs(preview.contents.data["footer"]["contents"][0]["action"]["data"])
        with patch("database.google_sheets.get_ticket", return_value={**self.ticket, "Admin Note": "Changed by another admin"}), patch(
            "database.google_sheets.update_ticket"
        ) as write:
            with self.assertRaisesRegex(ValueError, "changed"):
                handle_postback(data, "Uadmin")
            write.assert_not_called()

    def test_student_portal_has_clickable_six_actions(self):
        from bot.line_ui import portal_menu_message
        buttons = [row for row in portal_menu_message().contents.data["body"]["contents"] if row.get("type") == "button"]
        self.assertEqual(len(buttons), 6)
        labels = [button["action"]["label"] for button in buttons]
        self.assertIn("Leave Request", labels)
        self.assertNotIn("Attendance Status", labels)

    def test_ticket_resolution_note_and_actor_are_stored(self):
        from database.google_sheets import update_ticket
        sheet = MagicMock()
        sheet.get_all_values.return_value = [["Ticket ID"], ["ABCD", "", "ST101", "Ustudent", "Request", "OPEN"]]
        with patch("database.google_sheets._ensure_named_sheet", return_value=sheet):
            self.assertTrue(update_ticket("ABCD", "Uadmin", close=True, note="Attendance corrected."))
        values = sheet.update.call_args.kwargs["values"][0]
        self.assertEqual(values[0:2], ["CLOSED", "Uadmin"])
        self.assertTrue(values[2])
        self.assertEqual(values[3], "Attendance corrected.")


class TestAdminReportIdentityTranslation(TestCase):
    def test_other_students_names_are_protected_in_admin_reports(self):
        from bot.language import localize_message
        from attendance.report import StudentDisplay
        class FakeMessage:
            def to_dict(self):
                return {"type": "flex", "altText": "Report", "contents": {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "ST101 · 奎姐兒\n病假"}]}}}
        def translate(texts, language):
            self.assertFalse(any("奎姐兒" in text or "ST101" in text for text in texts))
            return tuple(text.replace("病假", "Sick Leave") for text in texts)
        with patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}), patch("database.google_sheets.get_user_language", return_value="en"), patch(
            "database.google_sheets.find_student_by_line_user_id", return_value=None
        ), patch("database.google_sheets.get_report_students", return_value=({"ST101": StudentDisplay("ST101", "奎姐兒")}, 1)), patch(
            "bot.language.translate_texts", side_effect=translate
        ), patch("linebot.v3.messaging.FlexMessage.from_dict", side_effect=lambda value: value, create=True):
            result = localize_message(FakeMessage(), "Uadmin")
        self.assertEqual(result["contents"]["body"]["contents"][0]["text"], "ST101 · 奎姐兒\nSick Leave")


class TestDailyReportPlainText(TestCase):
    def test_generated_report_has_plain_text_marker(self):
        from attendance.report import build_report, DailyReportText
        report = build_report(report_date=date(2026, 10, 9), total_students=41, expected_students=41, records=[])
        self.assertIsInstance(report, DailyReportText)
        self.assertEqual(report, "「2026/10/09」（禮拜五）\n\n應到人數：41\n實到人數：41")

    def test_report_reply_and_push_bypass_cards_and_translation(self):
        from attendance.report import DailyReportText
        from app import reply_to_line, push_to_line
        from bot.delivery import destination, ReplyDestination
        from types import SimpleNamespace
        report = DailyReportText("「2026/10/09」（禮拜五）\n\n應到人數：41\n實到人數：41")
        token = destination.set(ReplyDestination("Uadmin", True))
        try:
            with patch("app.ApiClient"), patch("app.MessagingApi") as api, patch("app.response_card_message") as card, patch("app.localize_message") as translate, patch(
                "app.ReplyMessageRequest", side_effect=lambda **args: SimpleNamespace(**args)
            ), patch("app.PushMessageRequest", side_effect=lambda **args: SimpleNamespace(**args)), patch("app.TextMessage", side_effect=lambda text: SimpleNamespace(text=text)):
                self.assertTrue(reply_to_line("PRIVATE_TOKEN", report))
                self.assertTrue(push_to_line("Uadmin", report))
                replied = api.return_value.reply_message.call_args.kwargs["reply_message_request"]
                pushed = api.return_value.push_message.call_args.kwargs["push_message_request"]
                self.assertEqual(replied.messages[0].text, report)
                self.assertEqual(pushed.messages[0].text, report)
                card.assert_not_called()
                translate.assert_not_called()
        finally:
            destination.reset(token)


class TestTimeOutReport(TestCase):
    def setUp(self):
        from attendance.attendance import AttendanceRecord
        from attendance.report import StudentDisplay, build_report
        self.env = patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin", "LINE_CHANNEL_SECRET": "secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.day = date(2026, 10, 11)
        self.students = {f"ST{index:03}": StudentDisplay(f"ST{index:03}", f"Student {index}") for index in range(41)}
        self.students["ST018"].display_name = "貝瑞森 (Rio)"
        statuses = ["personal_leave"] * 6 + ["sick_leave"] * 4 + ["menstrual_leave"] * 3 + ["not_coming"] * 5
        self.records = [AttendanceRecord(student_id=f"ST{index:03}", status=status, attendance_date=self.day) for index, status in enumerate(statuses)]
        self.morning = build_report(report_date=self.day, total_students=41, expected_students=41, records=self.records, students=self.students)
        self.tables = {}
        def worksheet(name, headers):
            if name not in self.tables:
                rows = [headers[:]]
                sheet = MagicMock()
                sheet.get_all_values.side_effect = lambda: [row[:] for row in rows]
                sheet.append_row.side_effect = lambda values, **kwargs: rows.append(list(values))
                def update(*, range_name, values, **kwargs):
                    import re
                    index = int(re.search(r"\d+", range_name)[0]) - 1
                    rows[index] = list(values[0])
                sheet.update.side_effect = update
                self.tables[name] = (sheet, rows)
            return self.tables[name][0]
        self.sheet_patch = patch("database.google_sheets._ensure_named_sheet", side_effect=worksheet)
        self.sheet_patch.start()
        self.addCleanup(self.sheet_patch.stop)
        self.attendance = patch("database.google_sheets.get_attendance_rows", return_value=[])
        self.mock_attendance = self.attendance.start()
        self.addCleanup(self.attendance.stop)
        from attendance.time_out import save_morning
        save_morning(self.day, self.morning, self.records, self.students, 41)

    def test_example_23_attended_one_no_bus_gives_22_returned(self):
        from attendance.time_out import get_state, confirm_return
        from attendance.report import DailyReportText
        self.mock_attendance.return_value = [{"student_id": "ST018", "type": "不坐公交車"}]
        state = get_state(self.day)
        self.assertEqual(state["expected_return"], 22)
        report = confirm_return(self.day, 22, "Uadmin", state["fingerprint"])
        self.assertIsInstance(report, DailyReportText)
        self.assertIn("應到人數：41", report)
        self.assertIn("實到人數：23", report)
        for category, count in (("事假", 6), ("病假", 4), ("經痛", 3), ("不出來", 5)):
            self.assertIn(f"{category}：{count}人", report)
        self.assertIn("不坐公交車：1人\n@貝瑞森 (Rio)", report)
        self.assertTrue(report.endswith("回到學校：22"))
        self.assertTrue(self.tables["Time Out Reports"][1][1][6])

    def test_morning_snapshot_never_changes_with_afternoon_records(self):
        from attendance.time_out import save_morning, get_state
        saved = save_morning(self.day, "Changed afternoon report", [], self.students, 41)
        self.assertEqual(saved["report"], self.morning)
        self.assertEqual(len(self.tables["Morning Reports"][1]), 2)
        self.assertEqual(get_state(self.day)["morning"]["snapshot"]["attended"], 23)

    def test_bus_override_does_not_change_leave_or_salary(self):
        from attendance.time_out import set_bus_exception, get_state
        with patch("database.google_sheets.upsert_attendance_record") as log, patch("database.google_sheets.update_monthly_report_cell") as grid:
            set_bus_exception(self.day, "ST018", True)
            self.assertEqual(get_state(self.day)["expected_return"], 22)
            set_bus_exception(self.day, "ST018", False)
            self.assertEqual(get_state(self.day)["expected_return"], 23)
            log.assert_not_called()
            grid.assert_not_called()
        with self.assertRaises(ValueError):
            set_bus_exception(self.day, "ST000", True)

    def test_absent_student_not_subtracted_twice(self):
        from attendance.time_out import get_state
        self.mock_attendance.return_value = [{"student_id": "ST000", "type": "不坐公交車"}]
        self.assertEqual(get_state(self.day)["expected_return"], 23)

    def test_changed_bus_list_and_repeat_confirmation_rejected(self):
        from attendance.time_out import get_state, set_bus_exception, confirm_return
        before = get_state(self.day)
        set_bus_exception(self.day, "ST018", True)
        with self.assertRaisesRegex(ValueError, "changed"):
            confirm_return(self.day, 23, "Uadmin", before["fingerprint"])
        now = get_state(self.day)
        confirm_return(self.day, 22, "Uadmin", now["fingerprint"])
        with self.assertRaises(ValueError):
            confirm_return(self.day, 22, "Uadmin", now["fingerprint"])

    def test_partial_return_does_not_mark_everyone_home(self):
        from attendance.time_out import get_state, confirm_return
        state = get_state(self.day)
        report = confirm_return(self.day, 20, "Uadmin", state["fingerprint"])
        self.assertTrue(report.endswith("回到學校：20"))
        self.assertFalse(self.tables["Time Out Reports"][1][1][6])
        from bot.time_out_portal import timeout_message
        rows = timeout_message(self.day).contents.data["body"]["contents"]
        values = {row["contents"][0]["text"]: row["contents"][1]["text"] for row in rows if row.get("layout") == "horizontal"}
        self.assertEqual(values["Confirmed Returned"], "20")
        self.assertNotIn("Status", values)

    def test_nonadmin_and_invalid_counts_cannot_confirm(self):
        from attendance.time_out import get_state, confirm_return
        state = get_state(self.day)
        with self.assertRaises(ValueError):
            confirm_return(self.day, 23, "Ustudent", state["fingerprint"])
        for count in (-1, 24):
            with self.assertRaises(ValueError):
                confirm_return(self.day, count, "Uadmin", state["fingerprint"])

    def test_direct_send_outputs_group_plain_text_without_preview(self):
        from bot.admin_portal import handle_postback
        from attendance.report import GroupReportText
        self.assertNotIn("Time Out Reports", self.tables)
        result = handle_postback({"action": ["admin_timeout_send"], "date": [self.day.isoformat()]}, "Uadmin")
        self.assertIsInstance(result, GroupReportText)
        self.assertTrue(result.endswith("回到學校：23"))
        self.assertEqual(len(self.tables["Time Out Reports"][1]), 2)

    def test_timeout_card_has_only_two_actions_and_no_extra_explanation(self):
        from bot.time_out_portal import timeout_message
        result = timeout_message(self.day)
        buttons = result.contents.data["footer"]["contents"]
        self.assertEqual([button["action"]["label"] for button in buttons], ["Choose Who Won't Take Bus", "Send to Group"])
        rows = result.contents.data["body"]["contents"]
        labels = [row["contents"][0]["text"] for row in rows if row.get("layout") == "horizontal"]
        self.assertNotIn("Status", labels)
        self.assertEqual(buttons[1]["margin"], "8px")

    def test_old_preview_button_now_sends_directly(self):
        from bot.admin_portal import handle_postback
        from attendance.report import GroupReportText
        result = handle_postback({"action": ["admin_timeout_preview"], "date": [self.day.isoformat()]}, "Uadmin")
        self.assertIsInstance(result, GroupReportText)

    def test_missing_morning_report_requests_capture(self):
        from bot.time_out_portal import timeout_message
        import json
        result = timeout_message(date(2026, 10, 10))
        content = json.dumps(result.contents.data)
        self.assertIn("No saved morning report", content)
        self.assertIn("cannot be recovered", content)

    def test_existing_transport_section_is_replaced_not_duplicated(self):
        from attendance.time_out import get_state, compose_report
        state = get_state(self.day)
        state["morning"]["report"] = str(self.morning) + "\n\n不坐公交車：1人\n@Old Name"
        state["no_bus"] = ["ST018"]
        state["expected_return"] = 22
        report = compose_report(state, 22)
        self.assertEqual(report.count("不坐公交車："), 1)
        self.assertNotIn("Old Name", report)
        self.assertIn("貝瑞森 (Rio)", report)

    def test_admin_menu_changes_only_admin_schedule_tile(self):
        admin = build_rich_menu_request(admin=True)
        student = build_rich_menu_request()
        self.assertEqual(admin.areas[3].action.label, "Time Out Report")
        self.assertEqual(admin.areas[3].action.data, "action=admin_timeout")
        self.assertEqual(student.areas[3].action.label, "Work Schedule")
        self.assertEqual(student.areas[3].action.data, "action=richmenu_schedule")


class TestTimeOutEligibility(TestCase):
    def test_paid_annual_leave_preserves_attendance_but_not_bus_expectation(self):
        from attendance.time_out import save_morning
        from attendance.attendance import AttendanceRecord
        from attendance.report import StudentDisplay, build_report
        day = date(2026, 10, 11)
        students = {sid: StudentDisplay(sid, sid) for sid in ("A", "B", "C")}
        records = [AttendanceRecord(student_id="A", status="special_leave", attendance_date=day)]
        report = build_report(report_date=day, total_students=3, expected_students=3, records=records, students=students)
        sheet = MagicMock()
        sheet.get_all_values.return_value = [["Date", "Captured At", "Report", "Snapshot"]]
        with patch("database.google_sheets._ensure_named_sheet", return_value=sheet):
            saved = save_morning(day, report, records, students, 3)
        self.assertEqual(saved["snapshot"]["attended"], 3)
        self.assertFalse(saved["snapshot"]["students"]["A"]["return_expected"])
        self.assertTrue(saved["snapshot"]["students"]["B"]["return_expected"])

    def test_future_or_rest_day_report_does_not_freeze_morning_attendance(self):
        from attendance.time_out import save_morning
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from datetime import datetime
        with patch("database.google_sheets._ensure_named_sheet") as sheet:
            self.assertIsNone(save_morning(date(2026, 10, 12), "Rest day", [], {}, 0))
            future = datetime.now(ZoneInfo("Asia/Taipei")).date() + timedelta(days=365)
            self.assertIsNone(save_morning(future, "Future day", [], {}, 0))
            sheet.assert_not_called()

    def test_student_cannot_access_time_out_workspace(self):
        from bot.admin_portal import handle_postback
        with patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}), patch("attendance.time_out.get_state") as read:
            with self.assertRaisesRegex(ValueError, "administrators only"):
                handle_postback({"action": ["admin_timeout"]}, "Ustudent")
            read.assert_not_called()


class TestRichMenuImageSync(TestCase):
    def test_source_images_fit_upload_limit_without_modifying_artwork(self):
        from bot.rich_menu import prepare_menu_image, IMAGE_DIR
        from pathlib import Path
        from PIL import Image
        import io
        for name in ("rich_menu.png", "admin_rich_menu.png"):
            with self.subTest(name=name):
                path = IMAGE_DIR / name
                original = path.read_bytes()
                data, content_type, width, height = prepare_menu_image(path)
                self.assertLessEqual(len(data), 1_000_000)
                self.assertIn(content_type, {"image/jpeg", "image/png"})
                with Image.open(io.BytesIO(data)) as uploaded:
                    self.assertEqual(uploaded.size, (width, height))
                self.assertEqual(path.read_bytes(), original)

    def test_hit_areas_cover_replacement_image_dimensions(self):
        menu = build_rich_menu_request(width=2048, height=1381, admin=True)
        self.assertEqual(menu.size.width, 2048)
        self.assertEqual(menu.size.height, 1381)
        for row in range(2):
            tiles = menu.areas[row * 3:(row + 1) * 3]
            self.assertEqual(sum(tile.bounds.width for tile in tiles), 2048)
            self.assertEqual(tiles[0].bounds.x, 0)
            self.assertEqual(tiles[-1].bounds.x + tiles[-1].bounds.width, 2048)
        self.assertEqual(menu.areas[-1].bounds.y + menu.areas[-1].bounds.height, 1381)

    def test_button_definition_changes_trigger_menu_recreation(self):
        import bot.rich_menu as menus
        old = menus.get_layout_hash(True, 2048, 1381)
        labels, actions = menus.menu_actions(True)
        actions[3] = "changed_route"
        with patch.object(menus, "menu_actions", return_value=(labels, actions)):
            self.assertNotEqual(menus.get_layout_hash(True, 2048, 1381), old)

    def test_refresh_command_refreshes_both_roles(self):
        from bot.commands import _run_admin_command
        with patch("bot.rich_menu.setup_rich_menu", side_effect=["STUDENT", "ADMIN"]) as refresh:
            result = _run_admin_command(["setuprichmenu"], "Uadmin")
        self.assertEqual(refresh.call_count, 2)
        self.assertEqual(refresh.call_args_list[0].kwargs, {"force": True})
        self.assertEqual(refresh.call_args_list[1].kwargs, {"force": True, "admin": True})
        self.assertIn("Student and admin", result)

    def test_invalid_image_is_rejected_before_line_api_call(self):
        import bot.rich_menu as menus
        with patch.object(menus, "prepare_menu_image", side_effect=ValueError("Invalid image")), patch.object(menus, "MessagingApi") as api:
            self.assertIsNone(menus.setup_rich_menu())
            api.assert_not_called()


class TestOfficialReportsGoToGroup(TestCase):
    def test_group_report_is_plain_text_and_uses_only_configured_group(self):
        from app import send_report_to_group
        from attendance.report import GroupReportText
        from types import SimpleNamespace
        report = GroupReportText("應到人數：41\n實到人數：23\n\n回到學校：22")
        with patch.dict(os.environ, {"LINE_REPORT_GROUP_ID": "Cconfigured"}), patch("app.ApiClient"), patch("app.MessagingApi") as api, patch(
            "app.PushMessageRequest", side_effect=lambda **args: SimpleNamespace(**args)
        ), patch("app.TextMessage", side_effect=lambda text: SimpleNamespace(text=text)), patch("app.response_card_message") as cards, patch("app.localize_message") as translate:
            self.assertTrue(send_report_to_group(report))
            request = api.return_value.push_message.call_args.kwargs["push_message_request"]
            self.assertEqual(request.to, "Cconfigured")
            self.assertEqual(request.messages[0].text, report)
            cards.assert_not_called()
            translate.assert_not_called()

    def test_issued_report_posts_to_group_and_acknowledges_admin_privately(self):
        from app import reply_to_line
        from attendance.report import GroupReportText
        from bot.delivery import destination, ReplyDestination
        report = GroupReportText("Report\n回到學校：22")
        token = destination.set(ReplyDestination("Uadmin", False))
        try:
            with patch("app.send_report_to_group", return_value=True) as group, patch("app.push_to_line", return_value=True) as private, patch("app.ApiClient") as public_reply:
                self.assertTrue(reply_to_line("PUBLIC_TOKEN", report))
                group.assert_called_once_with(report)
                private.assert_called_once_with("Uadmin", "Report sent to the configured group chat.")
                public_reply.assert_not_called()
        finally:
            destination.reset(token)

    def test_missing_group_config_has_no_public_fallback(self):
        from app import send_report_to_group
        with patch.dict(os.environ, {"LINE_REPORT_GROUP_ID": ""}), patch("app.ApiClient") as api:
            self.assertFalse(send_report_to_group("Report"))
            api.assert_not_called()

    def test_failed_group_delivery_notifies_admin_without_claiming_success(self):
        from app import reply_to_line
        from attendance.report import GroupReportText
        from bot.delivery import destination, ReplyDestination
        token = destination.set(ReplyDestination("Uadmin", False))
        try:
            with patch("app.send_report_to_group", return_value=False), patch("app.push_to_line", return_value=True) as private:
                reply_to_line("PUBLIC_TOKEN", GroupReportText("Report"))
                self.assertIn("could not be sent", private.call_args.args[1])
        finally:
            destination.reset(token)

    def test_manual_report_is_marked_for_group_publication(self):
        from bot.commands import _report_data
        from attendance.report import GroupReportText
        with patch("database.google_sheets.get_report_students", return_value=({}, 0)), patch("bot.commands._records_for_date", return_value=[]), patch("attendance.time_out.save_morning"):
            self.assertIsInstance(_report_data(date(2026, 10, 11), summary=False), GroupReportText)


class TestSearchFirstAdminCards(TestCase):
    def test_initial_picker_does_not_load_or_show_all_students(self):
        from bot.admin_portal import students_message
        with patch("database.google_sheets.search_active_students") as search, patch("database.google_sheets.get_report_students") as roster:
            result = students_message(date(2026, 10, 14))
        search.assert_not_called()
        roster.assert_not_called()
        buttons = result.contents.data["footer"]["contents"]
        self.assertEqual(buttons[0]["action"]["inputOption"], "openKeyboard")
        self.assertEqual(len(buttons), 3)
        self.assertNotIn("Page", result.alt_text)

    def test_search_matches_chinese_english_line_names_and_id(self):
        from database.google_sheets import search_active_students
        records = [
            {"student_id": "S06494", "chinese_name": "奎姐兒", "full_name": "Dharls Inobao Quinto", "display_name": "奎姐兒/dharls"},
            {"student_id": "S06505", "chinese_name": "華凌智", "full_name": "Another Student", "display_name": "Other"},
            {"student_id": "S99999", "full_name": "Dharls", "active": "FALSE"},
        ]
        with patch("database.google_sheets._read_students_records", return_value=records):
            for query in ("奎姐", "DHARLS", "Quinto", "s06494", "奎姐兒/dharls"):
                with self.subTest(query=query):
                    self.assertEqual([row["student_id"] for row in search_active_students(query)], ["S06494"])
            self.assertEqual(search_active_students("Missing"), [])

    def test_results_show_five_matches_and_preserve_date(self):
        from bot.admin_portal import students_message
        from urllib.parse import parse_qs
        matches = [{"student_id": str(i), "chinese_name": "Name", "name": "Name"} for i in range(8)]
        day = date(2026, 10, 23)
        with patch("database.google_sheets.search_active_students", return_value=matches):
            result = students_message(day, query="Name")
        buttons = result.contents.data["footer"]["contents"]
        choices = [button for button in buttons if parse_qs(button["action"].get("data", "")).get("action") == ["admin_student"]]
        self.assertEqual(len(choices), 5)
        for button in choices:
            self.assertEqual(parse_qs(button["action"]["data"])["date"], [day.isoformat()])
        self.assertIn("More Matches", [button["action"]["label"] for button in buttons])

    def test_status_choices_are_in_compact_two_column_grid(self):
        from bot.admin_portal import student_message, STATUSES
        from urllib.parse import parse_qs
        student = {"student_id": "S06505", "name": "華凌智"}
        day = date(2026, 10, 14)
        with patch("database.google_sheets.get_monthly_report_entries", return_value={day: "事假"}):
            result = student_message(student, day)
        rows = [row for row in result.contents.data["body"]["contents"] if row.get("layout") == "horizontal" and any(child.get("type") == "button" for child in row.get("contents", []))]
        self.assertEqual(len(rows), 5)
        buttons = [button for row in rows for button in row["contents"] if button.get("type") == "button"]
        self.assertEqual({parse_qs(button["action"]["data"])["status"][0] for button in buttons}, set(STATUSES))
        self.assertEqual(len(result.contents.data["footer"]["contents"]), 2)

    def test_missing_scheduled_date_opens_picker_instead_of_error(self):
        from bot.admin_portal import student_message
        with patch("database.google_sheets.get_monthly_report_entries", return_value={date(2026, 10, 14): ""}):
            result = student_message({"student_id": "S06505", "name": "Student"}, date(2026, 10, 12))
        self.assertIn("Choose a Workday", result.alt_text)
        self.assertEqual(result.contents.data["footer"]["contents"][0]["action"]["type"], "datetimepicker")

    def test_search_context_is_private_per_user_one_query_and_expires(self):
        from bot.search_context import begin_search, consume_search
        day = date(2026, 10, 23)
        with patch("bot.search_context.monotonic", return_value=100):
            begin_search("Uone", day)
            self.assertIsNone(consume_search("Uother"))
            self.assertEqual(consume_search("Uone").day, day)
            self.assertIsNone(consume_search("Uone"))
            begin_search("Uexpired", day, bus=True)
        with patch("bot.search_context.monotonic", return_value=401):
            self.assertIsNone(consume_search("Uexpired"))

    def test_search_button_starts_context_without_command_prefix(self):
        from bot.admin_portal import handle_postback
        from bot.search_context import consume_search
        day = date(2026, 10, 23)
        with patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}):
            result = handle_postback({"action": ["admin_search"], "date": [day.isoformat()]}, "Uadmin")
            self.assertIn("Search Students", result.alt_text)
            context = consume_search("Uadmin")
        self.assertEqual(context.day, day)
        self.assertFalse(context.bus)


class TestDirectEditAndClear(TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin", "LINE_CHANNEL_SECRET": "secret"})
        env.start()
        self.addCleanup(env.stop)
        self.student = {"student_id": "S06677", "name": "杜榮瑪", "chinese_name": "杜榮瑪"}
        self.day = date(2026, 10, 14)

    def test_edit_name_or_id_opens_card_directly(self):
        from bot.admin_portal import edit_shortcut
        for command in ("Edit S06677", "edit 杜榮瑪", "/edit 杜榮瑪"):
            with self.subTest(command=command), patch("database.google_sheets.find_student_by_id", return_value=self.student), patch(
                "database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假"}
            ), patch("bot.admin_portal.today", return_value=self.day), patch("bot.admin_portal.students_message") as picker:
                result = edit_shortcut(command, "Uadmin")
                self.assertIn("Edit Attendance", result.alt_text)
                picker.assert_not_called()

    def test_edit_explicit_date_and_rest_day_default(self):
        from bot.admin_portal import edit_shortcut
        import json
        later = date(2026, 10, 23)
        with patch("database.google_sheets.find_student_by_id", return_value=self.student), patch(
            "database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假", later: ""}
        ), patch("bot.admin_portal.today", return_value=date(2026, 10, 12)):
            default = edit_shortcut("Edit S06677", "Uadmin")
            explicit = edit_shortcut("Edit 杜榮瑪 2026-10-23", "Uadmin")
        self.assertIn(self.day.isoformat(), json.dumps(default.contents.data))
        self.assertIn(later.isoformat(), json.dumps(explicit.contents.data))

    def test_ambiguous_names_show_matches_instead_of_picking_someone(self):
        from bot.admin_portal import edit_shortcut
        matches = [self.student, {"student_id": "OTHER", "name": "杜榮瑪"}]
        with patch("database.google_sheets.find_student_by_id", return_value=None), patch("database.google_sheets.search_active_students", return_value=matches), patch("bot.admin_portal.student_message") as editor:
            result = edit_shortcut("Edit 杜榮瑪", "Uadmin")
        self.assertIn("Search Results", result.alt_text)
        editor.assert_not_called()

    def test_edit_status_shortcuts_apply_with_optional_month_day(self):
        from bot.admin_portal import edit_shortcut, STATUSES
        commands = [("Edit 10/14 杜榮瑪 Clear", "clear"),
                    ("Edit 10/14 s06677 Clear", "clear")]
        commands += [("Edit S06677 " + label, key) for label, key in (
            ("present", "present"), ("sick leave", "sick"), ("personal", "personal"),
            ("menstrual", "menstrual"), ("annual", "annual"), ("half day", "half"),
            ("late", "late"), ("pending", "pending"))]
        for command, key in commands:
            with self.subTest(command=command), \
                 patch("database.google_sheets.find_student_by_id", return_value=self.student), \
                 patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假"}), \
                 patch("bot.admin_portal.today", return_value=self.day), \
                 patch("bot.admin_portal._snapshot", return_value=("snapshot", "病假")), \
                 patch("attendance.leave_message.validate_leave_workday"), \
                 patch("bot.admin_portal.handle_postback", return_value="saved") as apply:
                self.assertEqual(edit_shortcut(command, "Uadmin"), "saved")
                data, actor = apply.call_args.args
                self.assertEqual(data["status"], [key])
                self.assertEqual(data["date"], ["2026-10-14"])
                self.assertEqual(data["student"], ["S06677"])
                self.assertEqual(actor, "Uadmin")

    def test_nonadmin_shortcut_does_not_read_students(self):
        from bot.admin_portal import edit_shortcut
        with patch("database.google_sheets.find_student_by_id") as read:
            with self.assertRaisesRegex(ValueError, "administrators only"):
                edit_shortcut("Edit S06677", "Ustudent")
            read.assert_not_called()

    def test_clear_is_red_and_directly_below_absent(self):
        from bot.admin_portal import student_message
        from bot.line_ui import DEDUCTION_RED
        with patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假"}):
            result = student_message(self.student, self.day)
        grid = [row for row in result.contents.data["body"]["contents"] if row.get("layout") == "horizontal" and row["contents"][0].get("type") == "button"]
        self.assertEqual(grid[3]["contents"][1]["action"]["label"], "Absent")
        clear = grid[4]["contents"][1]
        self.assertEqual(clear["action"]["label"], "Clear")
        self.assertEqual(clear["color"], DEDUCTION_RED)
        self.assertEqual(clear["margin"], "8px")

    def test_clear_confirm_uses_clear_service_not_present_status(self):
        from bot.admin_portal import preview_message, handle_postback
        from urllib.parse import parse_qs
        with patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假"}), patch("database.google_sheets.get_attendance_record", return_value=None), patch("database.google_sheets.find_student_by_id", return_value=self.student):
            preview = preview_message("Uadmin", self.student, self.day, "clear", None)
            data = parse_qs(preview.contents.data["footer"]["contents"][0]["action"]["data"])
            with patch("database.google_sheets.clear_student_attendance", return_value={"action_id": "CLEAR1"}) as clear, patch("database.google_sheets.upsert_attendance_record") as present:
                result = handle_postback(data, "Uadmin")
            clear.assert_called_once_with("S06677", self.day, "Uadmin")
            present.assert_not_called()
            self.assertIn("Attendance Cleared", result.alt_text)

    def test_clear_deletes_all_same_day_records_in_reverse_row_order(self):
        from database.google_sheets import clear_student_attendance
        sheet = MagicMock()
        records = [{"student_id": "S06677", "_row_number": "10"}, {"student_id": "OTHER", "_row_number": "15"}, {"student_id": "S06677", "_row_number": "20"}]
        with patch("database.google_sheets.get_monthly_report_entries", return_value={self.day: "病假"}), patch("database.google_sheets.get_attendance_rows", return_value=records), patch(
            "database.google_sheets._attendance_header_layout", return_value=(sheet, [], 1, {})
        ), patch("database.google_sheets._append_audit", return_value="CLEAR1") as audit, patch("database.google_sheets.update_monthly_report_cell", return_value=True) as grid:
            result = clear_student_attendance("S06677", self.day, "Uadmin")
        self.assertEqual([call.args[0] for call in sheet.delete_rows.call_args_list], [20, 10])
        self.assertEqual(audit.call_args.args[1], "CLEAR")
        grid.assert_called_once_with("S06677", self.day, "")
        self.assertEqual(result["action_id"], "CLEAR1")

    def test_undo_clear_restores_records_and_previous_grid_value(self):
        from database.google_sheets import undo_last_attendance_action, AUDIT_HEADERS
        import json
        saved = {"records": [{"student_id": "S06677", "name": "杜榮瑪", "date": self.day.isoformat(), "type": "病假", "status": "Confirmed", "raw_message": "Original notice", "attendance_record_id": "REC1"}], "monthly_status": "病假"}
        rows = [AUDIT_HEADERS, ["CLEAR1", "timestamp", "Uadmin", "CLEAR", "S06677", self.day.isoformat(), "病假", "", json.dumps(saved), "FALSE"]]
        sheet = MagicMock()
        sheet.get_all_values.side_effect = lambda: rows
        def append_undo(*args):
            rows.append(["UNDO1", "timestamp", "Uadmin", "UNDO", "S06677", self.day.isoformat(), "", "病假", "Undo", "FALSE"])
        with patch("database.google_sheets._ensure_named_sheet", return_value=sheet), patch("database.google_sheets.append_attendance_row", return_value="REC1") as restore, patch("database.google_sheets.update_monthly_report_cell", return_value=True) as grid, patch("database.google_sheets._append_audit", side_effect=append_undo):
            undo_last_attendance_action("Uadmin")
        self.assertEqual(restore.call_args.args[0][3], "病假")
        self.assertEqual(restore.call_args.args[0][-1], "REC1")
        grid.assert_called_once_with("S06677", self.day, "病假")


class TestNaturalWeekdayLeave(TestCase):
    MESSAGE = "Good morning, due to personal reasons I won't be able to make it to work on Wednesday."

    def test_exact_screenshot_message_is_personal_leave_on_wednesday(self):
        from attendance.ai_classifier import classify_attendance_message
        from attendance.leave_message import parse_attendance_date, validate_leave_workday
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            analysis = classify_attendance_message(self.MESSAGE)
        self.assertEqual(analysis.intent, "LEAVE")
        self.assertEqual(analysis.category, "事假")
        self.assertEqual(analysis.to_classification_result().status, "personal_leave")
        selected = parse_attendance_date(self.MESSAGE, today=date(2026, 10, 12))
        self.assertEqual(selected, date(2026, 10, 14))
        validate_leave_workday(selected)

    def test_greetings_do_not_turn_full_leave_into_half_day(self):
        from attendance.ai_classifier import classify_attendance_message
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            for greeting in ("Good morning", "Good afternoon", "Hello, good morning everyone"):
                message = f"{greeting}, due to personal reasons I won't be able to make it to work on Wednesday."
                with self.subTest(greeting=greeting):
                    self.assertEqual(classify_attendance_message(message).category, "事假")
            partial = "Good morning, I am requesting personal leave for Wednesday afternoon."
            self.assertEqual(classify_attendance_message(partial).category, "半天")

    def test_curly_apostrophe_and_common_absence_phrases(self):
        from attendance.ai_classifier import classify_attendance_message
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            for phrase in ("won’t be able to make it to work", "cannot come to work", "will not be able to attend work", "am unable to go to work"):
                message = f"Due to personal reasons I {phrase} on Wednesday."
                with self.subTest(phrase=phrase):
                    self.assertEqual(classify_attendance_message(message).category, "事假")

    def test_weekdays_relative_to_posted_day_and_month_boundary(self):
        from attendance.leave_message import parse_attendance_date
        for message, today, expected in (
            ("leave on Wednesday", date(2026, 10, 12), date(2026, 10, 14)),
            ("leave on Wednesday", date(2026, 10, 14), date(2026, 10, 14)),
            ("leave next Wednesday", date(2026, 10, 14), date(2026, 10, 21)),
            ("leave on Wednesday next week", date(2026, 10, 12), date(2026, 10, 21)),
            ("leave Wed", date(2026, 10, 30), date(2026, 11, 4)),
            ("星期三請假", date(2026, 10, 12), date(2026, 10, 14)),
            ("下週三請假", date(2026, 10, 12), date(2026, 10, 21)),
            ("leave on 2026-10-23, Wednesday", date(2026, 10, 12), date(2026, 10, 23)),
        ):
            with self.subTest(message=message):
                self.assertEqual(parse_attendance_date(message, today=today), expected)

    def test_personal_reasons_without_absence_is_not_a_leave_record(self):
        from attendance.classifier import classify_status
        for message in ("Good morning everyone", "We are discussing personal reasons", "I am not taking personal leave on Wednesday"):
            result = classify_status(message)
            self.assertFalse(result.attendance_intent)


class SeparateLogsWorkbookTests(TestCase):
    def test_initialization_routes_attendance_to_logs_workbook(self):
        from database import google_sheets as db
        main, logs = MagicMock(), MagicMock()
        with patch.multiple(db, spreadsheet=None, logs_spreadsheet=None,
                            students_sheet=None, attendance_sheet=None, logs_sheet=None), \
             patch.dict(os.environ, {"GOOGLE_SHEET_LOGS_ID": "logs-id"}), \
             patch.object(db, "connect_google_sheets", side_effect=[main, logs]) as connect, \
             patch.object(db, "_find_attendance_table", return_value="A1:G1"):
            self.assertIs(db.ensure_sheet_state(), main)
            self.assertIs(db.logs_spreadsheet, logs)
            main.worksheet.assert_called_once_with("Students")
            self.assertEqual([call.args[0] for call in logs.worksheet.call_args_list], ["Attendance", "Logs"])
            self.assertEqual(connect.call_args_list[1].args, ("GOOGLE_SHEET_LOGS_ID",))

    def test_named_tabs_use_the_correct_workbook(self):
        from database import google_sheets as db
        main, logs = MagicMock(), MagicMock()
        with patch.multiple(db, spreadsheet=main, logs_spreadsheet=logs):
            for name in ("Audit Log", "Tickets", "User Settings"):
                self.assertIs(db._ensure_named_sheet(name, ["header"]), logs.worksheet.return_value)
            for name in ("Account Authorizations", "Morning Reports", "Time Out Drafts", "Time Out Reports"):
                self.assertIs(db._ensure_named_sheet(name, ["header"]), main.worksheet.return_value)

    def test_unavailable_logs_workbook_does_not_fall_back(self):
        from database import google_sheets as db
        main = MagicMock()
        with patch.multiple(db, spreadsheet=None, logs_spreadsheet=None), \
             patch.dict(os.environ, {"GOOGLE_SHEET_LOGS_ID": "logs-id"}), \
             patch.object(db, "connect_google_sheets", side_effect=[main, RuntimeError("access denied")]):
            self.assertIsNone(db.ensure_sheet_state())
            self.assertIsNone(db.spreadsheet)
            main.worksheet.assert_not_called()

    def test_unset_logs_id_keeps_single_workbook_compatibility(self):
        from database import google_sheets as db
        main = MagicMock()
        with patch.multiple(db, spreadsheet=None, logs_spreadsheet=None,
                            students_sheet=None, attendance_sheet=None, logs_sheet=None), \
             patch.dict(os.environ, {"GOOGLE_SHEET_LOGS_ID": ""}), \
             patch.object(db, "connect_google_sheets", return_value=main) as connect, \
             patch.object(db, "_find_attendance_table", return_value="A1:G1"):
            self.assertIs(db.ensure_sheet_state(), main)
            self.assertIs(db.logs_spreadsheet, main)
            connect.assert_called_once_with()


class ImmediateAdminStatusTests(TestCase):
    def test_new_and_old_status_buttons_save_without_confirmation(self):
        from bot.admin_portal import handle_postback
        student = {"student_id": "S06677", "name": "杜榮瑪"}
        day = date(2026, 10, 14)
        for action_name in ("admin_change", "admin_preview"):
            for status in ("sick", "clear"):
                with self.subTest(action=action_name, status=status), \
                     patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}), \
                     patch("database.google_sheets.find_student_by_id", return_value=student), \
                     patch("database.google_sheets.get_monthly_report_entries", return_value={day: "事假"}), \
                     patch("database.google_sheets.get_attendance_record", return_value=None), \
                     patch("database.google_sheets.upsert_attendance_record", return_value={"action_id": "A1"}) as write, \
                     patch("database.google_sheets.update_monthly_report_cell", return_value=True) as grid, \
                     patch("database.google_sheets.clear_student_attendance", return_value={"action_id": "A2"}) as clear, \
                     patch("bot.admin_portal.preview_message") as preview:
                    result = handle_postback({"action": [action_name], "student": ["S06677"],
                                              "date": [day.isoformat()], "status": [status]}, "Uadmin")
                    preview.assert_not_called()
                    if status == "clear":
                        self.assertIn("Attendance Cleared", result.alt_text)
                        clear.assert_called_once_with("S06677", day, "Uadmin")
                        write.assert_not_called()
                    else:
                        self.assertIn("Attendance Updated", result.alt_text)
                        self.assertEqual(write.call_args.args[3], "病假")
                        grid.assert_called_once_with("S06677", day, "病假")
