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
            button = card.contents.data["body"]["contents"][-1]
            self.assertEqual(button["action"]["label"], "Authorize & Connect Account")
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
            self.assertEqual(values[3], "1")
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
