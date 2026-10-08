# CSIE_ALB
Attendance Line Bot Automation for automatic attendance making for class internship

## Google Sheets

Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the service account credentials JSON and
`GOOGLE_SHEET_ID` to the spreadsheet ID. Share the spreadsheet with the service
account's email address, with edit access.

The bot writes attendance to the `Attendance` worksheet, with columns
`student_id`, `name`, `date`, `type`, `status`, `raw_message`, and
`attendance_intent`. It creates
this worksheet and its header row if they do not exist. For an existing workbook
with a populated `Logs` tab and an empty `Attendance` tab, it continues writing
to the `Logs` table at `B4:H` so existing log data remains connected. The
`attendance_intent` field is added to existing attendance tables when needed
and backfilled from existing message text when possible. It marks unclear
absence messages separately from their `待確認` type. These pending absences
are excluded from the report's present count. The `Monthly Report` worksheet
is not modified by the bot.

The bot reads the existing `Students` worksheet and registers first-contact
LINE accounts in place. Keep its columns named `Student ID`, `Chinese Name`,
`Full Name`, `LINE Display Name`, `LINE User ID`, and `Active`. Set `Active` to
`TRUE` for eligible students. Existing LINE user IDs are the permanent identity
and are checked before display names. For a user ID not yet in the sheet, the
bot compares the LINE group member's display name exactly (case-insensitive,
with whitespace normalized) against active `LINE Display Name` values. It
stores the ID in that student's `LINE User ID` cell only when there is exactly
one match; unmatched and ambiguous names, or rows that already have a different
LINE user ID, require administrator review. The original attendance message is
processed immediately after successful registration.

The attendance date parser recognizes today/tomorrow phrases and explicit dates
such as `2026-10-07`. Leave categories are written with the configured Chinese
labels, and recognized categories receive the `Confirmed` status.

Set `GEMINI_API_KEY` to enable staged AI attendance classification. Common
greetings and reactions are ignored locally, and high-confidence Python
classifications do not call Gemini. Uncertain attendance intent is checked by
Gemini (`gemini-3.5-flash-lite`) using the Interactions API. Confirmed leave
messages proceed to category classification, where Python keywords are tried
first and Gemini is called only if Python cannot determine the category.
Messages about not taking or missing the bus are recorded as `不坐公交車`, not
as leave, and do not reduce the attending count. `IGNORE` messages are not
saved, `REVIEW` asks the sender to clarify, and confirmed leave or bus notices
proceed through the existing identity, date, and Google Sheets flow.

## LINE commands

Set `ADMIN_LINE_USER_IDS` to a comma-separated list of administrator LINE
Messaging API user IDs (the permanent `U...` IDs, not display names). Only those
accounts can use administrative commands.
Set `LINE_REPORT_GROUP_ID` to the LINE group ID where scheduled reports should
be pushed. The app schedules a daily report at 7:00 Asia/Taipei on dates
accepted by the work calendar; if no destination is configured, it logs that
the report was skipped.

All bot commands start with `/` to distinguish them from ordinary chat.
Students can use `/hello`, `/statusme [date]`, `/clear [date]`, and
`/ticket <message>`. A student can withdraw only their own leave dated today or
later. Each withdrawal is recorded in the `Audit Log` worksheet.

Administrators can use `/ping`, `/report [date]`, `/summary [date]`,
`/status <student> [date]`, `/set <student> <status> [date]`,
`/rm <student> [date]`,
`/range <student> <status> <start-date> <end-date>`, `/undo`, `/tickets`,
`/ticket show|close|reopen <ticket-id>`, and `/adminhelp`. Student IDs are
preferred; a quoted exact name is accepted only when it identifies one active
student. Dates accept `today`, `tomorrow`, or `YYYY-MM-DD`. Status aliases
include `sick`, `personal`, `leave`, `late`, and `pending`; the sheet stores
canonical Chinese labels. `/range` writes only dates selected by the current
work calendar. Tickets are stored in a `Tickets` worksheet, and administrative
attendance changes are recorded in `Audit Log` for `/undo`.

`/report`, `/summary`, and the scheduled report use the same roster format:
date and weekday, expected and attending counts, followed only by non-empty
attendance categories with each student's roster name. The attending count is
the expected roster size minus students marked absent; "不坐公交車" is listed
as a category but does not reduce attendance.
