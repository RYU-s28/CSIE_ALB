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
from bot.commands import handle_command, is_admin_user, normalize_command
from bot.line_ui import welcome_message
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
    LineRegistrationConflictError,
    register_line_user,
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


@handler.add(
    MessageEvent,
    message=TextMessageContent,
)
def handle_message(event):
    text = event.message.text or ""

    user_id = str(getattr(event.source, "user_id", None) or "").strip() or None
    requested_command = normalize_command(text)
    if requested_command == "hello" or (
        requested_command == "help" and not is_admin_user(user_id)
    ):
        reply_to_line(event.reply_token, welcome_message())
        return

    group_id = getattr(
        event.source,
        "group_id",
        None,
    )
    print("------------------------------")
    print("USER:", user_id)
    print("GROUP:", group_id)
    print("MESSAGE:", text)

    command_student_id = None
    if user_id and normalize_command(text) in {"statusme", "clear", "ticket"}:
        try:
            student = find_student_by_line_user_id(user_id)
            if student:
                command_student_id = str(student["student_id"])
        except Exception as error:
            print("STUDENT LOOKUP ERROR:", repr(error))

    try:
        command_response = handle_command(
            text,
            tracker,
            user_id,
            student_id=command_student_id,
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
def handle_postback(event):
    """Route card actions after validating identity and the exact record."""

    data = parse_qs(str(getattr(event.postback, "data", "") or ""))
    action = data.get("action", [""])[0]
    record_id = data.get("record_id", [""])[0]
    user_id = str(getattr(event.source, "user_id", None) or "").strip() or None
    group_id = getattr(event.source, "group_id", None)
    room_id = getattr(event.source, "room_id", None)

    if action == "help":
        reply_to_line(event.reply_token, welcome_message())
        return

    if action == "statusme":
        student_id = None
        if user_id:
            try:
                student = find_student_by_line_user_id(user_id)
                if student:
                    student_id = str(student["student_id"])
            except Exception as error:
                print("STUDENT LOOKUP ERROR:", repr(error))

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