"""LINE Bot Rich Menu configuration and setup."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PostbackAction,
    RichMenuArea,
    RichMenuBounds,
    RichMenuRequest,
    RichMenuSize,
)

RICH_MENU_NAME = "CSIE Student Portal"
CHAT_BAR_TEXT = "Portal Menu · 選單"
IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "rich_menu.png"


def build_rich_menu_request() -> RichMenuRequest:
    """Build the 6-tile RichMenuRequest matching the CSIE Student Portal design."""
    return RichMenuRequest(
        size=RichMenuSize(width=2500, height=946),
        selected=True,
        name=RICH_MENU_NAME,
        chat_bar_text=CHAT_BAR_TEXT,
        areas=[
            # Row 1, Col 1: My Attendance (出勤紀錄)
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=833, height=530),
                action=PostbackAction(
                    label="My Attendance",
                    data="action=richmenu_attendance",
                    display_text="出勤紀錄",
                ),
            ),
            # Row 1, Col 2: Leave History (請假紀錄)
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=0, width=834, height=530),
                action=PostbackAction(
                    label="Leave History",
                    data="action=richmenu_leave_history",
                    display_text="請假紀錄",
                ),
            ),
            # Row 1, Col 3: Salary Inquiry (薪資查詢)
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=0, width=833, height=530),
                action=PostbackAction(
                    label="Salary Inquiry",
                    data="action=richmenu_salary",
                    display_text="薪資查詢",
                ),
            ),
            # Row 2, Col 1: Work Schedule (工作日曆)
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=530, width=833, height=416),
                action=PostbackAction(
                    label="Work Schedule",
                    data="action=richmenu_schedule",
                    display_text="工作日曆",
                ),
            ),
            # Row 2, Col 2: Leave Request (請假申請)
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=530, width=834, height=416),
                action=PostbackAction(
                    label="Leave Request",
                    data="action=richmenu_leave_request",
                    display_text="請假申請",
                ),
            ),
            # Row 2, Col 3: Help Center (服務中心)
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=530, width=833, height=416),
                action=PostbackAction(
                    label="Help Center",
                    data="action=richmenu_help",
                    display_text="服務中心",
                ),
            ),
        ],
    )


def setup_rich_menu(*, force: bool = False) -> str | None:
    """Create, upload image for, and set default Rich Menu in LINE."""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("RICH MENU SETUP: LINE_CHANNEL_ACCESS_TOKEN is missing.")
        return None

    if not IMAGE_PATH.exists():
        print(f"RICH MENU SETUP: Image file not found at {IMAGE_PATH}")
        return None

    configuration = Configuration(access_token=token)
    try:
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)

            if not force:
                try:
                    menu_list = messaging_api.get_rich_menu_list()
                    for menu in menu_list.richmenus:
                        if menu.name == RICH_MENU_NAME:
                            messaging_api.set_default_rich_menu(menu.rich_menu_id)
                            print(f"RICH MENU SETUP: Reusing existing menu {menu.rich_menu_id}")
                            return menu.rich_menu_id
                except Exception as error:
                    print("RICH MENU LOOKUP WARNING:", repr(error))

            # 1. Create Rich Menu
            rich_menu_req = build_rich_menu_request()
            response = messaging_api.create_rich_menu(rich_menu_request=rich_menu_req)
            rich_menu_id = response.rich_menu_id
            print(f"RICH MENU CREATED: {rich_menu_id}")

            # 2. Upload Image
            with open(IMAGE_PATH, "rb") as image_file:
                image_data = image_file.read()

            upload_url = f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            }
            upload_req = urllib.request.Request(
                upload_url,
                data=image_data,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(upload_req, timeout=30) as upload_response:
                if upload_response.status not in {200, 201}:
                    print(f"RICH MENU IMAGE UPLOAD FAILED: {upload_response.status}")
                    return None

            print(f"RICH MENU IMAGE UPLOADED: {rich_menu_id}")

            # 3. Set Default Rich Menu
            messaging_api.set_default_rich_menu(rich_menu_id)
            print(f"RICH MENU SET AS DEFAULT: {rich_menu_id}")
            return rich_menu_id

    except Exception as error:
        print("RICH MENU SETUP ERROR:", repr(error))
        return None


if __name__ == "__main__":
    menu_id = setup_rich_menu(force=True)
    if menu_id:
        print(f"Successfully configured Rich Menu: {menu_id}")
    else:
        print("Failed to configure Rich Menu.")
