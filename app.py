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


load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError(
        "LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN are required."
    )


app = FastAPI()

configuration = Configuration(
    access_token=CHANNEL_ACCESS_TOKEN
)

handler = WebhookHandler(CHANNEL_SECRET)

tracker = AttendanceTracker()


@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "LINE Attendance Bot",
    }


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
            detail="Invalid signature",
        )

    return "OK"


@handler.add(
    MessageEvent,
    message=TextMessageContent,
)
def handle_message(event):
    text = event.message.text

    user_id = event.source.user_id
    group_id = getattr(
        event.source,
        "group_id",
        None,
    )

    print("USER:", user_id)
    print("GROUP:", group_id)
    print("MESSAGE:", text)

    record = tracker.add_from_message(
        student_id=user_id,
        message=text,
    )

    print(
        f"Classification: "
        f"{record.status} "
        f"({record.confidence})"
    )