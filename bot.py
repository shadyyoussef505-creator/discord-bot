import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import traceback
from datetime import datetime, time as dt_time

from config import ADMIN_ROLE_ID, EDITOR_ROLE_ID, CACHE_REFRESH_INTERVAL_SECONDS, AUTO_REMINDER_ENABLED, AUTO_REMINDER_TIME, REMINDER_CHANNEL_ID
from sheets import (
    fix_url,
    get_member_profile,
    async_log_chapter_done,
    async_upsert_project_pricing,
    find_project_by_channel_name,
    refresh_cache,
    get_overdue_claimed_chapters,
    get_reminder_channel_id,
)
from ui_project import ProjectView
from ui_chapter import AddChapterModal, DoneModal
from ui_profile import AdminProfileView, ProfileButtonsView

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(interaction: discord.Interaction) -> bool:
    admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if admin_role is None:
        return False
    return admin_role in interaction.user.roles


@bot.event
async def on_ready():
    print(f"البوت شغال باسم: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أمر")
    except Exception as e:
        print(traceback.format_exc())
        print(e)

    try:
        await bot.loop.run_in_executor(None, refresh_cache)
    except Exception:
        pass

    if not refresh_cache_task.is_running():
        refresh_cache_task.start()

    if AUTO_REMINDER_ENABLED and not daily_reminder_task.is_running():
        daily_reminder_task.start()


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
        await async_upsert_project_pricing(name, tl_price, ed_price)
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
    project_name="اسم المشروع (اختياري؛ يتم التعرف عليه تلقائياً من اسم القناة إذا تركته فارغًا)",
    chapter_number="رقم الفصل",
    mention="الرتبة اللي هتتعمله منشن (اختياري)"
)
async def add_chapter(interaction: discord.Interaction, chapter_number: str, project_name: str = None, mention: discord.Role = None):
    auto_detected = False
    if project_name is None or str(project_name).strip() == "":
        channel_name = getattr(interaction.channel, "name", "") or ""
        cleaned_channel_name = channel_name.replace("-", " ").replace("_", " ").strip().lower()
        project_name = find_project_by_channel_name(cleaned_channel_name)

        if project_name:
            auto_detected = True
        else:
            await interaction.response.send_message(
                "❌ لم أتمكن من تحديد المشروع من اسم القناة الحالية. الرجاء إعادة الأمر مع اسم المشروع يدوياً.",
                ephemeral=True
            )
            return

    modal = AddChapterModal(project_name, chapter_number, mention)
    await interaction.response.send_modal(modal)

    if auto_detected:
        await interaction.followup.send(
            f"✅ تم التعرف تلقائياً على المشروع '{project_name}' من اسم القناة.",
            ephemeral=True
        )


@bot.tree.command(name="done", description="إعلان إنجاز الترجمة أو التعديل وتسجيله في الشيت")
@app_commands.describe(
    role_type="هل انت المترجم ولا المحرر؟",
    project_name="اسم المشروع (اختياري؛ يتم التعرف عليه تلقائياً من اسم القناة إذا تركته فارغًا)",
    chapter_number="رقم الفصل"
)
@app_commands.choices(role_type=[
    app_commands.Choice(name="TL - مترجم", value="TL"),
    app_commands.Choice(name="ED - محرر", value="ED"),
])
async def done(interaction: discord.Interaction, role_type: app_commands.Choice[str], project_name: str = None, chapter_number: str = None):
    auto_detected = False
    if project_name is None or str(project_name).strip() == "":
        channel_name = getattr(interaction.channel, "name", "") or ""
        cleaned_channel_name = channel_name.replace("-", " ").replace("_", " ").strip().lower()
        project_name = find_project_by_channel_name(cleaned_channel_name)

        if project_name:
            auto_detected = True
        else:
            await interaction.response.send_message(
                "❌ لم أتمكن من تحديد المشروع من اسم القناة الحالية. الرجاء إعادة الأمر مع اسم المشروع يدوياً.",
                ephemeral=True
            )
            return

    modal = DoneModal(role_type.value, project_name, chapter_number, auto_detected=auto_detected)
    await interaction.response.send_modal(modal)


def _parse_reminder_time():
    try:
        return dt_time.fromisoformat(AUTO_REMINDER_TIME)
    except ValueError:
        return dt_time(hour=0, minute=0)


@tasks.loop(seconds=CACHE_REFRESH_INTERVAL_SECONDS)
async def refresh_cache_task():
    await bot.loop.run_in_executor(None, refresh_cache)


@tasks.loop(time=_parse_reminder_time())
async def daily_reminder_task():
    overdue_chapters = get_overdue_claimed_chapters()
    if not overdue_chapters:
        return

    grouped = {}
    for row in overdue_chapters:
        channel_id = row.get("reminder_channel_id") or REMINDER_CHANNEL_ID
        if not channel_id:
            continue
        grouped.setdefault(channel_id, []).append(row)

    for channel_id, rows in grouped.items():
        channel = bot.get_channel(channel_id)
        if channel is None:
            continue

        embed = discord.Embed(
            title="⏰ تذكيرات الفصول المتأخرة",
            description="الفصول التالية متأخرة عن التسليم:",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )

        for row in rows:
            name = row["project_name"]
            chap = row["chapter_number"]
            deadline = row["deadline"].strftime("%Y-%m-%d %H:%M")
            role_label = "Translator" if row["role"] == "TL" else "Editor"
            claimer = row["claimer"]
            embed.add_field(
                name=f"{name} — Chapter {chap}",
                value=f"{role_label}: {claimer}\nDeadline: {deadline}",
                inline=False
            )

        mention_lines = []
        for row in rows:
            claimer_id = row.get("claimer_id")
            if claimer_id:
                mention_lines.append(f"<@{claimer_id}>")
        mention_text = " ".join(dict.fromkeys(mention_lines))

        if mention_text:
            await channel.send(content=mention_text, embed=embed)
        else:
            await channel.send(embed=embed)


@bot.tree.command(name="profile", description="عرض بروفايلك أو بروفايل عضو تاني (أدمن بس)")
@app_commands.describe(member="عرض بروفايل عضو تاني (للأدمن بس، اختياري)")
async def profile(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer(ephemeral=True)

    if member is not None:
        if not is_admin(interaction):
            await interaction.followup.send("❌ بس الأدمن يقدر يشوف بروفايل عضو تاني.", ephemeral=True)
            return
        target_user = member
        is_admin_view = True
    else:
        target_user = interaction.user
        is_admin_view = False

    data = get_member_profile(target_user, refresh_member=True)

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