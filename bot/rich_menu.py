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


ADMIN_MENU_NAME = "CSIE Admin Portal"
_ADMIN_MENU_ID = None
_MENU_ROLE_CACHE = {}


def build_rich_menu_request(name: str | None = None, *, admin: bool = False) -> RichMenuRequest:
    labels = ["My Attendance", "Leave History", "Salary Inquiry", "Time Out Report" if admin else "Work Schedule", "Attendance Status" if admin else "Leave Request", "Help Center"]
    actions = ["richmenu_attendance", "richmenu_leave_history", "richmenu_salary", "admin_timeout" if admin else "richmenu_schedule", "admin_attendance" if admin else "richmenu_leave_request", "admin_tickets" if admin else "richmenu_help"]
    widths = [833, 834, 833]
    positions = [0, 833, 1667]
    return RichMenuRequest(
        size=RichMenuSize(width=2500, height=1686), selected=True,
        name=name or (ADMIN_MENU_NAME if admin else BASE_MENU_NAME),
        chat_bar_text="Admin Portal" if admin else CHAT_BAR_TEXT,
        areas=[RichMenuArea(
            bounds=RichMenuBounds(x=positions[index % 3], y=(index // 3) * 843, width=widths[index % 3], height=843),
            action=PostbackAction(label=label, data=f"action={actions[index]}", display_text=label),
        ) for index, label in enumerate(labels)],
    )


def _link_administrator_menu(messaging_api, menu_id):
    global _ADMIN_MENU_ID
    from bot.commands import _admin_ids
    _ADMIN_MENU_ID = menu_id
    linked = True
    for user_id in _admin_ids():
        if user_id.startswith("U"):
            try:
                messaging_api.link_rich_menu_id_to_user(user_id, menu_id)
            except Exception as error:
                linked = False
                print("ADMIN MENU LINK ERROR:", type(error).__name__)
    return linked


def sync_user_menu(user_id: str, *, force=False):
    """Refresh role-specific menus; permission checks still run on every action."""
    from bot.commands import is_admin_user
    if not user_id or not _ADMIN_MENU_ID:
        return
    admin = is_admin_user(user_id)
    if not force and _MENU_ROLE_CACHE.get(user_id) == admin:
        return
    with ApiClient(Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))) as client:
        api = MessagingApi(client)
        if admin:
            api.link_rich_menu_id_to_user(user_id, _ADMIN_MENU_ID)
        else:
            try:
                current = api.get_rich_menu_id_of_user(user_id)
                menu_id = getattr(current, "rich_menu_id", None)
                if menu_id == _ADMIN_MENU_ID:
                    api.unlink_rich_menu_id_from_user(user_id)
            except Exception:
                pass  # No per-user menu is normal for a student.
    if len(_MENU_ROLE_CACHE) >= 10000:
        _MENU_ROLE_CACHE.clear()
    _MENU_ROLE_CACHE[user_id] = admin


def setup_rich_menu(*, force: bool = False, target_image: Path | None = None, admin: bool = False) -> str | None:
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

    img_path = target_image or (IMAGE_DIR / "admin_rich_menu.png" if admin else (
        IMAGE_DIR / "rich_menu.jpg"
        if (IMAGE_DIR / "rich_menu.jpg").exists()
        else IMAGE_DIR / "rich_menu.png"
    ))
    if not img_path.exists():
        print(f"RICH MENU SETUP: Image file not found at {img_path}")
        return None

    img_hash = get_image_hash(img_path)
    base_name = ADMIN_MENU_NAME if admin else BASE_MENU_NAME
    target_menu_name = f"{base_name} ({img_hash})"

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
                    if admin:
                        _link_administrator_menu(messaging_api, current_active_menu.rich_menu_id)
                        return current_active_menu.rich_menu_id
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
            rich_menu_req = build_rich_menu_request(name=target_menu_name, admin=admin)
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
            linked = True
            if admin:
                linked = _link_administrator_menu(messaging_api, new_rich_menu_id)
            else:
                messaging_api.set_default_rich_menu(new_rich_menu_id)
            print(f"RICH MENU ACTIVATED: {new_rich_menu_id}")

            # 4. Clean up old menus now that the new one is active
            if menu_list and linked:
                for menu in menu_list.richmenus:
                    if menu.rich_menu_id != new_rich_menu_id and menu.name.startswith(base_name + " ("):
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
