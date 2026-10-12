import hashlib
import hmac
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from datetime import date, datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    FlexMessage,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    FollowEvent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

from attendance.attendance import AttendanceTracker
from attendance.ai_classifier import classify_attendance_message
from attendance.leave_message import (
    LEAVE_TYPE_LABELS,
    parse_attendance_date,
)
from attendance.salary import calculate_salary
from bot.language import localize_message, private_language_context
from bot.line_ui import language_settings_message
from database.google_sheets import set_user_language, save_account_authorization

from bot.commands import (
    handle_command,
    is_admin_user,
    normalize_command,
    try_handle_natural_portal_query,
)
from bot.line_ui import (
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
from ui.leave_confirmation import (
    leave_confirmation_message,
    withdrawal_confirmation_message,
)
from database.google_sheets import (
    append_attendance_row,
    create_ticket,
    delete_attendance_record,
    find_students_by_display_name,
    find_student_by_line_user_id,
    get_attendance_record_by_id,
    get_monthly_attendance_counts,
    get_student_attendance_summary,
    get_student_leave_records,
    get_student_tickets,
    get_work_calendar_schedule,
    LineRegistrationConflictError,
    register_line_user,
    update_monthly_report_cell,
)


# --------------------------------------------------
# Environment variables
# --------------------------------------------------

load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError(
        "LINE_CHANNEL_SECRET and "
        "LINE_CHANNEL_ACCESS_TOKEN are required."
    )


# --------------------------------------------------
# FastAPI + LINE setup
# --------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    from scheduler.daily_report import scheduler, start_scheduler

    start_scheduler()
    try:
        from bot.rich_menu import setup_rich_menu
        setup_rich_menu()
    except Exception as error:
        print("LIFESPAN RICH MENU INIT ERROR:", repr(error))

    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)

configuration = Configuration(
    access_token=CHANNEL_ACCESS_TOKEN
)

handler = WebhookHandler(CHANNEL_SECRET)

tracker = AttendanceTracker()


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "LINE Attendance Bot",
    }


# --------------------------------------------------
# LINE webhook
# --------------------------------------------------

@app.post("/callback")
async def callback(
    request: Request,
    x_line_signature: str = Header(None),
):
    body = await request.body()

    if not x_line_signature:
        raise HTTPException(
            status_code=400,
            detail="Missing LINE signature",
        )

    try:
        handler.handle(
            body.decode("utf-8"),
            x_line_signature,
        )

    except InvalidSignatureError:
        raise HTTPException(
            status_code=400,
            detail="Invalid LINE signature",
        )

    return {"status": "ok"}


# --------------------------------------------------
# LINE message handler
# --------------------------------------------------
def reply_to_line(reply_token: str, message: str | FlexMessage):
    try:
        message = localize_message(message)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)

            reply_request = ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=message) if isinstance(message, str) else message
                ],
            )

            messaging_api.reply_message(
                reply_message_request=reply_request
            )

    except Exception as error:
        print(
            "LINE REPLY ERROR:",
            repr(error),
        )


def push_to_line(user_id: str, message: str | FlexMessage) -> bool:
    """Send private attendance details without exposing them in a group."""

    try:
        message = localize_message(message, user_id)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.push_message(
                push_message_request=PushMessageRequest(
                    to=user_id,
                    messages=[
                        TextMessage(text=message) if isinstance(message, str) else message
                    ],
                )
            )
        return True
    except Exception as error:
        print("LINE PUSH ERROR:", repr(error))
        return False


def get_line_display_name(
    user_id: str,
    *,
    group_id: str | None = None,
    room_id: str | None = None,
) -> str | None:
    try:
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            if group_id:
                profile = messaging_api.get_group_member_profile(
                    group_id,
                    user_id,
                )
            elif room_id:
                profile = messaging_api.get_room_member_profile(
                    room_id,
                    user_id,
                )
            else:
                profile = messaging_api.get_profile(user_id)
        return profile.display_name
    except Exception as error:
        print("LINE PROFILE LOOKUP ERROR:", repr(error))
        return None


def get_line_group_member_profile(
    group_id: str,
    line_user_id: str,
) -> str | None:
    """Fetch a member's LINE display name from the group Messaging API."""

    try:
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            profile = messaging_api.get_group_member_profile(
                group_id,
                line_user_id,
            )
        return profile.display_name
    except Exception as error:
        print("LINE GROUP MEMBER PROFILE LOOKUP ERROR:", repr(error))
        return None


