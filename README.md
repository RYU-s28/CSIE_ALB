# CSIE_ALB
Attendance Line Bot Automation for automatic attendance making for class internship

## Google Sheets

Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the service account credentials JSON and
`GOOGLE_SHEET_ID` to the spreadsheet ID. Share the spreadsheet with the service
account's email address, with edit access.

The bot writes attendance to the `Attendance` worksheet, with columns
`student_id`, `name`, `date`, `type`, `status`, and `raw_message`. It creates
this worksheet and its header row if they do not exist. For an existing workbook
with a populated `Logs` tab and an empty `Attendance` tab, it continues writing
to the `Logs` table at `B4:G` so existing log data remains connected. The
`Monthly Report` worksheet is not modified by the bot.

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
