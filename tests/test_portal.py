"""Unit tests for CSIE Student Portal Rich Menu and features."""

import sys
from datetime import date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock

# Stub external libraries if not installed in the testing environment
for mod in ["dotenv", "gspread", "gspread.exceptions", "google", "google.oauth2", "google.oauth2.service_account"]:
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
    leave_history_message,
    leave_request_menu_message,
    my_attendance_message,
    salary_breakdown_message,
    salary_overview_message,
    welcome_message,
    work_schedule_message,
)
from bot.rich_menu import build_rich_menu_request
from bot.commands import try_handle_natural_portal_query, normalize_command
from ui.leave_confirmation import (
    leave_confirmation_message,
    withdrawal_confirmation_message,
)


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
        self.assertEqual(req.size.height, 946)
        self.assertEqual(len(req.areas), 6)

        # Verify area 1 (My Attendance)
        a1 = req.areas[0]
        self.assertEqual((a1.bounds.x, a1.bounds.y, a1.bounds.width, a1.bounds.height), (0, 0, 833, 530))
        self.assertEqual(a1.action.data, "action=richmenu_attendance")

        # Verify area 2 (Leave History)
        a2 = req.areas[1]
        self.assertEqual((a2.bounds.x, a2.bounds.y, a2.bounds.width, a2.bounds.height), (833, 0, 834, 530))
        self.assertEqual(a2.action.data, "action=richmenu_leave_history")

        # Verify area 3 (Salary Inquiry)
        a3 = req.areas[2]
        self.assertEqual((a3.bounds.x, a3.bounds.y, a3.bounds.width, a3.bounds.height), (1667, 0, 833, 530))
        self.assertEqual(a3.action.data, "action=richmenu_salary")

        # Verify area 4 (Work Schedule)
        a4 = req.areas[3]
        self.assertEqual((a4.bounds.x, a4.bounds.y, a4.bounds.width, a4.bounds.height), (0, 530, 833, 416))
        self.assertEqual(a4.action.data, "action=richmenu_schedule")

        # Verify area 5 (Leave Request)
        a5 = req.areas[4]
        self.assertEqual((a5.bounds.x, a5.bounds.y, a5.bounds.width, a5.bounds.height), (833, 530, 834, 416))
        self.assertEqual(a5.action.data, "action=richmenu_leave_request")

        # Verify area 6 (Help Center)
        a6 = req.areas[5]
        self.assertEqual((a6.bounds.x, a6.bounds.y, a6.bounds.width, a6.bounds.height), (1667, 530, 833, 416))
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
            "scheduled_days": 20,
            "attended_days": 19,
            "absent_days": 1,
            "half_days": 0,
            "late_days": 0,
            "attendance_pct": 95,
            "today_status": "Present (Scheduled Workday)",
        }
        msg = my_attendance_message(summary, month_label="October 2026")
        data = msg.contents.data
        self.assertEqual(data["body"]["backgroundColor"], CARD_BG)

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
        from unittest.mock import patch
        with patch("database.google_sheets.get_student_leave_records", return_value=[]):
            res = try_handle_natural_portal_query("Show me all my sick leaves in September", "ST001")
            self.assertIsNotNone(res)
