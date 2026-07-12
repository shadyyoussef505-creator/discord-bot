import discord
from discord.ext import commands
from discord import app_commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def fix_url(url: str) -> str:
    if not url:
        return None
    if not url.startswith("http://") and not url.startswith("https://"):
        return None
    return url


# ---------------- الجزء القديم بتاع /project ----------------

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
        modal = TextEditModal("السعر", self.embed, interaction.message, placeholder="مثال: TL: $0.50 | ED: $0.50")
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


@bot.event
async def on_ready():
    print(f"البوت شغال باسم: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أمر")
    except Exception as e:
        print(e)


@bot.tree.command(name="project", description="عرض بطاقة مشروع")
@app_commands.describe(
    name="اسم المشروع",
    drive_folder="رابط مجلد الدرايف",
    drive_sort="رابط الـ Sort",
    drive_raw="رابط الـ Raw"
)
async def project(interaction: discord.Interaction, name: str, drive_folder: str, drive_sort: str, drive_raw: str):
    embed = discord.Embed(title=f"📖 {name}", color=discord.Color.green())
    embed.add_field(name="الحالة", value="🟢 Active", inline=False)
    embed.add_field(name="TL", value="غير محدد", inline=True)
    embed.add_field(name="ED", value="غير محدد", inline=True)
    embed.add_field(name="PR", value="skipped", inline=True)
    embed.add_field(name="السعر", value="TL: $0.50 | ED: $0.50 | PR: skipped", inline=False)
    embed.add_field(name="التفاصيل", value="Latest: No chapters yet | Release: Not scheduled", inline=False)

    links = {
        "Folder": fix_url(drive_folder) or "https://drive.google.com",
        "Sort": fix_url(drive_sort) or "https://drive.google.com",
        "Raw": fix_url(drive_raw) or "https://drive.google.com"
    }
    view = ProjectView(embed, links)
    await interaction.response.send_message(embed=embed, view=view)


# ---------------- الجزء الجديد بتاع /add_chapter ----------------

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


@bot.tree.command(name="add_chapter", description="نشر فصل جديد")
@app_commands.describe(
    project_name="اسم المشروع",
    chapter_number="رقم الفصل",
    mention="الرتبة اللي هتتعمله منشن (اختياري)"
)
async def add_chapter(interaction: discord.Interaction, project_name: str, chapter_number: str, mention: discord.Role = None):
    modal = AddChapterModal(project_name, chapter_number, mention)
    await interaction.response.send_modal(modal)


TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
