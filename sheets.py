import asyncio
import os
import re
import json
import gspread
from datetime import datetime, date, time as dt_time
from oauth2client.service_account import ServiceAccountCredentials
from config import SHEET_ID

CACHE = {
    "projects": [],
    "project_map": {},
    "project_name_map": {},
    "members": {},
    "chapters": [],
    "pending": [],
}


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


def parse_float(value, default=0.0):
    try:
        if value is None:
            return default
        text = str(value).strip().replace(",", ".")
        return float(text)
    except (ValueError, TypeError):
        return default


def parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "yes", "1", "done", "finished", "completed"}


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, dt_time.min)

    text = str(value).strip()
    if not text:
        return None

    for fmt in [
        "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M",
        "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"
    ]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        try:
            if len(digits) == 8:
                return datetime.strptime(digits, "%Y%m%d")
            if len(digits) == 14:
                return datetime.strptime(digits, "%Y%m%d%H%M%S")
        except ValueError:
            pass

    return None


def normalize_project_name(name: str) -> str:
    if not name:
        return ""
    text = str(name).strip().lower()
    text = text.replace("\u00A0", " ")
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^\w\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_row_value(row, *keys):
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    lower_map = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    for key in keys:
        lower_key = str(key).strip().lower()
        if lower_key in lower_map:
            return lower_map[lower_key]
    return None