@dataclass
class StudentIdentification:
    status: str
    student: dict[str, object] | None = None
    display_name: str | None = None


def identify_or_register_student(event) -> StudentIdentification:
    """Resolve a sender by LINE user ID, registering only an exact first match."""

    line_user_id = str(
        getattr(event.source, "user_id", None) or ""
    ).strip()
    if not line_user_id:
        return StudentIdentification(status="missing_user_id")

    student = find_student_by_line_user_id(line_user_id)
    if student is not None:
        print(
            "LINE user already registered:",
            f"{line_user_id} → {student['name']}",
        )
        return StudentIdentification(status="identified", student=student)

    group_id = getattr(event.source, "group_id", None)
    room_id = getattr(event.source, "room_id", None)
    if group_id:
        display_name = get_line_group_member_profile(
            str(group_id),
            line_user_id,
        )
    else:
        display_name = get_line_display_name(
            line_user_id,
            room_id=room_id,
        )
    if display_name is None:
        print("First-contact LINE profile unavailable:", line_user_id)
        return StudentIdentification(status="profile_unavailable")

    print(f"First contact detected: {line_user_id} / {display_name}")
    matches = find_students_by_display_name(display_name)

    if not matches:
        print(
            "Unmatched first-contact LINE user:\n"
            f"Display Name: {display_name}\n"
            f"LINE User ID: {line_user_id}"
        )
        print("No Students sheet match for LINE display name:", display_name)
        return StudentIdentification(
            status="unmatched",
            display_name=display_name,
        )

    if len(matches) > 1:
        possible_matches = ", ".join(
            str(match.get("name", "")).strip() for match in matches
        )
        print(
            "Ambiguous LINE registration:\n"
            f"Display Name: {display_name}\n"
            f"Possible matches: {possible_matches}\n"
            f"LINE User ID: {line_user_id}"
        )
        print("Ambiguous display-name match:", display_name)
        return StudentIdentification(
            status="ambiguous",
            display_name=display_name,
        )

    student = matches[0]
    existing_user_id = str(student.get("line_user_id", "")).strip()
    if existing_user_id and existing_user_id != line_user_id:
        print(
            "LINE registration conflict\n"
            f"Student: {student.get('name', '')}\n"
            f"Existing LINE User ID: {existing_user_id}\n"
            f"Incoming LINE User ID: {line_user_id}"
        )
        return StudentIdentification(
            status="conflict",
            display_name=display_name,
        )

    try:
        register_line_user(student, line_user_id)
    except LineRegistrationConflictError as error:
        print(
            "LINE registration conflict\n"
            f"Student: {student.get('name', '')}\n"
            f"Existing LINE User ID: {error.existing_user_id}\n"
            f"Incoming LINE User ID: {error.incoming_user_id}"
        )
        return StudentIdentification(
            status="conflict",
            display_name=display_name,
        )

    student["line_user_id"] = line_user_id
    print(
        "Registered LINE user:\n"
        f"Display Name: {display_name}\n"
        f"Student: {student.get('name', '')}\n"
        f"LINE User ID: {line_user_id}"
    )
    print(
        "First-contact registration successful:",
        f"{display_name} → {student.get('student_id', '')} {student.get('name', '')}",
    )
    return StudentIdentification(
        status="registered",
        student=student,
        display_name=display_name,
    )


def resolve_student_from_event(event) -> dict[str, object] | None:
    """Resolve the active student for event, automatically connecting if not yet linked."""
    user_id = str(getattr(event.source, "user_id", None) or "").strip() or None
    if not user_id:
        return None
    try:
        student = find_student_by_line_user_id(user_id)
        if student:
            return student
        # Automatically connect LINE display name with LINE ID in database
        ident = identify_or_register_student(event)
        return ident.student
    except Exception as error:
        print("RESOLVE STUDENT ERROR:", repr(error))
        return None


