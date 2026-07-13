import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import gspread
import traceback
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

SHEET_ID = "1QG4besel9w7nFkwceD21SpwCpFRbXyQHB6GCRyCstDQ"

# ---------------- Role IDs (لازم تستبدلهم بالـ IDs الحقيقية بتاعت السيرفر عندك) ----------------
EDITOR_ROLE_ID = 123456789012345678
ADMIN_ROLE_ID = 123456789012345678


def is_admin(interaction: discord.Interaction) -> bool:
    """بترجع True لو العضو عنده رول الأدمن."""
    admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if admin_role is None:
        return False
    return admin_role in interaction.user.roles


def fix_url(url: str) -> str:
    if not url:
        return None
    if not url.startswith("http://") and not url.startswith("https://"):
        return None
    return url


# ---------------- ربط جوجل شيت ----------------

def get_sheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    return client


def get_project_prices(project_name: str):
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for row in records:
        if str(row["Project Name"]).strip() == project_name.strip():
            return float(row["TL Price"]), float(row["ED Price"])
    return 0.0, 0.0


def upsert_project_pricing(project_name: str, tl_price: float, ed_price: float):
    """
    بتضيف المشروع لو مش موجود في شيت Projects، أو بتحدث سعره لو موجود بالفعل.
    """
    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).worksheet("Projects")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["Project Name"]).strip() == project_name.strip():
            row_index = i + 2
            sheet.update(f"B{row_index}:C{row_index}", [[tl_price, ed_price]])
            return
    sheet.append_row([project_name, tl_price, ed_price])


def find_member_row(members_sheet, user_id: str):
    records = members_sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["Discord ID"]).strip() == user_id:
            return i + 2, row
    return None, None


def log_chapter_done(project_name: str, chapter_number: str, user: discord.User, role: str):
    client = get_sheet_client()
    spreadsheet = client.open_by_key(SHEET_ID)

    tl_price, ed_price = get_project_prices(project_name)
    amount = tl_price if role == "TL" else ed_price

    log_sheet = spreadsheet.worksheet("Log")
    log_sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        project_name,
        chapter_number,
        str(user),
        role,
        amount
    ])

    members_sheet = spreadsheet.worksheet("Members")
    user_id_str = str(user.id)
    row_index, existing_row = find_member_row(members_sheet, user_id_str)

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

        # C: TL Chapters | D: ED Chapters | E: Unpaid Balance | ... | O: Total Earned | P: Paid Out
        members_sheet.update(f"C{row_index}:E{row_index}", [[current_tl, current_ed, new_unpaid]])
        members_sheet.update(f"O{row_index}:P{row_index}", [[current_total_earned, current_paid_out]])
    else:
        new_tl = 1 if role == "TL" else 0
        new_ed = 1 if role == "ED" else 0
        # ترتيب الأعمدة الفعلي في الشيت:
        # A Discord ID | B Name | C TL Chapters | D ED Chapters | E Unpaid Balance | F Payment
        # G Email | H Country | I Age | J Gender | K Display Name | L Staff Role
        # M Join Date | N Other Scans | O Total Earned | P Paid Out
        members_sheet.append_row([
            user_id_str, str(user), new_tl, new_ed, amount,
            "", "", "", "", "",        # F..J: Payment, Email, Country, Age, Gender
            "", "", "", "",             # K..N: Display Name, Staff Role, Join Date, Other Scans
            amount, 0                   # O: Total Earned | P: Paid Out
        ])

    return amount


def get_member_profile(user: discord.User):
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    row_index, existing_row = find_member_row(members_sheet, str(user.id))
    if existing_row:
        return existing_row
    return None


# ---------------- دوال نظام البروفايل الجديد (Payment / Email / Country / Age / Gender) ----------------