def _is_undefined_text(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in {"غير محدد", "undefined", "none", "n/a", "-", "— not claimed —"}


def normalize_discord_id(value):
    if _is_undefined_text(value):
        return None
    text = str(value).strip()
    mention_match = re.search(r"<@!?(\d+)>", text)
    if mention_match:
        return int(mention_match.group(1))
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _cache_projects(records):
    CACHE["projects"] = []
    CACHE["project_map"] = {}
    CACHE["project_name_map"] = {}
    for row in records:
        raw_name = get_row_value(row, "Project Name") or ""
        project_name = str(raw_name).strip()
        if not project_name:
            continue
        normalized_name = normalize_project_name(project_name)
        if not normalized_name:
            continue
        tl_price = parse_float(get_row_value(row, "TL Price", "TL") or 0.0, default=0.0)
        ed_price = parse_float(get_row_value(row, "ED Price", "ED") or 0.0, default=0.0)
        row["Project Name"] = project_name
        row["TL Price"] = tl_price
        row["ED Price"] = ed_price
        CACHE["projects"].append(row)
        CACHE["project_map"][normalized_name] = row
        CACHE["project_name_map"][project_name.lower().strip()] = row


def _cache_members(records):
    CACHE["members"] = {}
    for row in records:
        raw_id = row.get("Discord ID") or row.get("ID") or row.get("User")
        normalized_id = normalize_discord_id(raw_id)
        if normalized_id is not None:
            CACHE["members"][str(normalized_id)] = row


def _cache_chapters(records):
    CACHE["chapters"] = records


def _cache_pending(records):
    CACHE["pending"] = records


def refresh_cache():
    CACHE["projects"] = []
    CACHE["project_map"] = {}
    CACHE["project_name_map"] = {}
    CACHE["members"] = {}
    CACHE["chapters"] = []
    CACHE["pending"] = []

    client = get_sheet_client()
    spreadsheet = client.open_by_key(SHEET_ID)

    try:
        project_records = spreadsheet.worksheet("Projects").get_all_records()
        _cache_projects(project_records)
    except Exception:
        CACHE["projects"] = []
        CACHE["project_map"] = {}
        CACHE["project_name_map"] = {}

    try:
        member_records = spreadsheet.worksheet("Members").get_all_records()
        _cache_members(member_records)
    except Exception:
        CACHE["members"] = {}

    try:
        chapter_records = spreadsheet.worksheet("Chapters").get_all_records()
        _cache_chapters(chapter_records)
    except Exception:
        CACHE["chapters"] = []

    try:
        pending_records = spreadsheet.worksheet("Pending").get_all_records()
        _cache_pending(pending_records)
    except Exception:
        CACHE["pending"] = []


def refresh_cache_async():
    return asyncio.to_thread(refresh_cache)


def _ensure_cache_loaded():
    if not CACHE["projects"] or not CACHE["members"]:
        refresh_cache()


def find_project_by_channel_name(channel_name: str):
    _ensure_cache_loaded()
    normalized_channel = normalize_project_name(channel_name)
    if not normalized_channel:
        return None

    exact_match = CACHE["project_map"].get(normalized_channel)
    if exact_match:
        return str(exact_match.get("Project Name", "")).strip()

    contains_matches = [row for key, row in CACHE["project_map"].items() if normalized_channel in key]
    if len(contains_matches) == 1:
        return str(contains_matches[0].get("Project Name", "")).strip()

    return None


def get_all_project_names():
    """بترجع أسماء كل المشاريع الموجودة في شيت Projects (لاستخدام Autocomplete)."""
    _ensure_cache_loaded()
    return [str(row.get("Project Name", "")).strip() for row in CACHE["projects"] if row.get("Project Name")]


def get_next_chapter_number(project_name: str) -> int:
    """
    بترجع رقم الفصل التالي المتوقع لمشروع معين = آخر رقم اتسجل له في شيت Log + 1.
    لو المشروع لسه معندوش أي فصل مسجل، بترجع 1.
    """
    normalized_input = normalize_project_name(project_name)
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Log")
    records = sheet.get_all_records()

    max_chapter = 0
    for row in records:
        row_project_name = str(get_row_value(row, "Project Name", "Project") or "").strip()
        if normalize_project_name(row_project_name) != normalized_input:
            continue
        chapter_raw = get_row_value(row, "Chapter", "Chapter Number") or ""
        digits = re.sub(r"\D", "", str(chapter_raw))
        if digits:
            max_chapter = max(max_chapter, int(digits))

    return max_chapter + 1


def get_project_card_location(project_name: str):
    """بترجع (channel_id, message_id) بتاعت بطاقة /project المحفوظة، أو (None, None) لو مش موجودة."""
    _ensure_cache_loaded()
    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    if not project:
        return None, None
    channel_id = normalize_discord_id(project.get("Card Channel ID"))
    message_id = normalize_discord_id(project.get("Card Message ID"))
    return channel_id, message_id


def save_project_card_location(project_name: str, channel_id: int, message_id: int):
    normalized_input = normalize_project_name(project_name)
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        row_project_name = str(get_row_value(row, "Project Name") or "").strip()
        if normalize_project_name(row_project_name) == normalized_input:
            sheet.update(f"D{i+2}:E{i+2}", [[str(channel_id), str(message_id)]])
            return
    sheet.append_row([project_name.strip(), 0, 0, str(channel_id), str(message_id)])


def _cache_save_project_card_location(project_name: str, channel_id: int, message_id: int):
    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    if project:
        project["Card Channel ID"] = str(channel_id)
        project["Card Message ID"] = str(message_id)


def async_save_project_card_location(project_name: str, channel_id: int, message_id: int):
    _cache_save_project_card_location(project_name, channel_id, message_id)
    _spawn_background(save_project_card_location, project_name, channel_id, message_id)


def set_project_team_member(project_name: str, field_name: str, discord_id: int):
    """
    بتحفظ TL/ED المعين على مشروع في شيت Projects.
    field_name: 'TL' أو 'ED'
    """
    column_map = {"TL": "F", "ED": "G", "PR": "H"}
    col_letter = column_map.get(field_name)
    if not col_letter:
        return

    normalized_input = normalize_project_name(project_name)
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        row_project_name = str(get_row_value(row, "Project Name") or "").strip()
        if normalize_project_name(row_project_name) == normalized_input:
            sheet.update(f"{col_letter}{i+2}", [[str(discord_id)]])
            return
    new_row = [project_name.strip(), 0, 0, "", ""]
    new_row_map = {"TL": 5, "ED": 6, "PR": 7}
    while len(new_row) <= new_row_map[field_name]:
        new_row.append("")
    new_row[new_row_map[field_name]] = str(discord_id)
    sheet.append_row(new_row)


def _cache_set_project_team_member(project_name: str, field_name: str, discord_id: int):
    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    key_map = {"TL": "TL Discord ID", "ED": "ED Discord ID", "PR": "PR Discord ID"}
    if project:
        project[key_map[field_name]] = str(discord_id)


def async_set_project_team_member(project_name: str, field_name: str, discord_id: int):
    _cache_set_project_team_member(project_name, field_name, discord_id)
    _spawn_background(set_project_team_member, project_name, field_name, discord_id)


def get_project_prices(project_name: str):
    _ensure_cache_loaded()
    if not project_name:
        return 0.0, 0.0

    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    if project:
        return parse_float(project.get("TL Price")), parse_float(project.get("ED Price"))

    tl_price, ed_price = get_project_prices_from_sheet(project_name)
    if tl_price != 0.0 or ed_price != 0.0:
        _cache_update_project_pricing(project_name, tl_price, ed_price)
    return tl_price, ed_price


def get_project_prices_from_sheet(project_name: str):
    normalized_input = normalize_project_name(project_name)
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()

    for row in records:
        row_project_name = str(get_row_value(row, "Project Name") or "").strip()
        if normalize_project_name(row_project_name) == normalized_input:
            return parse_float(get_row_value(row, "TL Price", "TL") or 0), parse_float(get_row_value(row, "ED Price", "ED") or 0)

    for row in records:
        row_project_name = str(get_row_value(row, "Project Name") or "").strip()
        normalized_row_name = normalize_project_name(row_project_name)
        if normalized_input in normalized_row_name or normalized_row_name in normalized_input:
            return parse_float(get_row_value(row, "TL Price", "TL") or 0), parse_float(get_row_value(row, "ED Price", "ED") or 0)

    return 0.0, 0.0


def get_project_team_discord_ids(project_name: str):
    _ensure_cache_loaded()
    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    if not project:
        return None, None

    tl_id = (project.get("TL Discord ID") or project.get("TL ID") or project.get("TL")
             or project.get("Translator") or project.get("Translator ID"))
    ed_id = (project.get("ED Discord ID") or project.get("ED ID") or project.get("ED")
             or project.get("Editor") or project.get("Editor ID"))
    return normalize_discord_id(tl_id), normalize_discord_id(ed_id)


def get_reminder_channel_id(project_name: str):
    _ensure_cache_loaded()
    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    if not project:
        return None
    return normalize_discord_id(project.get("Reminder Channel ID") or project.get("Reminder Channel") or project.get("Project Channel ID") or project.get("Channel ID"))


def get_member_profile_from_sheet(user_obj):
    user_id = normalize_discord_id(getattr(user_obj, "id", user_obj))
    if user_id is None:
        return None

    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    records = sheet.get_all_records()

    for row in records:
        raw_id = row.get("Discord ID") or row.get("ID") or row.get("User")
        if normalize_discord_id(raw_id) == user_id:
            return row
    return None


def get_member_profile(user_obj, refresh_member: bool = False):
    _ensure_cache_loaded()
    user_id = normalize_discord_id(getattr(user_obj, "id", user_obj))
    if user_id is None:
        return None

    user_key = str(user_id)

    if refresh_member:
        row = get_member_profile_from_sheet(user_obj)
        if row is not None:
            CACHE["members"][user_key] = row
        return row

    member = CACHE["members"].get(user_key)
    if member is not None:
        return member

    row = get_member_profile_from_sheet(user_obj)
    if row is not None:
        CACHE["members"][user_key] = row
    return row


def get_overdue_claimed_chapters():
    _ensure_cache_loaded()
    now = datetime.now()
    overdue_rows = []

    for row in CACHE["chapters"]:
        project_name = str(row.get("Project", "")).strip()
        chapter_number = str(row.get("Chapter", "")).strip()
        deadline = parse_date(row.get("Deadline", ""))
        done = parse_bool(row.get("Done", ""))
        if not project_name or not chapter_number or not deadline or done:
            continue
        if deadline > now:
            continue

        translator = str(row.get("Translator", "")).strip()
        editor = str(row.get("Editor", "")).strip()
        reminder_channel_id = normalize_discord_id(row.get("Reminder Channel ID") or row.get("Reminder Channel") or row.get("Project Channel ID") or row.get("Channel ID"))

        if translator and translator != "— Not claimed —":
            overdue_rows.append({
                "project_name": project_name,
                "chapter_number": chapter_number,
                "role": "TL",
                "claimer": translator,
                "claimer_id": normalize_discord_id(row.get("Translator Discord ID") or translator),
                "deadline": deadline,
                "reminder_channel_id": reminder_channel_id,
            })

        if editor and editor != "— Not claimed —":
            overdue_rows.append({
                "project_name": project_name,
                "chapter_number": chapter_number,
                "role": "ED",
                "claimer": editor,
                "claimer_id": normalize_discord_id(row.get("Editor Discord ID") or editor),
                "deadline": deadline,
                "reminder_channel_id": reminder_channel_id,
            })

    return overdue_rows


def _spawn_background(fn, *args, **kwargs):
    async def _runner():
        try:
            await asyncio.to_thread(fn, *args, **kwargs)
        except Exception:
            pass

    asyncio.create_task(_runner())


def _cache_update_member_field(user, field_name: str, value: str):
    row = CACHE["members"].get(str(user.id))
    if row:
        row[field_name] = value
    else:
        new_row = {
            "Discord ID": str(user.id),
            "Name": str(user),
            "TL Chapters": 0,
            "ED Chapters": 0,
            "Unpaid Balance": 0,
            "Join Date": datetime.now().strftime("%Y-%m-%d"),
            field_name: value,
            "Total Earned": 0,
            "Paid Out": 0,
        }
        CACHE["members"][str(user.id)] = new_row


def _cache_update_project_pricing(project_name: str, tl_price: float, ed_price: float):
    normalized_name = normalize_project_name(project_name)
    project = CACHE["project_map"].get(normalized_name)
    if project:
        project["TL Price"] = tl_price
        project["ED Price"] = ed_price
    else:
        new_project = {
            "Project Name": project_name,
            "TL Price": tl_price,
            "ED Price": ed_price,
            "TL Discord ID": None,
            "ED Discord ID": None,
        }
        CACHE["projects"].append(new_project)
        CACHE["project_map"][normalized_name] = new_project


def _cache_log_chapter_done(project_name: str, chapter_number: str, user, role: str, amount: float):
    member_id = str(user.id)
    row = CACHE["members"].get(member_id)
    if not row:
        row = {
            "Discord ID": member_id,
            "Name": str(user),
            "TL Chapters": 0,
            "ED Chapters": 0,
            "Unpaid Balance": 0,
            "Total Earned": 0,
            "Paid Out": 0,
        }
        CACHE["members"][member_id] = row

    current_tl = int(row.get("TL Chapters", 0) or 0)
    current_ed = int(row.get("ED Chapters", 0) or 0)
    current_total_earned = parse_float(row.get("Total Earned", 0) or 0)
    current_paid_out = parse_float(row.get("Paid Out", 0) or 0)

    if role == "TL":
        current_tl += 1
    else:
        current_ed += 1

    current_total_earned += amount
    new_unpaid = current_total_earned - current_paid_out

    row["TL Chapters"] = current_tl
    row["ED Chapters"] = current_ed
    row["Total Earned"] = current_total_earned
    row["Unpaid Balance"] = new_unpaid


def _cache_record_payment(user, amount: float, new_unpaid: float, new_paid_out: float):
    row = CACHE["members"].get(str(user.id))
    if row:
        row["Unpaid Balance"] = new_unpaid
        row["Paid Out"] = new_paid_out


def async_update_member_field(user, field_name: str, value: str):
    _cache_update_member_field(user, field_name, value)
    _spawn_background(update_member_field, user, field_name, value)


async def async_upsert_project_pricing(project_name: str, tl_price: float, ed_price: float):
    _cache_update_project_pricing(project_name, tl_price, ed_price)
    _spawn_background(upsert_project_pricing, project_name, tl_price, ed_price)


def async_log_chapter_done(project_name: str, chapter_number: str, user, role: str):
    amount = parse_float(get_project_prices(project_name)[0] if role == "TL" else get_project_prices(project_name)[1])
    if role == "TL":
        amount = get_project_prices(project_name)[0]
    else:
        amount = get_project_prices(project_name)[1]

    _cache_log_chapter_done(project_name, chapter_number, user, role, amount)
    _spawn_background(log_chapter_done, project_name, chapter_number, user, role)
    return amount


def async_record_payment(user, amount: float):
    current_row = CACHE["members"].get(str(user.id))
    if not current_row:
        raise ValueError("العضو ده لسه معندوش أي رصيد مسجل في الشيت.")

    current_total_earned = parse_float(current_row.get("Total Earned", 0) or 0)
    current_paid_out = parse_float(current_row.get("Paid Out", 0) or 0)
    new_paid_out = current_paid_out + amount
    new_unpaid = current_total_earned - new_paid_out

    _cache_record_payment(user, amount, new_unpaid, new_paid_out)
    _spawn_background(record_payment, user, amount)
    return new_unpaid


def upsert_project_pricing(project_name: str, tl_price: float, ed_price: float):
    normalized_input = normalize_project_name(project_name)
    tl_price = parse_float(tl_price)
    ed_price = parse_float(ed_price)

    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        row_project_name = str(get_row_value(row, "Project Name") or "").strip()
        if normalize_project_name(row_project_name) == normalized_input:
            sheet.update(f"B{i+2}:C{i+2}", [[tl_price, ed_price]])
            return
    sheet.append_row([project_name.strip(), tl_price, ed_price])


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
        current_total_earned = parse_float(existing_row.get("Total Earned", 0) or 0)
        current_paid_out = parse_float(existing_row.get("Paid Out", 0) or 0)

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
        today = datetime.now().strftime("%Y-%m-%d")
        new_row = [str(user.id), str(user), 0, 0, 0, "", "", "", "", "", "", "", today, "", 0, 0]
        field_order = ["Discord ID", "Name", "TL Chapters", "ED Chapters", "Unpaid Balance",
                       "Payment", "Email", "Country", "Age", "Gender",
                       "Display Name", "Staff Role", "Join Date", "Other Scans", "Total Earned", "Paid Out"]
        new_row[field_order.index(field_name)] = value
        members_sheet.append_row(new_row)


def is_gender_locked(user) -> bool:
    data = get_member_profile(user)
    return bool(data and str(data.get("Gender", "")).strip())


def is_role_locked(user) -> bool:
    data = get_member_profile(user)
    return bool(data and str(data.get("Staff Role", "")).strip())


def ensure_join_date(user):
    """بتسجل تاريخ الانضمام أول مرة بس لو مش متسجل قبل كده."""
    data = get_member_profile(user)
    if data and not str(data.get("Join Date", "")).strip():
        today = datetime.now().strftime("%Y-%m-%d")
        async_update_member_field(user, "Join Date", today)


def record_payment(user, amount: float):
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    row_index, existing_row = find_member_row(members_sheet, str(user.id))
    if not row_index:
        raise ValueError("العضو ده لسه معندوش أي رصيد مسجل في الشيت.")

    current_total_earned = parse_float(existing_row.get("Total Earned", 0) or 0)
    current_paid_out = parse_float(existing_row.get("Paid Out", 0) or 0)
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


def save_claim(project_name: str, chapter_number: str, user, role: str):
    """بتسجل الـ claim في شيت Claims."""
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Claims")
    sheet.append_row([
        project_name,
        str(chapter_number),
        str(user.id),
        str(user),
        role,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ])


def async_save_claim(project_name: str, chapter_number: str, user, role: str):
    _spawn_background(save_claim, project_name, chapter_number, user, role)


def check_user_claim(project_name: str, chapter_number: str, user, role: str) -> bool:
    """
    بتتحقق إن العضو ده عنده claim في شيت Claims
    للمشروع والفصل والدور ده.
    """
    normalized_project = normalize_project_name(project_name)
    chapter_digits = re.sub(r"\D", "", str(chapter_number))
    user_id = str(user.id)

    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Claims")
    records = sheet.get_all_records()

    for row in records:
        row_project = normalize_project_name(str(row.get("Project", "")))
        row_chapter = re.sub(r"\D", "", str(row.get("Chapter", "")))
        row_discord_id = str(row.get("Discord ID", "")).strip()
        row_role = str(row.get("Role", "")).strip().upper()

        if (row_project == normalized_project and
                row_chapter == chapter_digits and
                row_discord_id == user_id and
                row_role == role.upper()):
            return True

    return False
