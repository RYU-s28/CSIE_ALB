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
is updated by scheduled attendance jobs, which write `出席` for students
without a leave record on accepted workdays.

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
such as `2026-10-07`, `Oct 23`, `October 23rd, 2026`, `23 Oct`, and
`10月23日`. Yearless dates use the current Taipei year; invalid dates are
rejected. Advance notices such as "I already filed leave for tomorrow cannot
work" and "I will be absent on Oct 23" are saved for the specified date. Leave categories are written with the configured Chinese
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
The app sends scheduled daily reports privately to `ADMIN_LINE_USER_IDS` at
7:00 Asia/Taipei on accepted workdays. `LINE_REPORT_GROUP_ID` is no longer
used. If no administrator user IDs are configured, reporting is skipped.

All bot commands start with `/` to distinguish them from ordinary chat.
Students can use `/hello`, `/statusme [date]`, `/clear [date]`,
`/salary [YYYY-MM]`, and `/ticket <message>`. Salary inquiries read the
student's `出席` and `半天` entries from the selected `Monthly Report` month
(current month by default), estimate pay at NT$196 per hour (8 hours per full
day, 4 per half day), and show the configured deductions and take-home estimate.
Salary details are returned only in a private chat; selecting Salary from a
group card sends the estimate privately when LINE allows it. A student can
withdraw only their own leave dated today or later. Each withdrawal is recorded
in the `Audit Log` worksheet.

### CSIE Student Portal Rich Menu

The bot includes a 6-tile persistent Rich Menu configured in `bot/rich_menu.py` with asset `assets/rich_menu.png` (2500x946 px), matching the sage green portal design:
1. **My Attendance (出勤紀錄)**: Displays scheduled days, attended days, absences, half-days, late arrivals, today's status, and an attendance percentage progress bar (`/attendance`, `/statusme`).
2. **Leave History (請假紀錄)**: Lists past leave records with dates, categories, and approval status, with natural language query support (e.g. "Show me all my sick leaves in September", `/leaves [month] [category]`) and a button to request corrections.
3. **Salary Inquiry (薪資查詢)**: Shows take-home pay, gross earnings, itemized deductions, worked hours, and an itemized breakdown with overtime calculation (`/salary [YYYY-MM] [overtime_hours]`). Marked as estimates unless actual payroll data is imported.
4. **Work Schedule (工作日曆)**: Shows upcoming 7-day schedule with workday, rest day, and holiday badges, integrated with the Google Sheets `Work Calendar` tab and defaulting to Wednesday–Sunday workdays (`/schedule`, `/calendar`).
5. **Leave Request (請假申請)**: Guided menu for submitting sick, personal, menstrual, annual, and half-day leave notices with explicit notice that submission is flagged for admin review and does not automatically imply HR approval (`/leaverequest`).
6. **Help Center (服務中心)**: Service ticket system for attendance correction, missing records, salary inquiries, and general questions, displaying ticket statuses and administrator responses (`/ticket`, `/helpcenter`).

In a LINE chat, `/hello` and `/help` show the CSIE Student Portal card matching the same design with quick actions for all features. Administrators can run `/setuprichmenu` to recreate or refresh the default Rich Menu in LINE.

After a leave record is successfully written, the bot sends a Flex confirmation
card with the saved category, date, and stable attendance record ID. Existing
attendance sheets are extended with an `attendance_record_id` column, and
legacy rows receive generated IDs. The card's status and correction actions work
only for the linked student in a private chat. Correction requests are added to
the existing administrator ticket queue. Leave withdrawal requires a signed,
10-minute confirmation and deletes only the exact owned record after checking
that it is still present and withdrawable.

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

My Attendance reads only the student's Monthly Report row. Day columns define
the scheduled dates. Blank past cells count as present, matching the report's
leave-marking convention; a blank cell today remains pending. Late arrivals
count as attended, half-days count as 0.5, and future leave is excluded from
month-to-date totals. Missing report sections or student rows produce a retrieval
error instead of falling back to leave records.

## Language settings and first greeting

The bot's initial account card is English and its title is `CSIE Student`.
Students can open **Language / 語言** from the welcome or initialization card,
or send `/language` or `/settings` in a private chat. Choose **English** or
**繁體中文**. Preferences persist by LINE user ID in the `User Settings` sheet.
English is the default. AI translates visible private reply text and Flex cards
using `GEMINI_API_KEY`; IDs and button action data remain unchanged. Translations
are cached in memory. If translation fails, the original message is sent.
Scheduled administrator reports use each administrator’s selected language. The fixed LINE rich-menu image
is not translated.

The separate automatic friend greeting is configured in LINE Official Account
Manager, outside this repository. Replace its Chinese greeting with:

> Hi! Welcome to CSIE Student. View your attendance, check your work schedule,
> and submit leave notices here. Use the menu below to get started. You can
> change your language to English or Traditional Chinese in Language Settings.

Alternatively, disable that automatic greeting so the bot's English account
initialization card is the first message.

## Account authorization

On first contact, a unique active roster-name match automatically saves the
sender's LINE user ID in the Students sheet. The initialization card ends with
**Authorize**. Tapping it in a private chat rechecks the sender's
identity, connects the account if possible, and records the student ID, LINE user
ID, Taipei timestamp, and terms version in `Account Authorizations`. Repeated
taps preserve the original timestamp. Unmatched, duplicate-name, and conflicting
accounts remain unlinked and need roster correction. The button also retries
matching after a display name or roster correction. Existing `agree_terms`
buttons use the same saved authorization flow.