@handler.add(FollowEvent)
def handle_follow(event):
    """Handle new friend follow event with automatic initialization."""
    user_id = str(getattr(event.source, "user_id", None) or "").strip()
    if not user_id:
        return
    try:
        ident = identify_or_register_student(event)
        student = ident.student
        display_name = ident.display_name or get_line_display_name(user_id)
        msg = initialization_message(
            student=student,
            display_name=display_name,
            is_registered=(ident.status == "registered"),
            error_status=ident.status if not student else None,
        )
        reply_to_line(event.reply_token, msg)
    except Exception as error:
        print("FOLLOW EVENT INIT ERROR:", repr(error))
        reply_to_line(event.reply_token, welcome_message())


@handler.add(
    MessageEvent,
    message=TextMessageContent,
)
@private_language_context
def handle_message(event):
    text = event.message.text or ""

    user_id = str(getattr(event.source, "user_id", None) or "").strip() or None
    is_private_chat = getattr(event.source, "type", "") == "user"
    group_id = getattr(
        event.source,
        "group_id",
        None,
    )
    print("------------------------------")
    print("USER:", user_id)
    print("GROUP:", group_id)
    print("MESSAGE:", text)

    if is_private_chat and text.strip().lower() in {"/language", "/settings", "language", "語言", "設定"}:
        reply_to_line(event.reply_token, language_settings_message())
        return

    student = None
    was_registered = False
    if user_id:
        try:
            student = find_student_by_line_user_id(user_id)
            was_registered = (student is not None)
        except Exception as error:
            print("STUDENT LOOKUP ERROR:", repr(error))

        if not was_registered:
            try:
                ident = identify_or_register_student(event)
                student = ident.student
                if is_private_chat:
                    if student and ident.status == "registered":
                        # Newly auto-connected upon first private chat: send initialization card with recognized identity & terms
                        reply_to_line(
                            event.reply_token,
                            initialization_message(
                                student=student,
                                display_name=ident.display_name,
                                is_registered=True,
                            ),
                        )
                        return
                    elif not student:
                        # Unmatched in database
                        reply_to_line(
                            event.reply_token,
                            initialization_message(
                                student=None,
                                display_name=ident.display_name,
                                error_status=ident.status,
                            ),
                        )
                        return
            except Exception as error:
                print("AUTO IDENTIFY ON CHAT ERROR:", repr(error))

    command_student_id = str(student["student_id"]) if student else None

    requested_command = normalize_command(text)
    if requested_command in {"hello", "start", "init"} or (
        requested_command == "help" and not is_admin_user(user_id)
    ):
        reply_to_line(event.reply_token, welcome_message(student=student))
        return

    is_private_chat = getattr(event.source, "type", "") == "user"
    try:
        command_response = handle_command(
            text,
            tracker,
            user_id,
            student_id=command_student_id,
            is_private=is_private_chat,
        )
    except Exception as error:
        print("COMMAND PROCESSING ERROR:", repr(error))
        command_response = "The command could not be completed. Please contact an administrator."
    if command_response is not None:
        reply_to_line(
            event.reply_token,
            command_response,
        )
        return

    # Check natural portal queries (e.g. 'Show me all my sick leaves in September', '出勤紀錄', etc.)
    try:
        natural_portal_response = try_handle_natural_portal_query(
            text,
            command_student_id,
            is_private=is_private_chat,
        )
        if natural_portal_response is not None:
            reply_to_line(event.reply_token, natural_portal_response)
            return
    except Exception as error:
        print("NATURAL PORTAL QUERY ERROR:", repr(error))

    if not text.strip():
        return

    try:
        analysis = classify_attendance_message(text)
    except Exception as error:
        import traceback

        print("ATTENDANCE AI CLASSIFICATION ERROR:", repr(error))
        traceback.print_exc()
        reply_to_line(
            event.reply_token,
            "The attendance classifier is unavailable, so your message was "
            "not saved. Please try again later or contact an administrator.",
        )
        return

    if analysis.intent == "IGNORE":
        print(
            "Non-attendance LINE message ignored:",
            analysis.reasoning,
        )
        return

    if analysis.intent == "REVIEW":
        reply_to_line(
            event.reply_token,
            "I couldn't determine whether you're notifying us of an absence. "
            "Are you requesting leave? Please send a clear leave notice with "
            "the date.",
        )
        return

    # --------------------------------------------------
    # No user ID
    # --------------------------------------------------

    if not user_id:
        reply_to_line(
            event.reply_token,
            "I couldn't identify your LINE account. Please contact an administrator.",
        )
        print("No user ID found. Message ignored; profile lookup requires a user ID.")
        return

    # --------------------------------------------------
    # Normal attendance classification
    # --------------------------------------------------

    try:
        identification = identify_or_register_student(event)
        student = identification.student

        if student is None:
            if identification.status == "unmatched":
                reply_message = (
                    "Your LINE account could not be matched to a student record.\n\n"
                    f"LINE display name: {identification.display_name}\n\n"
                    "Please ask an administrator to check your LINE Display Name "
                    "in the Students sheet."
                )
            elif identification.status == "ambiguous":
                reply_message = (
                    "Your LINE account matches more than one student record.\n\n"
                    "Please ask an administrator to confirm your account."
                )
            elif identification.status == "conflict":
                reply_message = (
                    "Your LINE account is already associated with a different "
                    "account on the student record. Please ask an administrator "
                    "to confirm your account."
                )
            else:
                reply_message = (
                    "I couldn't verify your LINE profile. Please ask an "
                    "administrator to confirm your account."
                )
            reply_to_line(
                event.reply_token,
                reply_message,
            )
            return

        student_work_id = str(student.get("student_id", "")).strip()
        student_name = str(
            student.get("chinese_name") or student.get("name") or ""
        ).strip()
        if not student_work_id or not student_name:
            print(
                "STUDENT ROSTER IDENTITY ERROR:",
                f"work_id_present={bool(student_work_id)}",
                f"chinese_name_present={bool(student_name)}",
            )
            reply_to_line(
                event.reply_token,
                "Your student record is missing its Work ID or Chinese Name. "
                "Please ask an administrator to check the Students sheet.",
            )
            return

        matched_by_line_user_id = True
        attendance_date = parse_attendance_date(text)
        classification = analysis.to_classification_result()
        record = tracker.add_from_message(
            student_id=student_work_id,
            message=text,
            attendance_date=attendance_date,
            classification_result=classification,
        )

        attendance_record_id = append_attendance_row([
            record.student_id,
            student_name,
            record.attendance_date.isoformat(),
            LEAVE_TYPE_LABELS[record.status],
            "Confirmed"
            if classification.status != "unknown" and matched_by_line_user_id
            else "Pending",
            record.message,
            record.attendance_intent,
        ])
        if attendance_record_id is None:
            reply_to_line(
                event.reply_token,
                "Google Sheets is not configured yet. Please contact an administrator.",
            )
            print("Attendance write skipped because spreadsheet config is unavailable.")
            return

        category = LEAVE_TYPE_LABELS[record.status]
        leave_categories = {
            "病假",
            "事假",
            "經痛",
            "特休",
            "半天",
            "回菲律賓",
            "待確認",
            "不出來",
            "取消工讀",
        }
        if category in leave_categories:
            confirmation_card = leave_confirmation_message(
                student_name=student_name,
                leave_date=record.attendance_date.strftime("%Y/%m/%d"),
                category=category,
                record_id=attendance_record_id,
                confirmed=classification.status != "unknown",
                withdrawable=category != "待確認",
            )
            in_group = bool(
                getattr(event.source, "group_id", None)
                or getattr(event.source, "room_id", None)
            )
            if in_group:
                push_to_line(user_id, confirmation_card)
            else:
                reply_to_line(event.reply_token, confirmation_card)

        # Mirror every attendance notice into its dated Monthly Report cell.
        update_monthly_report_cell(
            student_work_id,
            record.attendance_date,
            category,
        )

        print("CLASSIFICATION:", record.status)
        print("CONFIDENCE:", record.confidence)
        print("AI REASONING:", analysis.reasoning)

    except Exception as error:
        import traceback

        print(
            "ATTENDANCE CLASSIFICATION ERROR:",
            repr(error),
        )
        traceback.print_exc()
        reply_to_line(
            event.reply_token,
            "I couldn't save your attendance. Please try again or contact an administrator.",
        )


