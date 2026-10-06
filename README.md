# CSIE_ALB
Attendance Line Bot Automation for automatic attendance making for class internship

## Google Sheets

Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the service account credentials JSON and
`GOOGLE_SHEET_ID` to the spreadsheet ID. Share the spreadsheet with the service
account's email address, with edit access.

The bot writes only to the `Attendance` worksheet, with columns
`student_id`, `name`, `date`, `type`, `status`, and `raw_message`. It creates
this worksheet and its header row if they do not exist. The `Monthly Report`
worksheet is not modified by the bot and can use formulas based on `Attendance`.

The bot reads, but does not modify, a `Students` worksheet to map LINE accounts
to student records. Its first row should contain `student_id`, `name`,
`line_user_id`, and `active` columns. Add one row per student and set `active`
to `TRUE`; inactive students are not matched. If the LINE user ID is not in the
roster, the bot may fall back to an exact, unique match against the student's
LINE display name. Because display names are user-controlled and can be
duplicated, those entries are logged as `Pending` for review. An event without
a LINE user ID cannot use profile-name fallback.

The attendance date parser recognizes today/tomorrow phrases and explicit dates
such as `2026-10-07`. Leave categories are written with the configured Chinese
labels, and recognized categories receive the `Confirmed` status.
