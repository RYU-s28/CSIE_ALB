"""Helpers for talking to the LINE Messaging API."""

import os

from linebot import LineBotApi
from linebot.models import TextSendMessage


class LineClient:
    def __init__(self) -> None:
        self.channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        self.line_bot_api = LineBotApi(self.channel_access_token) if self.channel_access_token else None

    def reply(self, reply_token: str, text: str) -> bool:
        if not self.line_bot_api:
            return False
        self.line_bot_api.reply_message(reply_token, TextSendMessage(text=text))
        return True
