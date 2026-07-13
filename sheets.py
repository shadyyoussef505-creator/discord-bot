import os
import json
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from config import SHEET_ID


def fix_url(url: str) -> str:
    if not url:
        return None
    if not url.startswith("http://") and not url.startswith("https://"):
        return None
    return url


def get_sheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    return gspread.authorize(creds)


def get_project_prices(project_name: str):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for row in records:
        if str(row["Project Name"]).strip() == project_name.strip():
            return float(row["TL Price"]), float(row["ED Price"])
    return 0.0, 0.0


def upsert_project_pricing(project_name: str, tl_price: float, ed_price: float):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["Project Name"]).strip() == project_name.strip():
            sheet.update(f"B{i+2}:C{i+2}", [[tl_price, ed_price]])
            return
    sheet.append_row([project_name, tl_price, ed_price])


def find_member_row(members_sheet, user_id: str):
    records = members_sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["Discord ID"]).strip() == user_id:
            return i + 2, row
    return None, None


def log_chapter_done(project_name: str, chapter_number: str, user, role: str):
    client = get_sheet_client()
    spreadsheet = client.open_by_key(SHEET_ID)
    tl_price, ed_price = get_project_prices(project_name)
    amount = tl_price if role == "TL" else ed_price

    spreadsheet.worksheet("Log").append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M"), project_name, chapter_number, str(user), role, amount
    ])

    members_sheet = spreadsheet.worksheet("Members")
    row_index, existing_row = find_member_row(members_sheet, str(user.id))

    if row_index:
        current_tl = int(existing_row.get("TL Chapters", 0) or 0)
        current_ed = int(existing_row.get("ED Chapters", 0) or 0)
        current_total_earned = float(existing_row.get("Total Earned", 0) or 0)
        current_paid_out = float(existing_row.get("Paid Out", 0) or 0)

        if role == "TL":
            current_tl += 1
        else:
            current_ed += 1
        current_total_earned += amount
        new_unpaid = current_total_earned - current_paid_out

        members_sheet.update(f"C{row_index}:E{row_index}", [[current_tl, current_ed, new_unpaid]])
        members_sheet.update(f"O{row_index}:P{row_index}", [[current_total_earned, current_paid_out]])
    else:
        new_tl = 1 if role == "TL" else 0
        new_ed = 1 if role == "ED" else 0
        members_sheet.append_row([
            str(user.id), str(user), new_tl, new_ed, amount,
            "", "", "", "", "", "", "", "", "", amount, 0
        ])
    return amount


def get_member_profile(user):
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    _, existing_row = find_member_row(members_sheet, str(user.id))
    return existing_row


def update_member_field(user, field_name: str, value: str):
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    row_index, existing_row = find_member_row(members_sheet, str(user.id))

    column_map = {
        "Payment": "F", "Email": "G", "Country": "H", "Age": "I", "Gender": "J",
        "Display Name": "K", "Staff Role": "L", "Join Date": "M", "Other Scans": "N",
    }
    col_letter = column_map[field_name]

    if row_index:
        members_sheet.update(f"{col_letter}{row_index}", [[value]])
    else:
        new_row = [str(user.id), str(user), 0, 0, 0, "", "", "", "", "", "", "", "", "", 0, 0]
        field_order = ["Discord ID", "Name", "TL Chapters", "ED Chapters", "Unpaid Balance",
                       "Payment", "Email", "Country", "Age", "Gender",
                       "Display Name", "Staff Role", "Join Date", "Other Scans", "Total Earned", "Paid Out"]
        new_row[field_order.index(field_name)] = value
        members_sheet.append_row(new_row)


def is_gender_locked(user) -> bool:
    data = get_member_profile(user)
    return bool(data and str(data.get("Gender", "")).strip())


def record_payment(user, amount: float):
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    row_index, existing_row = find_member_row(members_sheet, str(user.id))
    if not row_index:
        raise ValueError("العضو ده لسه معندوش أي رصيد مسجل في الشيت.")

    current_total_earned = float(existing_row.get("Total Earned", 0) or 0)
    current_paid_out = float(existing_row.get("Paid Out", 0) or 0)
    new_paid_out = current_paid_out + amount
    new_unpaid = current_total_earned - new_paid_out

    members_sheet.update(f"E{row_index}", [[new_unpaid]])
    members_sheet.update(f"P{row_index}", [[new_paid_out]])
    return new_unpaid


def add_pending(project_name: str, chapter_number: str, user, role: str):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Pending")
    sheet.append_row([str(user.id), project_name, chapter_number, role, datetime.now().strftime("%Y-%m-%d %H:%M")])


def remove_pending(user_id: str, project_name: str, chapter_number: str, role: str):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Pending")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if (str(row["Discord ID"]).strip() == user_id and str(row["Project"]).strip() == project_name.strip()
                and str(row["Chapter"]).strip() == str(chapter_number).strip() and str(row["Role"]).strip() == role):
            sheet.delete_rows(i + 2)
            return


def get_pending_for_user(user):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Pending")
    records = sheet.get_all_records()
    return [row for row in records if str(row["Discord ID"]).strip() == str(user.id)]


def get_series_for_user(user):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Log")
    records = sheet.get_all_records()
    projects = set()
    for row in records:
        if str(row["Person"]).strip() == str(user):
            projects.add(row["Project"])
    return sorted(projects)
