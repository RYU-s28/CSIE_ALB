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
from bot.commands import handle_command


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

    print("------------------------------")
    print("USER:", user_id)
    print("GROUP:", group_id)
    print("MESSAGE:", text)

    command_response = handle_command(text, tracker, user_id)
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