import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

from attendance.attendance import AttendanceTracker
from attendance.ai_classifier import classify_attendance_message
from attendance.leave_message import (
    LEAVE_TYPE_LABELS,
    parse_attendance_date,
)
from bot.commands import handle_command, normalize_command
from database.google_sheets import (
    append_attendance_row,
    find_students_by_display_name,
    find_student_by_line_user_id,
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
def reply_to_line(reply_token: str, message: str):
    try:
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)

            reply_request = ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=message)
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
        classification = classify_attendance_message(text)
    except Exception as error:
        import traceback

        print("ATTENDANCE AI CLASSIFICATION ERROR:", repr(error))
        traceback.print_exc()
        reply_to_line(
            event.reply_token,
            "I couldn't classify this attendance message. Please try again "
            "or contact an administrator.",
        )
        return

    if classification.status == "unrelated":
        print(
            "Non-attendance LINE message ignored:",
            f"confidence={classification.confidence:.2f}",
            f"matched_keyword={classification.matched_keyword}",
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
        record = tracker.add_from_message(
            student_id=student_work_id,
            message=text,
            attendance_date=attendance_date,
            classification_result=classification,
        )

        if not append_attendance_row([
            record.student_id,
            student_name,
            record.attendance_date.isoformat(),
            LEAVE_TYPE_LABELS[record.status],
            "Confirmed"
            if classification.status != "unknown" and matched_by_line_user_id
            else "Pending",
            record.message,
            record.attendance_intent,
        ]):
            reply_to_line(
                event.reply_token,
                "Google Sheets is not configured yet. Please contact an administrator.",
            )
            print("Attendance write skipped because spreadsheet config is unavailable.")
            return

        reply_to_line(
            event.reply_token,
            f"Attendance saved for {student_name}: "
            f"{LEAVE_TYPE_LABELS[record.status]} on "
            f"{record.attendance_date.isoformat()}.",
        )

        print("CLASSIFICATION:", record.status)
        print("CONFIDENCE:", record.confidence)
        print("MATCHED KEYWORD:", record.matched_keyword)

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