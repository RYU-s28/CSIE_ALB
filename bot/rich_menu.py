"""LINE Bot Rich Menu configuration and setup."""

from __future__ import annotations

import hashlib
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

BASE_MENU_NAME = "CSIE Student Portal"
CHAT_BAR_TEXT = "Portal Menu"
IMAGE_DIR = Path(__file__).resolve().parent.parent / "assets"
IMAGE_PATH = IMAGE_DIR / "rich_menu.jpg" if (IMAGE_DIR / "rich_menu.jpg").exists() else IMAGE_DIR / "rich_menu.png"


def get_image_hash(path: Path) -> str:
    """Compute an 8-character hash of the image content to detect asset updates."""
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()[:8]
    except Exception:
        return "default"


def build_rich_menu_request(name: str | None = None) -> RichMenuRequest:
    """Build the 6-tile RichMenuRequest matching the LINE large 6-tile template (2500x1686)."""
    return RichMenuRequest(
        size=RichMenuSize(width=2500, height=1686),
        selected=True,
        name=name or BASE_MENU_NAME,
        chat_bar_text=CHAT_BAR_TEXT,
        areas=[
            # Row 1, Col 1: My Attendance (833 x 843)
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                action=PostbackAction(
                    label="My Attendance",
                    data="action=richmenu_attendance",
                    display_text="My Attendance",
                ),
            ),
            # Row 1, Col 2: Leave History (834 x 843)
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=0, width=834, height=843),
                action=PostbackAction(
                    label="Leave History",
                    data="action=richmenu_leave_history",
                    display_text="Leave History",
                ),
            ),
            # Row 1, Col 3: Salary Inquiry (833 x 843)
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                action=PostbackAction(
                    label="Salary Inquiry",
                    data="action=richmenu_salary",
                    display_text="Salary Inquiry",
                ),
            ),
            # Row 2, Col 1: Work Schedule (833 x 843)
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=843, width=833, height=843),
                action=PostbackAction(
                    label="Work Schedule",
                    data="action=richmenu_schedule",
                    display_text="Work Schedule",
                ),
            ),
            # Row 2, Col 2: Leave Request (834 x 843)
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=843, width=834, height=843),
                action=PostbackAction(
                    label="Leave Request",
                    data="action=richmenu_leave_request",
                    display_text="Leave Request",
                ),
            ),
            # Row 2, Col 3: Help Center (833 x 843)
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=843, width=833, height=843),
                action=PostbackAction(
                    label="Help Center",
                    data="action=richmenu_help",
                    display_text="Help Center",
                ),
            ),
        ],
    )


def setup_rich_menu(*, force: bool = False, target_image: Path | None = None) -> str | None:
    """Create, upload image for, and set default Rich Menu in LINE.
    
    Guarantees:
    1. Detects image content changes via hash; auto-updates when asset changes.
    2. Avoids recreating the menu on every deployment if already active with matching hash.
    3. When replacing, creates and uploads new menu first; links as default ONLY after success.
    4. Cleans up obsolete rich menus only after successful replacement.
    """
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("RICH MENU SETUP: LINE_CHANNEL_ACCESS_TOKEN is missing.")
        return None

    img_path = target_image or (
        IMAGE_DIR / "rich_menu.jpg"
        if (IMAGE_DIR / "rich_menu.jpg").exists()
        else IMAGE_DIR / "rich_menu.png"
    )
    if not img_path.exists():
        print(f"RICH MENU SETUP: Image file not found at {img_path}")
        return None

    img_hash = get_image_hash(img_path)
    target_menu_name = f"{BASE_MENU_NAME} ({img_hash})"

    configuration = Configuration(access_token=token)
    try:
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)

            # Avoid recreating on every deployment: check for existing menu with matching hash
            menu_list = None
            try:
                menu_list = messaging_api.get_rich_menu_list()
                current_active_menu = None
                for menu in menu_list.richmenus:
                    if (
                        menu.name == target_menu_name
                        and menu.size.width == 2500
                        and menu.size.height == 1686
                    ):
                        current_active_menu = menu
                        break

                if current_active_menu and not force:
                    # Check if already set as default
                    try:
                        def_res = messaging_api.get_default_rich_menu_id()
                        current_def_id = getattr(def_res, "rich_menu_id", str(def_res))
                        if current_def_id == current_active_menu.rich_menu_id:
                            print(f"RICH MENU SETUP: Menu with hash {img_hash} is already active and default. Skipping recreation.")
                            return current_active_menu.rich_menu_id
                    except Exception:
                        pass
                    # If exists with matching hash but not default, set as default
                    messaging_api.set_default_rich_menu(current_active_menu.rich_menu_id)
                    print(f"RICH MENU SETUP: Set menu with hash {img_hash} as default.")
                    return current_active_menu.rich_menu_id
            except Exception as error:
                print("RICH MENU LOOKUP WARNING:", repr(error))

            # 1. Create a NEW Rich Menu first (preserving existing menu until replacement is ready)
            rich_menu_req = build_rich_menu_request(name=target_menu_name)
            response = messaging_api.create_rich_menu(rich_menu_request=rich_menu_req)
            new_rich_menu_id = response.rich_menu_id
            print(f"RICH MENU CREATED: {new_rich_menu_id} ({target_menu_name})")

            # 2. Upload Image
            with open(img_path, "rb") as image_file:
                image_data = image_file.read()

            content_type = "image/jpeg" if img_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            upload_url = f"https://api-data.line.me/v2/bot/richmenu/{new_rich_menu_id}/content"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
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
                    try:
                        messaging_api.delete_rich_menu(new_rich_menu_id)
                    except Exception:
                        pass
                    return None

            print(f"RICH MENU IMAGE UPLOADED: {new_rich_menu_id}")

            # 3. Link the new menu as the default ONLY after successful creation and upload
            messaging_api.set_default_rich_menu(new_rich_menu_id)
            print(f"RICH MENU SET AS DEFAULT: {new_rich_menu_id}")

            # 4. Clean up old menus now that the new one is active
            if menu_list:
                for menu in menu_list.richmenus:
                    if menu.rich_menu_id != new_rich_menu_id:
                        try:
                            messaging_api.delete_rich_menu(menu.rich_menu_id)
                            print(f"RICH MENU CLEANED UP OLD MENU: {menu.rich_menu_id}")
                        except Exception:
                            pass

            return new_rich_menu_id

    except Exception as error:
        print("RICH MENU SETUP ERROR:", repr(error))
        return None


if __name__ == "__main__":
    menu_id = setup_rich_menu(force=True)
    if menu_id:
        print(f"Successfully configured Rich Menu: {menu_id}")
    else:
        print("Failed to configure Rich Menu.")