@handler.add(PostbackEvent)
@private_language_context
def handle_postback(event):
    """Route card actions after validating identity and the exact record."""

    data = parse_qs(str(getattr(event.postback, "data", "") or ""))
    action = data.get("action", [""])[0]
    record_id = data.get("record_id", [""])[0]
    user_id = str(getattr(event.source, "user_id", None) or "").strip() or None
    group_id = getattr(event.source, "group_id", None)
    room_id = getattr(event.source, "room_id", None)

    if action in {"language_settings", "set_language"}:
        if getattr(event.source, "type", "") != "user" or not user_id:
            reply_to_line(event.reply_token, "Please change your language in a private chat with the bot.")
            return
        if action == "language_settings":
            reply_to_line(event.reply_token, language_settings_message())
            return
        language = data.get("language", [""])[0]
        try:
            if language == "zh-TW" and not os.getenv("GEMINI_API_KEY"):
                raise RuntimeError("AI translation is not configured.")
            set_user_language(user_id, language)
            reply_to_line(event.reply_token, "Language set to English." if language == "en" else "語言已設定為繁體中文。")
        except (ValueError, RuntimeError):
            reply_to_line(event.reply_token, "I couldn't save your language setting. Please contact an administrator.")
        return

    if action in {"help", "hello"}:
        student = resolve_student_from_event(event)
        reply_to_line(event.reply_token, welcome_message(student=student))
        return

    if action in {"authorize_account", "agree_terms"}:
        if getattr(event.source, "type", "") != "user" or not user_id:
            reply_to_line(event.reply_token, "Please authorize your account in a private chat with the bot.")
            return
        try:
            # Resolve the sender from LINE, never a student ID supplied in the button.
            ident = identify_or_register_student(event)
            student = ident.student
            if student:
                save_account_authorization(user_id, str(student["student_id"]).strip())
                reply_to_line(event.reply_token, terms_agreement_confirmed_message(student))
            else:
                reply_to_line(
                    event.reply_token,
                    initialization_message(student=None, display_name=ident.display_name, error_status=ident.status),
                )
        except Exception as error:
            print("ACCOUNT AUTHORIZATION ERROR:", type(error).__name__)
            reply_to_line(event.reply_token, "I couldn't save your account authorization. Please try again or contact an administrator.")
        return

    if action == "richmenu_attendance":
        student = resolve_student_from_event(event)
        if not student:
            display_name = get_line_display_name(user_id) if user_id else None
            reply_to_line(
                event.reply_token,
                initialization_message(student=None, display_name=display_name, error_status="unmatched"),
            )
            return
        student_id = str(student["student_id"])
        target_month = _today_taipei().replace(day=1)
        summary = get_student_attendance_summary(student_id, target_month)
        msg = my_attendance_message(summary, month_label=target_month.strftime("%B %Y"))
        reply_to_line(event.reply_token, msg)
        return

    if action == "richmenu_leave_history":
        student = resolve_student_from_event(event)
        if not student:
            display_name = get_line_display_name(user_id) if user_id else None
            reply_to_line(
                event.reply_token,
                initialization_message(student=None, display_name=display_name, error_status="unmatched"),
            )
            return
        student_id = str(student["student_id"])
        records = get_student_leave_records(student_id)
        msg = leave_history_message(records, month_label=_today_taipei().strftime("%B %Y"))
        reply_to_line(event.reply_token, msg)
        return

    if action == "richmenu_salary":
        student = resolve_student_from_event(event)
        if not student:
            display_name = get_line_display_name(user_id) if user_id else None
            reply_to_line(
                event.reply_token,
                initialization_message(student=None, display_name=display_name, error_status="unmatched"),
            )
            return
        student_id = str(student["student_id"])
        target_month = _today_taipei().replace(day=1)
        try:
            full_days, half_days = get_monthly_attendance_counts(student_id, target_month)
            estimate = calculate_salary(full_days, half_days)
            msg = salary_overview_message(
                estimate,
                month_label=target_month.strftime("%B %Y"),
                target_month_key=target_month.strftime("%Y-%m"),
            )
        except Exception as error:
            print("SALARY LOOKUP ERROR:", repr(error))
            msg = "Could not calculate salary estimate. Please contact an administrator."
        is_private = getattr(event.source, "type", "") == "user"
        if not is_private:
            if user_id and push_to_line(user_id, msg):
                reply_to_line(event.reply_token, "I sent your salary estimate in a private message.")
            else:
                reply_to_line(event.reply_token, "For privacy, please open a private chat with CSIE Attendance and choose Salary Inquiry.")
        else:
            reply_to_line(event.reply_token, msg)
        return

    if action == "salary_breakdown":
        student = resolve_student_from_event(event)
        if not student:
            reply_to_line(event.reply_token, "Student record not found.")
            return
        student_id = str(student["student_id"])
        target_month = _today_taipei().replace(day=1)
        month_arg = data.get("month", [""])[0]
        if month_arg:
            try:
                target_month = date.fromisoformat(f"{month_arg[:7]}-01")
            except ValueError:
                pass
        try:
            full_days, half_days = get_monthly_attendance_counts(student_id, target_month)
            estimate = calculate_salary(full_days, half_days)
            msg = salary_breakdown_message(estimate, month_label=target_month.strftime("%B %Y"))
            reply_to_line(event.reply_token, msg)
        except Exception as error:
            print("SALARY BREAKDOWN ERROR:", repr(error))
            reply_to_line(event.reply_token, "Could not load salary breakdown.")
        return

    if action == "richmenu_schedule":
        schedule_list = get_work_calendar_schedule(days=7)
        msg = work_schedule_message(schedule_list, title_label="Upcoming 7 Days")
        reply_to_line(event.reply_token, msg)
        return

    if action == "richmenu_leave_request":
        student = resolve_student_from_event(event)
        student_name = str(student.get("name", "")) if student else None
        msg = leave_request_menu_message(student_name)
        reply_to_line(event.reply_token, msg)
        return

    if action == "richmenu_help":
        tickets = []
        student = resolve_student_from_event(event)
        if student:
            tickets = get_student_tickets(str(student["student_id"]))
        msg = help_center_message(tickets)
        reply_to_line(event.reply_token, msg)
        return

    if action == "request_leave_type":
        cat = data.get("category", ["Leave"])[0]
        reply_to_line(
            event.reply_token,
            f"📝 Apply for {cat}:\n\n"
            "Please send your leave notice in this format:\n\n"
            f"Leave YYYY-MM-DD {cat} <reason>\n\n"
            f"Example: Leave {_today_taipei().isoformat()} {cat} Feeling unwell\n\n"
            "⚠️ Note: Submission will be flagged for administrator review and does not automatically imply approval.",
        )
        return

    if action == "ticket_prompt":
        cat = data.get("category", ["Inquiry"])[0]
        reply_to_line(
            event.reply_token,
            f"🎫 Submit Ticket ({cat}):\n\n"
            "Please send your request or correction details:\n\n"
            f"/ticket [{cat}] <details of your request>\n\n"
            "Example: /ticket [Attendance Correction] Please review my absence on 2026-10-08",
        )
        return

    if action == "statusme":
        student = resolve_student_from_event(event)
        student_id = str(student["student_id"]) if student else None

        try:
            response = handle_command(
                "/statusme",
                tracker,
                user_id,
                student_id=student_id,
            )
        except Exception as error:
            print("POSTBACK COMMAND ERROR:", repr(error))
            response = "The request could not be completed. Please contact an administrator."
        if response is not None:
            if (group_id or room_id) and user_id:
                if push_to_line(user_id, response):
                    reply_to_line(
                        event.reply_token,
                        "I sent your status in a private message.",
                    )
                else:
                    reply_to_line(
                        event.reply_token,
                        "For privacy, I couldn't send your status here. Please "
                        "open a private chat with CSIE Attendance and choose My Status.",
                    )
            else:
                reply_to_line(event.reply_token, response)
        return

    if action == "salary":
        student = resolve_student_from_event(event)
        student_id = str(student["student_id"]) if student else None

        is_private = getattr(event.source, "type", "") == "user"
        try:
            response = handle_command(
                "/salary",
                tracker,
                user_id,
                student_id=student_id,
                is_private=True,
            )
        except Exception as error:
            print("SALARY POSTBACK ERROR:", repr(error))
            response = "The salary estimate could not be retrieved. Please contact an administrator."
        if response is not None:
            if not is_private:
                if user_id and push_to_line(user_id, response):
                    reply_to_line(
                        event.reply_token,
                        "I sent your salary estimate in a private message.",
                    )
                else:
                    reply_to_line(
                        event.reply_token,
                        "For privacy, please open a private chat with CSIE Attendance and choose Salary.",
                    )
            else:
                reply_to_line(event.reply_token, response)
        return

    if action == "contact":
        reply_to_line(
            event.reply_token,
            "To contact an administrator, send /ticket followed by your "
            "request in a private chat with CSIE Attendance.",
        )
        return

    if action == "cancel_withdraw":
        reply_to_line(event.reply_token, "Your leave was not withdrawn.")
        return

    if action not in {"correction", "withdraw", "confirm_withdraw"}:
        print("Unknown LINE postback action:", action)
        return

    if not user_id or not record_id:
        reply_to_line(
            event.reply_token,
            "This attendance action is invalid or has expired. Please check "
            "your status again.",
        )
        return

    try:
        attendance = get_attendance_record_by_id(record_id)
        student = find_student_by_line_user_id(user_id)
    except Exception as error:
        print("ATTENDANCE POSTBACK LOOKUP ERROR:", repr(error))
        reply_to_line(
            event.reply_token,
            "I couldn't retrieve this attendance record. Please contact an administrator.",
        )
        return
    if (
        attendance is None
        or student is None
        or str(student.get("student_id", "")) != attendance.get("student_id")
    ):
        reply_to_line(
            event.reply_token,
            "This attendance record is unavailable or does not belong to your account.",
        )
        return

    attendance_date = date.fromisoformat(attendance["date"])
    category = attendance.get("type", "待確認")
    if action == "correction":
        try:
            ticket_id = create_ticket(
                str(student["student_id"]),
                user_id,
                (
                    f"Correction request for attendance record {record_id} "
                    f"({attendance_date.isoformat()}, {category}). "
                    "Please review this saved attendance and contact the student "
                    "to confirm the requested correction."
                ),
            )
        except Exception as error:
            print("ATTENDANCE CORRECTION REQUEST ERROR:", repr(error))
            reply_to_line(
                event.reply_token,
                "Your correction request could not be submitted. Please try "
                "again or contact an administrator.",
            )
            return
        reply_to_line(
            event.reply_token,
            f"Correction request #{ticket_id} was sent to an administrator for review.",
        )
        return

    if action == "withdraw":
        if attendance_date < _today_taipei():
            reply_to_line(
                event.reply_token,
                "Past attendance records cannot be withdrawn from this card. "
                "Please contact an administrator.",
            )
            return
        expires = int(time.time()) + 600
        signature = _withdrawal_signature(record_id, user_id, expires)
        confirm_data = (
            f"action=confirm_withdraw&record_id={record_id}"
            f"&expires={expires}&token={signature}"
        )
        reply_to_line(
            event.reply_token,
            withdrawal_confirmation_message(
                category=category,
                leave_date=attendance_date.strftime("%Y/%m/%d"),
                record_id=record_id,
                confirmation_data=confirm_data,
            ),
        )
        return

    if action == "confirm_withdraw":
        expires_text = data.get("expires", [""])[0]
        token = data.get("token", [""])[0]
        try:
            expires = int(expires_text)
        except ValueError:
            expires = 0
        expected_signature = _withdrawal_signature(record_id, user_id, expires)
        if (
            expires < int(time.time())
            or not token
            or not hmac.compare_digest(token, expected_signature)
            or attendance_date < _today_taipei()
        ):
            reply_to_line(
                event.reply_token,
                "This withdrawal confirmation has expired or is invalid. "
                "Please start again from the attendance card.",
            )
            return
        try:
            deleted = delete_attendance_record(
                str(student["student_id"]),
                attendance_date,
                user_id,
                leave_only=True,
                attendance_record_id=record_id,
            )
        except Exception as error:
            print("ATTENDANCE WITHDRAWAL ERROR:", repr(error))
            reply_to_line(
                event.reply_token,
                "I couldn't withdraw this leave. Please contact an administrator.",
            )
            return
        if deleted is None:
            reply_to_line(
                event.reply_token,
                "This leave is no longer available to withdraw.",
            )
            return
        reply_to_line(
            event.reply_token,
            f"Your leave for {attendance_date.strftime('%Y/%m/%d')} "
            f"({category}) was withdrawn.",
        )


def _withdrawal_signature(record_id: str, user_id: str, expires: int) -> str:
    payload = f"{record_id}|{user_id}|{expires}".encode()
    return hmac.new(
        str(CHANNEL_SECRET).encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()


def _today_taipei() -> date:
    return datetime.now(ZoneInfo("Asia/Taipei")).date()