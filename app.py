import os
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
from attendance.classifier import classify_status
from attendance.leave_message import (
    LEAVE_TYPE_LABELS,
    parse_attendance_date,
)
from bot.commands import handle_command, normalize_command
from database.google_sheets import (
    ATTENDANCE_TABLE_RANGE,
    attendance_sheet,
    find_student_by_display_name,
    find_student_by_line_user_id,
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

app = FastAPI()

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
        
@handler.add(
    MessageEvent,
    message=TextMessageContent,
)
def handle_message(event):
    text = event.message.text or ""

    user_id = getattr(
        event.source,
        "user_id",
        None,
    )

    group_id = getattr(
        event.source,
        "group_id",
        None,
    )
    room_id = getattr(
        event.source,
        "room_id",
        None,
    )

    print("------------------------------")
    print("USER:", user_id)
    print("GROUP:", group_id)
    print("MESSAGE:", text)

    command_student_id = None
    if user_id and normalize_command(text) == "statusme":
        try:
            student = find_student_by_line_user_id(user_id)
            if student is None:
                display_name = get_line_display_name(
                    user_id,
                    group_id=group_id,
                    room_id=room_id,
                )
                if display_name:
                    student = find_student_by_display_name(display_name)
            if student:
                command_student_id = student["student_id"]
        except Exception as error:
            print("STUDENT LOOKUP ERROR:", repr(error))

    command_response = handle_command(
        text,
        tracker,
        user_id,
        student_id=command_student_id,
    )
    if command_response is not None:
        reply_to_line(
            event.reply_token,
            command_response,
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
        student = find_student_by_line_user_id(user_id)
        matched_by_line_user_id = student is not None
        if student is None:
            display_name = get_line_display_name(
                user_id,
                group_id=group_id,
                room_id=room_id,
            )
            if display_name:
                student = find_student_by_display_name(display_name)
                if student is not None:
                    print(
                        "Student matched by display name; requires review:",
                        display_name,
                    )

        if student is None:
            reply_to_line(
                event.reply_token,
                "Your LINE account could not be matched to a student record. Ask an administrator to check the Students sheet.",
            )
            print("Unmatched LINE user:", user_id)
            return

        classification = classify_status(text)
        attendance_date = parse_attendance_date(text)
        record = tracker.add_from_message(
            student_id=student["student_id"],
            message=text,
            attendance_date=attendance_date,
        )

        attendance_sheet.append_row([
            record.student_id,
            student["name"],
            record.attendance_date.isoformat(),
            LEAVE_TYPE_LABELS[record.status],
            "Confirmed"
            if classification.status != "unknown" and matched_by_line_user_id
            else "Pending",
            record.message,
        ], table_range=ATTENDANCE_TABLE_RANGE, value_input_option="RAW")

        reply_to_line(
            event.reply_token,
            f"Attendance saved for {student['name']}: "
            f"{LEAVE_TYPE_LABELS[record.status]} on "
            f"{record.attendance_date.isoformat()}.",
        )

        print("CLASSIFICATION:", record.status)
        print("CONFIDENCE:", record.confidence)
        print("MATCHED KEYWORD:", record.matched_keyword)

    except Exception as error:
        print(
            "ATTENDANCE CLASSIFICATION ERROR:",
            repr(error),
        )
        reply_to_line(
            event.reply_token,
            "I couldn't save your attendance. Please try again or contact an administrator.",
        )