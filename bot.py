import discord
from discord.ext import commands
from discord import app_commands
import os
import traceback

from config import ADMIN_ROLE_ID, EDITOR_ROLE_ID
from sheets import fix_url, get_member_profile, log_chapter_done, upsert_project_pricing
from ui_project import ProjectView
from ui_chapter import AddChapterModal, DoneModal
from ui_profile import AdminProfileView, ProfileButtonsView

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


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
