"""LINE Flex message templates for the student-facing interface."""

from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
)


def welcome_message() -> FlexMessage:
    """Build the welcome card shown for explicit hello/help requests."""

    return FlexMessage(
        alt_text="CSIE Attendance Assistant: welcome and student options",
        contents=FlexContainer.from_dict(
            {
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#176B5B",
                    "paddingAll": "20px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "CSIE Attendance Bot",
                            "weight": "bold",
                            "color": "#FFFFFF",
                            "size": "xl",
                        },
                        {
                            "type": "text",
                            "text": "Student attendance assistant",
                            "color": "#D7F2E9",
                            "size": "sm",
                            "margin": "sm",
                        },
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "paddingAll": "20px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Welcome to CSIE Attendance",
                            "weight": "bold",
                            "size": "md",
                            "wrap": True,
                        },
                        {
                            "type": "text",
                            "text": (
                                "I help track leave notifications submitted "
                                "in this LINE chat."
                            ),
                            "size": "sm",
                            "color": "#5B6470",
                            "wrap": True,
                        },
                        {
                            "type": "separator",
                            "margin": "sm",
                        },
                        {
                            "type": "text",
                            "text": "What I can help with",
                            "weight": "bold",
                            "size": "sm",
                            "margin": "sm",
                        },
                        {
                            "type": "text",
                            "text": (
                                "• Recognize leave notifications automatically\n"
                                "• Check your attendance status\n"
                                "• Send a request to an administrator"
                            ),
                            "size": "sm",
                            "color": "#5B6470",
                            "wrap": True,
                        },
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "paddingAll": "16px",
                    "contents": [
                        {
                            "type": "text",
                            "text": (
                                "Personal attendance details are only shown "
                                "in a private chat."
                            ),
                            "size": "xs",
                            "color": "#78828D",
                            "wrap": True,
                        },
                    ],
                },
            }
        ),
        quick_reply=QuickReply(
            items=[
                QuickReplyItem(
                    action=PostbackAction(
                        label="My Status",
                        data="action=statusme",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="Help",
                        data="action=help",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="Contact Admin",
                        data="action=contact",
                    )
                ),
            ]
        ),
    )
