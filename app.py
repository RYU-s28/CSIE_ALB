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
from datetime import date
from attendance.report import build_report


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

    normalized_text = text.strip().lower()

    print("------------------------------")
    print("USER:", user_id)
    print("GROUP:", group_id)
    print("MESSAGE:", text)

    # --------------------------------------------------
    # /ping
    # --------------------------------------------------

    if normalized_text in {"ping", "/ping"}:
        reply_to_line(
            event.reply_token,
            "Pong! Attendance bot is online ✅"
        )
        return

    # --------------------------------------------------
    # /statusme
    # Show this user's current status
    # --------------------------------------------------

    if normalized_text == "/statusme":
        record = tracker.get_record(user_id)

        if not record:
            reply_to_line(
                event.reply_token,
                "No attendance record found for you today."
            )
            return

        message = (
            f"Your current status:\n"
            f"{record.status}\n"
            f"Confidence: {record.confidence:.0%}\n"
            f"Keyword: {record.matched_keyword or 'None'}"
        )

        reply_to_line(
            event.reply_token,
            message,
        )

        return

    # --------------------------------------------------
    # /summary
    # --------------------------------------------------

    if normalized_text == "/summary":
        summary = tracker.get_summary()

        message = (
            "📊 Today's Attendance Summary\n\n"
            f"✅ Present: {summary.get('present', 0)}\n"
            f"⏰ Late: {summary.get('late', 0)}\n"
            f"🤒 Sick leave: {summary.get('sick_leave', 0)}\n"
            f"📋 Personal leave: {summary.get('personal_leave', 0)}\n"
            f"🌸 Menstrual leave: {summary.get('menstrual_leave', 0)}\n"
            f"✈️ Abroad: {summary.get('abroad', 0)}\n"
            f"❓ Unknown: {summary.get('unknown', 0)}"
        )

        reply_to_line(
            event.reply_token,
            message,
        )

        return

    # --------------------------------------------------
    # /report
    # Build the full attendance report text and send immediately
    # --------------------------------------------------

    if normalized_text == "/report":
        records = tracker.get_records_for_date()

        total_students = len({r.student_id for r in records})

        report = build_report(
            report_date=date.today(),
            total_students=total_students,
            records=records,
        )

        reply_to_line(
            event.reply_token,
            report,
        )

        return

    # --------------------------------------------------
    # /absent
    # --------------------------------------------------

    if normalized_text == "/absent":
        absent_statuses = {
            "sick_leave",
            "personal_leave",
            "menstrual_leave",
            "abroad",
        }

        records = tracker.get_records_for_date()

        absent_records = [
            record
            for record in records
            if record.status in absent_statuses
        ]

        if not absent_records:
            reply_to_line(
                event.reply_token,
                "No absent students recorded today."
            )
            return

        lines = ["❌ Currently absent:"]

        for record in absent_records:
            lines.append(
                f"{record.student_id} — {record.status}"
            )

        reply_to_line(
            event.reply_token,
            "\n".join(lines),
        )

        return

    # --------------------------------------------------
    # /status
    # Show everything currently stored
    # --------------------------------------------------

    if normalized_text == "/status":
        records = tracker.get_records_for_date()

        if not records:
            reply_to_line(
                event.reply_token,
                "No attendance records stored for today."
            )
            return

        lines = [
            "📋 Current attendance records",
            ""
        ]

        for record in records:
            lines.append(
                f"{record.student_id}\n"
                f"→ {record.status} "
                f"({record.confidence:.0%})"
            )

        reply_to_line(
            event.reply_token,
            "\n".join(lines),
        )

        return

    # --------------------------------------------------
    # /clear
    # Development only!
    # --------------------------------------------------

    if normalized_text == "/clear":
        from datetime import date

        tracker.clear_date(date.today())

        reply_to_line(
            event.reply_token,
            "Today's attendance records cleared."
        )

        return

    # --------------------------------------------------
    # No user ID
    # --------------------------------------------------

    if not user_id:
        print("No user ID found. Message ignored.")
        return

    # --------------------------------------------------
    # Normal attendance classification
    # --------------------------------------------------

    try:
        record = tracker.add_from_message(
            student_id=user_id,
            message=text,
        )

        print("CLASSIFICATION:", record.status)
        print("CONFIDENCE:", record.confidence)
        print("MATCHED KEYWORD:", record.matched_keyword)

    except Exception as error:
        print(
            "ATTENDANCE CLASSIFICATION ERROR:",
            repr(error),
        )