## Spam protection and editable leave drafts

Message, follow, and postback events share a per-LINE-user rolling limit of
1 accepted request per second and 20 per minute. Excess requests are silently
ignored before student lookup, AI classification, and writes. No extra slowdown
reply is sent. The limit uses LINE event timestamps so rapid messages remain
one burst even when webhook processing is delayed by slow Sheets calls. Webhook event IDs are remembered for five minutes to
prevent duplicate delivery processing. Limits are thread-safe and bounded in
memory per bot process; they reset on restart and are not shared across replicas.

Leave cannot be saved on a rest day, including administrator single-date edits.
The work calendar's normal Wednesday–Sunday schedule and explicit workday/day-off
overrides apply. Validation occurs before tracker updates and spreadsheet writes.

Leave category buttons open LINE's keyboard with an editable draft, defaulting
to today or the next workday. Replace `[your reason]` and optionally change the
date, then send. Selecting a category does not submit a request. Completed drafts
are parsed locally for all five categories, including annual and half-day leave.
The form's date/category syntax stays in English when display labels are translated.
Keyboard autofill requires LINE for iOS/Android 12.6.0 or later; the bot also sends
manual typing instructions for unsupported clients.

Identity fields on cards are preserved verbatim during AI translation, including
LINE names for unmatched accounts. Embedded names are masked before translation.
Roster matching ignores spaces around `/` (for example, `Name /nickname` matches
`Name/nickname`) while retaining all name characters and duplicate-name checks.

The initialization card is compact and has no language selector or portal quick
replies. Its footer contains **Terms & Usage** and a red **Authorize** button.
Terms & Usage opens the complete supplied policy from `assets/terms.md` in a
separate carousel of readable bubbles. Language settings remain available with
`/settings` after initialization. Saved authorizations reference policy version
`2026-10-12`; earlier generic consent records remain in the sheet.

## Private responses and ticket handling

All event responses stay private. Group and room events push response cards to
the sender's LINE user ID; private chats use their private reply token. Error
messages and confirmations follow the same routing. No public
acknowledgments or group fallback messages are sent. If a private push cannot be
delivered, the error is logged and nothing is posted publicly. Students should
add the bot as a friend and unblock it to receive private messages.

Plain-text responses use readable Flex cards; existing specialized cards retain
their layouts. Scheduled class reports are delivered only to configured
administrator LINE user IDs, never group IDs.

Ticket bodies are untrusted literal text, limited to 4,000 characters, and saved
with Google Sheets `RAW` input. They do not run through Python `eval`, `exec`,
or shell commands. Formula-like ticket text is stored literally as well.

## Paid annual leave (特休)

特休 counts as a full paid attendance day, never an absence. It retains its
Annual Leave status label and report category, while preserving attendance
percentage and the full eight-hour salary credit. Future-dated report entries
are excluded from salary totals until their date arrives, just as future annual
leave is excluded from month-to-date attendance.

## Admin Portal in LINE

Users in `ADMIN_LINE_USER_IDS` receive a separate per-user **CSIE Admin Portal**
rich menu. **Attendance Status** replaces Leave Request, and **Help Center** opens
the administrator ticket workspace. The default student rich menu stays separate.
Admin tools do not require the administrator to have a Students row. Type `/menu`
or `/start` to open the same clickable admin portal card on desktop or mobile.
Students can also use `/menu` for the six student actions without a rich menu.

Attendance Status shows daily totals directly from Monthly Report. View the daily
roster report, select a student, choose a date, choose a status, then confirm the
before/after preview. **Present / Remove Leave** restores a full attendance day;
**Annual Leave · Paid** keeps 特休 paid. Leave on rest days is blocked. Changes
update Attendance, Monthly Report, and the actor's audit log. Student lists and
daily reports are paginated. `/adminfind [YYYY-MM-DD] <name-or-ID>` searches the
roster in the selected date's editing workflow.

Help Center lists open tickets. Open a ticket to read the student's request,
choose **Correct Student Attendance**, and select the correction date and status.
Attendance changes are recorded in the ticket's Admin Note with the audit ID.
The ticket stays open until **Resolve Ticket → Confirm Resolve**. Resolved tickets
can be reopened from their card. Resolution/reopening sends the student a private
notification; recorded corrections appear in their normal attendance view.

Every admin postback checks the sender's configured admin ID. Mutations require
a signed ten-minute confirmation tied to that administrator and the current
record snapshot. Stale, tampered, cross-account, and expired confirmations are
rejected. A failed Monthly Report mirror is reported explicitly and does not
automatically resolve the ticket; correct it before resolving.

The generated admin menu asset is `assets/admin_rich_menu.png`; regenerate it on
macOS with `swift scripts/render_admin_menu.swift assets/admin_rich_menu.png`.
Deployment setup links the admin menu to configured admin user IDs. Admins must
be friends with the bot for LINE to display their per-user menu.

Daily attendance report text from `/report`, `/summary`, and scheduled reports
retains its original Chinese plain-text format (date, 應到人數, 實到人數, and
category lists). It bypasses card conversion and AI translation. Other portal
and ticket replies still use cards.
