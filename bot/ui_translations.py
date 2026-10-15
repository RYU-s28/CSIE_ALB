"""Reviewed UI wording. Unknown/free-form text stays original; no API calls."""
import re

ZH_TW = {
    "Morning Bus": "上班交通", "Afternoon Bus": "下班交通", "Expected Bus Riders": "預計搭車人數",
    "Daily Expected": "當日應到人數", "Daily Attended": "當日實到人數",
    "Type a student name or ID in the typing area and send. Only attendees in the Monthly Report are included.": "輸入學生姓名或編號後送出。僅包含月報表中出席的學生。",
    "Preview Return Report": "預覽回校報告",
    "Send 下班點名 in the report group to post this report.": "在報告群組傳送「下班點名」以發布此報告。",
    "My Attendance": "我的出勤", "Salary Inquiry": "薪資查詢", "Change Language": "切換語言",
    "Portal Menu": "功能選單", "Admin Portal": "管理員選單", "Administrator workspace": "管理員工作區",
    "Attendance Status": "出勤狀態", "Time Out Report": "下班回校報告", "Help Center": "幫助中心",
    "Help Center · Tickets": "幫助中心・服務單", "Leave History": "請假紀錄", "Leave Request": "請假申請",
    "Terms & Usage": "條款與使用規範", "Start Using": "開始使用", "Welcome to CSIE Attendance Bot.": "歡迎使用 CSIE 出勤機器人。",
    "Name": "姓名", "ID no.": "編號",
    "Student Name": "學生姓名", "Student ID": "學生編號", "LINE Name": "LINE 名稱", "LINE User ID": "LINE 使用者 ID",
    "Full Name": "全名", "Chinese Name": "中文姓名", "Account Link": "帳號連結", "Status": "狀態", "Date": "日期",
    "Day": "日期類型", "Students": "學生人數", "Present / Paid Leave": "出席／有薪假", "Annual Leave · Paid": "特休・有薪",
    "Absences": "缺席", "Half Days": "半天", "Pending / Missing": "待確認／未登記", "Attended days": "出席天數",
    "Half-days": "半天天數", "Late arrivals": "遲到次數", "Remaining scheduled workdays": "剩餘排班天數",
    "Today's status": "今日狀態", "Attendance Rate (Month-to-Date)": "本月截至今日出勤率",
    "View Attendance History": "查看出勤紀錄", "View Daily Report": "查看每日報告", "Edit Leave": "編輯請假",
    "Edit Attendance": "編輯出勤", "Current Status": "目前狀態", "Choose Date": "選擇日期", "Find Another Student": "尋找其他學生",
    "Choose a Workday": "選擇工作日", "Choose Correction Date": "選擇更正日期", "Use Today": "使用今天",
    "Present": "出席", "Present / Remove Leave": "出席／移除請假", "Sick Leave": "病假", "Personal Leave": "事假",
    "Personal": "事假", "Menstrual Leave": "經痛假", "Menstrual": "經痛", "Annual Leave": "特休", "Annual · Paid": "特休・有薪",
    "Half Day": "半天", "Late": "遲到", "Absent": "不出來", "Pending": "待確認", "Pending Review": "待確認",
    "Clear": "清除", "Clear · Blank Record": "清除・空白紀錄", "Rest Day": "休息日", "Workday": "工作日",
    "Scheduled Workday": "排班工作日", "Missing Report Row": "報表缺少資料", "Upcoming": "尚未到來", "No Bus": "不坐公交車",
    "Abroad": "回菲律賓", "Cancelled Work": "取消工讀", "Confirmed": "已確認", "Recorded": "已登記",
    "Recognized": "已識別", "Connected": "已連結", "Guest": "訪客", "Unmatched": "未匹配", "Connected & Active": "已連結並啟用",
    "Verified & Connected": "已確認並連結", "Connected in Database": "已連結資料庫", "Account Not Linked": "帳號尚未連結",
    "Student Identity Recognized": "已識別學生身分", "Account Initialization & Terms": "帳號初始化與條款",
    "Name Not Matched": "姓名未匹配", "Duplicate Name": "姓名重複", "Account Conflict": "帳號衝突", "Profile Unavailable": "無法取得個人檔案",
    "Contact Admin / Support": "聯絡管理員／支援", "Attendance Updated": "出勤已更新", "Attendance Cleared": "出勤已清除",
    "Already Up to Date": "資料已是最新", "Attendance Record": "出勤紀錄", "Attendance logged": "出勤已登記",
    "Leave Recorded": "請假已登記", "Leave Needs Review": "請假待審核", "Leave category": "假別", "Student": "學生", "Record ID": "紀錄編號",
    "Request Correction": "申請更正", "Request a Correction": "申請更正", "Withdraw This Leave": "撤回這筆請假",
    "Withdraw this leave?": "要撤回這筆請假嗎？", "Confirm Withdrawal": "確認撤回", "Keep This Leave": "保留這筆請假",
    "Invalid Leave": "無效請假", "Before": "變更前", "After": "變更後", "Back": "返回", "Cancel": "取消",
    "Next": "下一頁", "Previous": "上一頁", "Back to Status": "返回出勤狀態", "Back to Ticket": "返回服務單",
    "Back to Help Center": "返回幫助中心", "Back to Overview": "返回總覽", "Edit This Student": "編輯此學生",
    "Search Students": "搜尋學生", "Search Results": "搜尋結果", "Find Student": "尋找學生", "Cancel Search": "取消搜尋",
    "Previous Matches": "上一頁結果", "More Matches": "更多結果", "🔎 Search name or student ID": "🔎 搜尋姓名或學生編號",
    "Search Attendees": "搜尋出席學生", "No-Bus Search": "搜尋不搭車學生", "Done · Back to Time Out": "完成・返回回校報告",
    "Choose Who Won't Take Bus": "選擇不搭公交車的人", "Send to Group": "發送至群組", "Save Current Morning Report": "儲存目前早上報告",
    "Morning Expected": "早上應到人數", "Morning Attended": "早上實到人數", "Expected School Return": "預計回校人數",
    "Expected Return": "預計回校人數", "Confirmed Returned": "已確認回校人數", "Return to School": "回到學校", "Enter Return Count": "輸入回校人數",
    "Correct Student Attendance": "更正學生出勤", "Resolve Ticket": "結案", "Reopen Ticket": "重新開啟服務單",
    "Confirm Resolve": "確認結案", "Confirm Reopen": "確認重新開啟", "Refresh Tickets": "重新整理服務單",
    "OPEN": "未結案", "CLOSED": "已結案", "Service Desk & Correction Tickets": "服務與更正申請", "Need assistance?": "需要協助嗎？",
    "Apply for Leave": "申請請假", "Work Schedule": "工作排班", "Attendance & Work Services": "出勤與工作服務",
    "Salary Overview": "薪資總覽", "Salary Breakdown": "薪資明細", "View Salary Breakdown": "查看薪資明細",
    "Estimated Take-Home Pay": "預估實領薪資", "Net Take-Home Pay": "實領薪資", "Gross earnings": "總收入",
    "Gross earnings (NT$196/h)": "總收入（每小時 NT$196）", "Estimated deductions": "預估扣款", "Total Deductions": "扣款合計",
    "Worked hours": "工時", "Labor Insurance": "勞保", "Health Insurance": "健保", "Income Tax (5%)": "所得稅（5%）",
    "Welfare Fund (0.5%)": "福利金（0.5%）", "Est.": "預估", "Verified": "已確認", "Setup Complete!": "設定完成！",
    "Language / 語言": "Language / 語言", "Language Settings": "語言設定", "Choose your language": "選擇語言",
    "Manage student requests and attendance privately in LINE.": "在 LINE 私訊中管理學生申請與出勤。",
    "Monthly Report is the source. Blank today remains pending; past blank workdays count as present.": "以月報表為準。今日空白為待確認，過去工作日空白視為出席。",
    "Tap a status to save immediately. Present records attendance. Clear removes the saved record and blanks the report cell. Annual leave is paid.": "點選狀態立即儲存。出席會登記出勤；清除會移除紀錄並清空報表儲存格。特休為有薪假。",
    "Attendance, Monthly Report, and the audit log are saved.": "已儲存出勤、月報表及稽核紀錄。",
    "Saved records were removed and the Monthly Report cell is blank.": "已移除儲存的紀錄，並清空月報表儲存格。",
    "This status is already saved. No duplicate change was made.": "此狀態已儲存，未重複變更。",
    "This date is not scheduled. Choose the attendance date to continue.": "此日期未排班。請選擇出勤日期後繼續。",
    "Review the Terms & Usage for details about this service and how your information is used.": "請閱讀條款與使用規範，了解本服務及您的資料如何被使用。",
    "Tap Search, enter a student ID or any part of their Chinese, English, or LINE name, then send.": "點選搜尋，輸入學生編號、中文姓名、英文姓名或 LINE 名稱的一部分後送出。",
    "Type a student name or ID in the typing area and send. Search is active for five minutes.": "在輸入區輸入學生姓名或編號後送出。搜尋有效時間為五分鐘。",
    "Type a student name or ID in the typing area and send. Only morning attendees are included.": "輸入學生姓名或編號後送出。僅包含早上出席的學生。",
    "Search for an attendee to mark or clear No Bus. Transport choices do not change attendance or salary.": "搜尋出席學生以設定或取消不搭車。交通選擇不影響出勤或薪資。",
    "No saved morning report exists for this date. Save the current report first; an earlier report that was never saved cannot be recovered.": "此日期尚無早上報告。請先儲存目前報告；未儲存的過往報告無法還原。",
    "Choose a category to fill your draft. Edit the date and reason, then send.": "選擇假別以填入草稿，修改日期和原因後送出。",
    "Leave can only be filed on scheduled workdays.": "僅能在排班工作日申請請假。",
    "Requests are flagged for administrator review. Submission does not automatically imply HR approval.": "申請將交由管理員審核，送出不代表人事已核准。",
    "No leave records found for this period.": "此期間沒有請假紀錄。",
    "Automatically classified. If anything is incorrect, request a correction from an administrator.": "已自動分類。若有錯誤，請向管理員申請更正。",
    "Your absence notice was recorded as Pending Review. Please contact an administrator to confirm the leave type.": "您的缺席通知已登記為待確認。請聯絡管理員確認假別。",
    "This action cannot be undone here.": "此處無法復原這項操作。",
    "Track your attendance, view estimated salary, check work schedules, and submit leave notices using the portal menu below.": "使用下方選單查看出勤、預估薪資、排班及提交請假通知。",
    "Submit a ticket for incorrect attendance, missing leave records, or salary questions. Admins will review and respond.": "若出勤有誤、缺少請假紀錄或有薪資問題，請提交服務單，由管理員審核回覆。",
    "Language set to English.": "語言已設定為英文。", "Please change your language in a private chat with the bot.": "請在與機器人的私訊中切換語言。",
    "I couldn't save your language setting. Please contact an administrator.": "無法儲存語言設定，請聯絡管理員。",
    "Report sent to the configured group chat.": "報告已發送至指定群組。",
    "Default schedule: Wednesday–Sunday (8 hrs/day). Synchronized with Google Sheets Work Calendar tab.": "預設排班：週三至週日（每日 8 小時），與 Google Sheets 工作日曆同步。",
    "⚠️ Submission Notice": "⚠️ 申請須知", "✏️ Attendance Correction": "✏️ 出勤更正", "❓ Help & Support": "❓ 幫助與支援",
    "💰 Salary Discrepancy": "💰 薪資差異", "📄 Missing Leave Record": "📄 缺少請假紀錄",
}
ZH_TW.update({
    "CSIE Attendance Assistant · Automated record": "CSIE 出勤助理・自動紀錄",
    "CSIE Attendance · Shu-Te 3": "CSIE 出勤・樹德 3",
    "Confirm Attendance Change": "確認出勤變更", "Confirm Change": "確認變更",
    "Direct ticket: send /ticket <message>": "直接提交服務單：輸入 /ticket <訊息>",
    "Leave YYYY-MM-DD <Type> Reason: <your reason>": "Leave YYYY-MM-DD <假別> Reason: <請假原因>",
    "Leave can only be filed on scheduled workdays.": "僅能在排班工作日請假。",
    "Send Edit followed by a name or student ID. Examples: Edit S06677; Edit 杜榮瑪 sick leave; Edit 10/14 S06677 clear.": "輸入 Edit 加姓名或學生編號。例如：Edit S06677；Edit 杜榮瑪 sick leave；Edit 10/14 S06677 clear。",
    "*Calculated figures are estimates based on logged hours. Overtime rate is 1.34x (NT$263/hr) and can be requested in Help Center.": "*數字依登記工時估算。加班費為 1.34 倍（每小時 NT$263），可在幫助中心申請。",
    "More than one active student record matches your LINE name.": "您的 LINE 名稱符合多筆啟用中的學生紀錄。",
    "Ask an administrator to correct the duplicate LINE Display Name entries, then message the bot again.": "請管理員更正重複的 LINE 名稱，再傳訊息給機器人。",
    "Duplicate Names": "姓名重複",
    "The matching student record is already linked to a different LINE account.": "符合的學生紀錄已連結至另一個 LINE 帳號。",
    "Ask an administrator to check the existing account link.": "請管理員檢查目前的帳號連結。",
    "We could not retrieve your LINE profile name.": "無法取得您的 LINE 個人檔案名稱。",
    "Try again in a private chat. If this continues, contact an administrator.": "請在私訊中重試。若仍有問題，請聯絡管理員。",
    "Your LINE profile name does not match an active student record.": "您的 LINE 名稱不符合任何啟用中的學生紀錄。",
    "Unknown": "未知", "Standard rest day": "例行休息日", "Scheduled workday (8 hrs)": "排班工作日（8 小時）",
    "Student Identity Recognized": "已識別學生身分", "CSIE Admin": "CSIE 管理員",
})
EN = {value: key for key, value in ZH_TW.items()}
EN.update({"病假": "Sick Leave", "事假": "Personal Leave", "經痛": "Menstrual Leave", "特休": "Annual Leave",
           "半天": "Half Day", "遲到": "Late", "待確認": "Pending Review", "出席": "Present", "不出來": "Absent",
           "不坐公交車": "No Bus", "考試": "Exam", "語言已設定為繁體中文。": "Language set to Traditional Chinese."})


def translate_ui(text, language):
    table = ZH_TW if language == "zh-TW" else EN
    if text in table:
        return table[text]
    # Translate independent UI components without rewriting arbitrary prose.
    for separator in ("\n", " · ", ": "):
        if separator in text:
            return separator.join(translate_ui(part, language) for part in text.split(separator))
    if language == "zh-TW":
        months = {name: number for number, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
        match = re.fullmatch(r"(" + "|".join(months) + r") (\d{4})", text)
        if match:
            return f"{match[2]}年{months[match[1]]}月"
        match = re.fullmatch(r"Page (\d+)", text)
        if match:
            return f"第 {match[1]} 頁"
        match = re.fullmatch(r"(\d+) student\(s\)", text)
        if match:
            return f"{match[1]} 位學生"
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) is a rest day\. Leave can only be filed on a scheduled workday\.", text)
        if match:
            return f"{match[1]} 是休息日。僅能在排班工作日申請請假。"
    return text