def update_member_field(user: discord.User, field_name: str, value: str):
    """
    بتحدث حقل واحد بس (زي Payment أو Email) في صف العضو.
    لو العضو مش موجود في الشيت، بتضيفله صف جديد.

    ترتيب الأعمدة الفعلي في شيت Members:
    A: Discord ID | B: Name | C: TL Chapters | D: ED Chapters | E: Unpaid Balance
    F: Payment | G: Email | H: Country | I: Age | J: Gender
    K: Display Name | L: Staff Role | M: Join Date | N: Other Scans
    O: Total Earned | P: Paid Out
    """
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    user_id_str = str(user.id)
    row_index, existing_row = find_member_row(members_sheet, user_id_str)

    column_map = {
        "Payment": "F",
        "Email": "G",
        "Country": "H",
        "Age": "I",
        "Gender": "J",
        "Display Name": "K",
        "Staff Role": "L",
        "Join Date": "M",
        "Other Scans": "N",
    }
    col_letter = column_map[field_name]

    if row_index:
        members_sheet.update(f"{col_letter}{row_index}", [[value]])
    else:
        new_row = [user_id_str, str(user), 0, 0, 0, "", "", "", "", "", "", "", "", "", 0, 0]
        field_order = ["Discord ID", "Name", "TL Chapters", "ED Chapters",
                        "Unpaid Balance", "Payment", "Email", "Country", "Age", "Gender",
                        "Display Name", "Staff Role", "Join Date", "Other Scans",
                        "Total Earned", "Paid Out"]
        idx = field_order.index(field_name)
        new_row[idx] = value
        members_sheet.append_row(new_row)


def is_gender_locked(user: discord.User) -> bool:
    """بترجع True لو العضو حدد الـ Gender قبل كده (يعني مقفول)."""
    data = get_member_profile(user)
    if data and str(data.get("Gender", "")).strip():
        return True
    return False


def record_payment(user: discord.User, amount: float):
    """
    بتسجل مبلغ اتدفع للعضو: بتزود Paid Out وبتقلل Unpaid Balance تلقائيًا.
    """
    client = get_sheet_client()
    members_sheet = client.open_by_key(SHEET_ID).worksheet("Members")
    user_id_str = str(user.id)
    row_index, existing_row = find_member_row(members_sheet, user_id_str)

    if not row_index:
        raise ValueError("العضو ده لسه معندوش أي رصيد مسجل في الشيت.")

    current_total_earned = float(existing_row.get("Total Earned", 0) or 0)
    current_paid_out = float(existing_row.get("Paid Out", 0) or 0)

    new_paid_out = current_paid_out + amount
    new_unpaid = current_total_earned - new_paid_out

    members_sheet.update(f"E{row_index}", [[new_unpaid]])
    members_sheet.update(f"P{row_index}", [[new_paid_out]])

    return new_unpaid


class ProfileFieldModal(discord.ui.Modal):
    def __init__(self, field_name: str, label: str, placeholder: str = ""):
        super().__init__(title=f"تعديل {label}")
        self.field_name = field_name
        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder,
            required=True,
            max_length=100
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            update_member_field(interaction.user, self.field_name, self.value_input.value)
        except Exception as e:
            print(traceback.format_exc())
            await interaction.followup.send(f"❌ حصل خطأ أثناء الحفظ: {e}", ephemeral=True)
            return
        await interaction.followup.send(f"✅ تم تحديث {self.field_name} بنجاح", ephemeral=True)


class GenderSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        placeholder="اختار الـ Gender",
        options=[
            discord.SelectOption(label="Male", emoji="♂️"),
            discord.SelectOption(label="Female", emoji="♀️"),
        ]
    )
    async def select_gender(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        try:
            update_member_field(interaction.user, "Gender", select.values[0])
        except Exception as e:
            print(traceback.format_exc())
            await interaction.followup.send(f"❌ حصل خطأ أثناء الحفظ: {e}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ تم تسجيل الـ Gender: {select.values[0]}\n"
            f"🔒 الحقل ده اتقفل دلوقتي، لو عايز تغيره لازم تتواصل مع أدمن.",
            ephemeral=True
        )


class PaymentAmountModal(discord.ui.Modal, title="تسجيل دفعة"):
    amount_input = discord.ui.TextInput(label="المبلغ المدفوع ($)", placeholder="مثال: 5", required=True)

    def __init__(self, target_user: discord.User):
        super().__init__()
        self.target_user = target_user

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.amount_input.value)
        except ValueError:
            await interaction.response.send_message("❌ لازم تكتب رقم صحيح للمبلغ.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            new_unpaid = record_payment(self.target_user, amount)
        except Exception as e:
            print(traceback.format_exc())
            await interaction.followup.send(f"❌ حصل خطأ أثناء تسجيل الدفعة: {e}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ تم تسجيل دفعة ${amount:.2f} لـ {self.target_user.mention}\n"
            f"💰 الرصيد المتبقي عليه دلوقتي: ${new_unpaid:.2f}",
            ephemeral=True
        )


class AdminProfileView(discord.ui.View):
    """View مخصص لما الأدمن يشوف بروفايل عضو تاني — فيها زرار الدفع بس."""
    def __init__(self, target_user: discord.User):
        super().__init__(timeout=180)
        self.target_user = target_user

    @discord.ui.button(label="Pay", style=discord.ButtonStyle.success, emoji="💵")
    async def pay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ الزرار ده مخصص للأدمن بس.", ephemeral=True)
            return
        modal = PaymentAmountModal(self.target_user)
        await interaction.response.send_modal(modal)


class ProfileButtonsView(discord.ui.View):
    def __init__(self, profile_owner_id: int):
        super().__init__(timeout=None)
        self.profile_owner_id = profile_owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.profile_owner_id:
            await interaction.response.send_message(
                "❌ الزرار ده مخصص بس لصاحب البروفايل.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Payment", style=discord.ButtonStyle.primary, emoji="💳")
    async def edit_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ProfileFieldModal("Payment", "طريقة الدفع", "مثال: Vodafone Cash / InstaPay")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Email", style=discord.ButtonStyle.secondary, emoji="📧")
    async def edit_email(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ProfileFieldModal("Email", "الإيميل", "example@gmail.com")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Country", style=discord.ButtonStyle.secondary, emoji="🌍")
    async def edit_country(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ProfileFieldModal("Country", "الدولة", "مثال: Egypt")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Age", style=discord.ButtonStyle.secondary, emoji="🎂")
    async def edit_age(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ProfileFieldModal("Age", "السن", "مثال: 19")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Gender", style=discord.ButtonStyle.success, emoji="⚧")
    async def edit_gender(self, interaction: discord.Interaction, button: discord.ui.Button):
        if is_gender_locked(interaction.user):
            await interaction.response.send_message(
                "🔒 الحقل ده مقفول بالفعل، لازم تتواصل مع أدمن عشان يغيره.",
                ephemeral=True
            )
            return
        view = GenderSelectView()
        await interaction.response.send_message("اختار الـ Gender بتاعك:", view=view, ephemeral=True)


# ---------------- الجزء بتاع /project ----------------

class TextEditModal(discord.ui.Modal):
    def __init__(self, field_name: str, embed: discord.Embed, message: discord.Message, placeholder: str = ""):
        super().__init__(title=f"تعديل {field_name}")
        self.field_name = field_name
        self.embed = embed
        self.message = message
        self.value_input = discord.ui.TextInput(
            label=f"القيمة الجديدة لـ {field_name}",
            placeholder=placeholder,
            required=True
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_value = self.value_input.value
        for i, field in enumerate(self.embed.fields):
            if field.name == self.field_name:
                self.embed.set_field_at(i, name=self.field_name, value=new_value, inline=field.inline)
                break
        await self.message.edit(embed=self.embed)
        await interaction.response.send_message(f"تم تحديث {self.field_name} ✅", ephemeral=True)


class LinkEditModal(discord.ui.Modal):
    def __init__(self, link_name: str, project_view):
        super().__init__(title=f"تعديل رابط {link_name}")
        self.link_name = link_name
        self.project_view = project_view
        self.link_input = discord.ui.TextInput(
            label=f"الرابط الجديد لـ {link_name}",
            placeholder="https://drive.google.com/...",
            required=True
        )
        self.add_item(self.link_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_link = fix_url(self.link_input.value) or "https://drive.google.com"
        self.project_view.links[self.link_name] = new_link
        new_view = self.project_view.rebuild()
        await interaction.message.edit(view=new_view)
        await interaction.response.send_message(f"تم تحديث رابط {self.link_name} ✅", ephemeral=True)


class PricingEditModal(discord.ui.Modal, title="تعديل السعر"):
    tl_price_input = discord.ui.TextInput(label="سعر المترجم TL", placeholder="مثال: 0.5", required=True)
    ed_price_input = discord.ui.TextInput(label="سعر المحرر ED", placeholder="مثال: 0.5", required=True)

    def __init__(self, project_name: str, embed: discord.Embed, message: discord.Message):
        super().__init__()
        self.project_name = project_name
        self.embed = embed
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        try:
            tl_price = float(self.tl_price_input.value)
            ed_price = float(self.ed_price_input.value)
        except ValueError:
            await interaction.response.send_message("❌ لازم تكتب أرقام صحيحة للسعر (مثال: 0.5)", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            upsert_project_pricing(self.project_name, tl_price, ed_price)
        except Exception as e:
            print(traceback.format_exc())
            await interaction.followup.send(f"❌ حصل خطأ أثناء تحديث الشيت: {e}", ephemeral=True)
            return

        for i, field in enumerate(self.embed.fields):
            if field.name == "السعر":
                self.embed.set_field_at(
                    i, name="السعر",
                    value=f"TL: ${tl_price:.2f} | ED: ${ed_price:.2f} | PR: skipped",
                    inline=field.inline
                )
                break
        await self.message.edit(embed=self.embed)
        await interaction.followup.send("✅ تم تحديث السعر في البطاقة والشيت معًا", ephemeral=True)


class UserSelectView(discord.ui.View):
    def __init__(self, field_name: str, embed: discord.Embed, message: discord.Message):
        super().__init__(timeout=60)
        self.field_name = field_name
        self.embed = embed
        self.message = message

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="اختار العضو")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        chosen_user = select.values[0]
        for i, field in enumerate(self.embed.fields):
            if field.name == self.field_name:
                self.embed.set_field_at(i, name=self.field_name, value=chosen_user.mention, inline=field.inline)
                break
        await self.message.edit(embed=self.embed)
        await interaction.response.send_message(
            f"تم تحديث {self.field_name} إلى {chosen_user.mention} ✅", ephemeral=True
        )


class ProjectView(discord.ui.View):
    def __init__(self, embed: discord.Embed, links: dict):
        super().__init__(timeout=None)
        self.embed = embed
        self.links = links
        self._build_link_buttons()

    def _build_link_buttons(self):
        for item in list(self.children):
            if getattr(item, "row", None) == 2 and isinstance(item, discord.ui.Button) and item.url:
                self.remove_item(item)
        for name, url in self.links.items():
            self.add_item(discord.ui.Button(label=name, url=url, row=2))

    def rebuild(self):
        return ProjectView(self.embed, self.links)

    @discord.ui.button(label="Change TL", style=discord.ButtonStyle.primary, row=0)
    async def change_tl(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = UserSelectView("TL", self.embed, interaction.message)
        await interaction.response.send_message("اختار الـ TL الجديد:", view=view, ephemeral=True)

    @discord.ui.button(label="Change ED", style=discord.ButtonStyle.primary, row=0)
    async def change_ed(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = UserSelectView("ED", self.embed, interaction.message)
        await interaction.response.send_message("اختار الـ ED الجديد:", view=view, ephemeral=True)

    @discord.ui.button(label="Add PR", style=discord.ButtonStyle.success, row=0)
    async def add_pr(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = UserSelectView("PR", self.embed, interaction.message)
        await interaction.response.send_message("اختار الـ PR الجديد:", view=view, ephemeral=True)

    @discord.ui.button(label="Edit Pricing", style=discord.ButtonStyle.secondary, row=1)
    async def edit_pricing(self, interaction: discord.Interaction, button: discord.ui.Button):
        # اسم المشروع بناخده من عنوان الـ embed (📖 اسم المشروع)
        project_name = self.embed.title.replace("📖", "").strip()
        modal = PricingEditModal(project_name, self.embed, interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Status", style=discord.ButtonStyle.secondary, row=1)
    async def edit_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TextEditModal("الحالة", self.embed, interaction.message, placeholder="مثال: 🟢 Active")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Details", style=discord.ButtonStyle.secondary, row=1)
    async def edit_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TextEditModal("التفاصيل", self.embed, interaction.message, placeholder="Latest: ... | Release: ...")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✏️ Edit Folder", style=discord.ButtonStyle.gray, row=3)
    async def edit_folder(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LinkEditModal("Folder", self))

    @discord.ui.button(label="✏️ Edit Sort", style=discord.ButtonStyle.gray, row=3)
    async def edit_sort(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LinkEditModal("Sort", self))

    @discord.ui.button(label="✏️ Edit Raw", style=discord.ButtonStyle.gray, row=3)
    async def edit_raw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LinkEditModal("Raw", self))


# ---------------- الجزء بتاع /add_chapter ----------------

class ChapterView(discord.ui.View):
    def __init__(self, embed: discord.Embed):
        super().__init__(timeout=None)
        self.embed = embed

    async def claim(self, interaction: discord.Interaction, field_name: str):
        for i, field in enumerate(self.embed.fields):
            if field.name.endswith(field_name):
                current_value = field.value
                if current_value != "— Not claimed —":
                    await interaction.response.send_message(
                        f"⚠️ الفصل ده اتاخد بالفعل من {current_value}", ephemeral=True
                    )
                    return
                self.embed.set_field_at(i, name=field.name, value=interaction.user.mention, inline=field.inline)
                break
        await interaction.message.edit(embed=self.embed)
        await interaction.response.send_message(f"✅ تم تسجيلك كـ {field_name} لهذا الفصل", ephemeral=True)

    @discord.ui.button(label="Claim TL", style=discord.ButtonStyle.primary)
    async def claim_tl(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim(interaction, "Translator")

    @discord.ui.button(label="Claim ED", style=discord.ButtonStyle.success)
    async def claim_ed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim(interaction, "Editor")


class AddChapterModal(discord.ui.Modal, title="تفاصيل الفصل"):
    link_input = discord.ui.TextInput(
        label="الرابط (اختياري)", placeholder="https://drive.google.com/...", required=False
    )
    deadline_input = discord.ui.TextInput(
        label="الديدلاين (اختياري)", placeholder="مثال: 15 يوليو", required=False
    )
    status_input = discord.ui.TextInput(
        label="الحالة", placeholder="مثال: Waiting for claims", required=False
    )
    note_input = discord.ui.TextInput(
        label="ملاحظة (اختياري)", placeholder="أي ملاحظة إضافية", required=False, style=discord.TextStyle.paragraph
    )

    def __init__(self, project_name: str, chapter_number: str, mention: discord.Role = None):
        super().__init__()
        self.project_name = project_name
        self.chapter_number = chapter_number
        self.mention = mention

    async def on_submit(self, interaction: discord.Interaction):
        link_value = fix_url(self.link_input.value) if self.link_input.value else None
        link_display = link_value if link_value else "— Not set —"
        deadline_display = self.deadline_input.value if self.deadline_input.value else "— Not set —"
        status_display = self.status_input.value if self.status_input.value else "Waiting for claims"
        note_display = self.note_input.value if self.note_input.value else "—"

        embed = discord.Embed(
            title="🔔 New Chapter Released!",
            description=f"**{self.project_name}** • Chapter {self.chapter_number}",
            color=discord.Color.gold()
        )
        embed.add_field(name="🌐 Link", value=link_display, inline=True)
        embed.add_field(name="⏰ Deadline", value=deadline_display, inline=True)
        embed.add_field(name="⚡ Status", value=status_display, inline=True)
        embed.add_field(name="🎙️ Translator", value="— Not claimed —", inline=True)
        embed.add_field(name="✏️ Editor", value="— Not claimed —", inline=True)
        embed.add_field(name="📝 Note", value=note_display, inline=True)
        embed.set_footer(text=f"{self.project_name} • Chapter Panel")

        view = ChapterView(embed)
        await interaction.response.send_message(embed=embed, view=view)

        if self.mention:
            await interaction.channel.send(
                f"{self.mention.mention} 📢 Chapter {self.chapter_number} of **{self.project_name}** is here! Claim your slot above 👆"
            )


# ---------------- الجزء بتاع /done ----------------

class DoneModal(discord.ui.Modal, title="تفاصيل الإنجاز"):
    link_input = discord.ui.TextInput(
        label="الرابط (اختياري)", placeholder="https://drive.google.com/...", required=False
    )

    def __init__(self, role_type: str, project_name: str, chapter_number: str):
        super().__init__()
        self.role_type = role_type
        self.project_name = project_name
        self.chapter_number = chapter_number

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        link_value = fix_url(self.link_input.value) if self.link_input.value else None
        link_display = link_value if link_value else "— No link provided —"

        try:
            amount = log_chapter_done(self.project_name, self.chapter_number, interaction.user, self.role_type)
        except Exception as e:
            print(traceback.format_exc())
            await interaction.followup.send(f"❌ حصل خطأ أثناء التسجيل في الشيت: {e}")
            return

        if self.role_type == "TL":
            embed = discord.Embed(
                title="✅ Translation Done!",
                description=f"**{self.project_name}** • Chapter {self.chapter_number}",
                color=discord.Color.blue()
            )
            embed.add_field(name="🎙️ Translator", value=interaction.user.mention, inline=True)
            embed.add_field(name="🔗 Link", value=link_display, inline=False)
            embed.add_field(name="💰 Amount", value=f"${amount:.2f}", inline=True)
            embed.set_footer(text="Ready for editing")

            editor_role = interaction.guild.get_role(EDITOR_ROLE_ID)
            mention_text = editor_role.mention if editor_role else "@Editors"
            await interaction.followup.send(content=mention_text, embed=embed)

        else:
            embed = discord.Embed(
                title="📢 Editing Done — Ready for Release!",
                description=f"**{self.project_name}** • Chapter {self.chapter_number}",
                color=discord.Color.purple()
            )
            embed.add_field(name="✏️ Editor", value=interaction.user.mention, inline=True)
            embed.add_field(name="🔗 Final Link", value=link_display, inline=False)
            embed.add_field(name="💰 Amount", value=f"${amount:.2f}", inline=True)

            admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
            mention_text = admin_role.mention if admin_role else "@Admins"
            await interaction.followup.send(content=mention_text, embed=embed)


@bot.event
async def on_ready():
    print(f"البوت شغال باسم: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أمر")
    except Exception as e:
        print(traceback.format_exc())
        print(e)


@bot.tree.command(name="project", description="عرض بطاقة مشروع")
@app_commands.describe(
    name="اسم المشروع",
    tl_price="سعر الفصل للمترجم (مثال: 0.5)",
    ed_price="سعر الفصل للمحرر (مثال: 0.5)",
    drive_folder="رابط مجلد الدرايف",
    drive_sort="رابط الـ Sort",
    drive_raw="رابط الـ Raw"
)
async def project(interaction: discord.Interaction, name: str, tl_price: float, ed_price: float,
                   drive_folder: str, drive_sort: str, drive_raw: str):
    await interaction.response.defer()

    try:
        upsert_project_pricing(name, tl_price, ed_price)
    except Exception as e:
        print("========== خطأ في /project ==========")
        print(traceback.format_exc())
        print("=======================================")
        await interaction.followup.send(f"❌ حصل خطأ أثناء تسجيل المشروع في الشيت: {e}")
        return

    embed = discord.Embed(title=f"📖 {name}", color=discord.Color.green())
    embed.add_field(name="الحالة", value="🟢 Active", inline=False)
    embed.add_field(name="TL", value="غير محدد", inline=True)
    embed.add_field(name="ED", value="غير محدد", inline=True)
    embed.add_field(name="PR", value="skipped", inline=True)
    embed.add_field(name="السعر", value=f"TL: ${tl_price:.2f} | ED: ${ed_price:.2f} | PR: skipped", inline=False)
    embed.add_field(name="التفاصيل", value="Latest: No chapters yet | Release: Not scheduled", inline=False)

    links = {
        "Folder": fix_url(drive_folder) or "https://drive.google.com",
        "Sort": fix_url(drive_sort) or "https://drive.google.com",
        "Raw": fix_url(drive_raw) or "https://drive.google.com"
    }
    view = ProjectView(embed, links)
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="add_chapter", description="نشر فصل جديد")
@app_commands.describe(
    project_name="اسم المشروع",
    chapter_number="رقم الفصل",
    mention="الرتبة اللي هتتعمله منشن (اختياري)"
)
async def add_chapter(interaction: discord.Interaction, project_name: str, chapter_number: str, mention: discord.Role = None):
    modal = AddChapterModal(project_name, chapter_number, mention)
    await interaction.response.send_modal(modal)


@bot.tree.command(name="done", description="إعلان إنجاز الترجمة أو التعديل وتسجيله في الشيت")
@app_commands.describe(
    role_type="هل انت المترجم ولا المحرر؟",
    project_name="اسم المشروع (لازم يكون مطابق للاسم في شيت Projects)",
    chapter_number="رقم الفصل"
)
@app_commands.choices(role_type=[
    app_commands.Choice(name="TL - مترجم", value="TL"),
    app_commands.Choice(name="ED - محرر", value="ED"),
])
async def done(interaction: discord.Interaction, role_type: app_commands.Choice[str], project_name: str, chapter_number: str):
    modal = DoneModal(role_type.value, project_name, chapter_number)
    await interaction.response.send_modal(modal)


# ---------------- أمر /profile (النسخة الجديدة بالأزرار) ----------------

@bot.tree.command(name="profile", description="عرض بروفايلك أو بروفايل عضو تاني (أدمن بس)")
@app_commands.describe(member="عرض بروفايل عضو تاني (للأدمن بس، اختياري)")
async def profile(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer(ephemeral=True)

    # تحديد صاحب البروفايل اللي هيتعرض
    if member is not None:
        if not is_admin(interaction):
            await interaction.followup.send("❌ بس الأدمن يقدر يشوف بروفايل عضو تاني.", ephemeral=True)
            return
        target_user = member
        is_admin_view = True
    else:
        target_user = interaction.user
        is_admin_view = False

    data = get_member_profile(target_user)

    embed = discord.Embed(title=f"👤 {target_user.display_name}'s Profile", color=discord.Color.blurple())
    embed.set_thumbnail(url=target_user.display_avatar.url)

    if data:
        embed.add_field(name="💰 Unpaid Balance", value=f"${float(data.get('Unpaid Balance', 0) or 0):.2f}", inline=True)
        embed.add_field(name="📈 Total Earned", value=f"${float(data.get('Total Earned', 0) or 0):.2f}", inline=True)
        embed.add_field(name="✅ Paid Out", value=f"${float(data.get('Paid Out', 0) or 0):.2f}", inline=True)
        embed.add_field(name="✅ TL Chapters", value=str(data.get('TL Chapters', 0)), inline=True)
        embed.add_field(name="✅ ED Chapters", value=str(data.get('ED Chapters', 0)), inline=True)
        embed.add_field(name="💳 Payment", value=data.get("Payment") or "— Not set —", inline=True)
        embed.add_field(name="📧 Email", value=data.get("Email") or "— Not set —", inline=True)
        embed.add_field(name="🌍 Country", value=data.get("Country") or "— Not set —", inline=True)
        embed.add_field(name="🎂 Age", value=data.get("Age") or "— Not set —", inline=True)
        gender_value = data.get("Gender") or "— Not set —"
        if data.get("Gender"):
            gender_value += " 🔒"
        embed.add_field(name="⚧ Gender", value=gender_value, inline=True)
    else:
        embed.add_field(name="💰 Unpaid Balance", value="$0.00", inline=True)
        embed.add_field(name="📈 Total Earned", value="$0.00", inline=True)
        embed.add_field(name="✅ Paid Out", value="$0.00", inline=True)
        embed.add_field(name="✅ TL Chapters", value="0", inline=True)
        embed.add_field(name="✅ ED Chapters", value="0", inline=True)
        embed.add_field(name="💳 Payment", value="— Not set —", inline=True)
        embed.add_field(name="📧 Email", value="— Not set —", inline=True)
        embed.add_field(name="🌍 Country", value="— Not set —", inline=True)
        embed.add_field(name="🎂 Age", value="— Not set —", inline=True)
        embed.add_field(name="⚧ Gender", value="— Not set —", inline=True)

    if is_admin_view:
        view = AdminProfileView(target_user)
    else:
        view = ProfileButtonsView(target_user.id)

    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
