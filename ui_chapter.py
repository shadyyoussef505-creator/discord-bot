import re
import discord
from datetime import datetime
from config import ADMIN_ROLE_ID, EDITOR_ROLE_ID, LOGS_CHANNEL_ID
from sheets import async_log_chapter_done, fix_url, get_project_team_discord_ids, get_project_card_location, async_save_claim, check_user_claim


def _is_undefined_member_value(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in {"غير محدد", "undefined", "none", "n/a", "-", "— not claimed —"}


def _format_mention(member_id):
    return f"<@{member_id}>" if member_id else None


class ChapterView(discord.ui.View):
    def __init__(self, embed: discord.Embed):
        super().__init__(timeout=None)
        self.embed = embed

    async def claim(self, interaction: discord.Interaction, field_name: str, role: str):
        # استخرج اسم المشروع ورقم الفصل من الـ embed
        description = self.embed.description or ""
        # الـ description شكله: "**project_name** • Chapter X"
        project_name = ""
        chapter_number = ""
        if "•" in description:
            parts = description.split("•")
            project_name = parts[0].replace("**", "").strip()
            chapter_part = parts[1].strip()
            chapter_number = re.sub(r"\D", "", chapter_part)

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

        # سجل الـ claim في شيت Claims
        if project_name and chapter_number:
            try:
                async_save_claim(project_name, chapter_number, interaction.user, role)
            except Exception:
                pass

        await interaction.response.send_message(f"✅ تم تسجيلك كـ {field_name} لهذا الفصل", ephemeral=True)

    @discord.ui.button(label="Claim TL", style=discord.ButtonStyle.primary, custom_id="chapter_claim_tl")
    async def claim_tl(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.claim(interaction, "Translator", "TL")
        except Exception:
            try:
                await interaction.response.send_message("❌ حدث خطأ أثناء محاولة المطالبة بـ TL. حاول مرة أخرى.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Claim ED", style=discord.ButtonStyle.success, custom_id="chapter_claim_ed")
    async def claim_ed(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.claim(interaction, "Editor", "ED")
        except Exception:
            try:
                await interaction.response.send_message("❌ حدث خطأ أثناء محاولة المطالبة بـ ED. حاول مرة أخرى.", ephemeral=True)
            except Exception:
                pass


class AddChapterModal(discord.ui.Modal):
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
        super().__init__(title="تفاصيل الفصل")
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

        tl_id, ed_id = None, None
        try:
            tl_id, ed_id = get_project_team_discord_ids(self.project_name)
        except Exception:
            tl_id, ed_id = None, None

        mentions = []
        if self.mention:
            mentions.append(self.mention.mention)
        tl_mention = _format_mention(tl_id)
        ed_mention = _format_mention(ed_id)
        if tl_mention:
            mentions.append(tl_mention)
        if ed_mention:
            mentions.append(ed_mention)

        mention_text = " ".join(mentions).strip()
        if mention_text:
            mention_text = f"{mention_text}\n"

        view = ChapterView(embed)
        await interaction.response.send_message(content=mention_text or None, embed=embed, view=view)

        try:
            await self.update_project_card_latest(interaction)
        except Exception:
            pass

    async def update_project_card_latest(self, interaction: discord.Interaction):
        channel_id, message_id = get_project_card_location(self.project_name)
        if not channel_id or not message_id:
            return

        channel = interaction.client.get_channel(int(channel_id))
        if channel is None:
            channel = await interaction.client.fetch_channel(int(channel_id))
        if channel is None:
            return

        card_message = await channel.fetch_message(int(message_id))
        card_embed = card_message.embeds[0]

        for i, field in enumerate(card_embed.fields):
            if field.name == "التفاصيل":
                old_value = field.value
                release_part = old_value.split("|")[-1].strip() if "|" in old_value else "Release: Not scheduled"
                new_value = f"Latest: Chapter {self.chapter_number} | {release_part}"
                card_embed.set_field_at(i, name="التفاصيل", value=new_value, inline=field.inline)
                break

        await card_message.edit(embed=card_embed)


class DoneModal(discord.ui.Modal):
    link_input = discord.ui.TextInput(
        label="الرابط (اختياري)", placeholder="https://drive.google.com/...", required=False
    )

    def __init__(self, role_type: str, project_name: str, chapter_number: str, auto_detected: bool = False):
        super().__init__(title="تفاصيل الإنجاز")
        self.role_type = role_type
        self.project_name = project_name
        self.chapter_number = chapter_number
        self.auto_detected = auto_detected

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        link_value = fix_url(self.link_input.value) if self.link_input.value else None
        link_display = link_value if link_value else "— No link provided —"

        # ✅ Validation — تحقق من شيت Claims
        has_claim = check_user_claim(self.project_name, self.chapter_number, interaction.user, self.role_type)
        if not has_claim:
            await interaction.followup.send(
                f"❌ مش لاقيك عملت claim للفصل **{self.chapter_number}** كـ **{self.role_type}** في مشروع **{self.project_name}**.\n"
                f"لازم تضغط **Claim {self.role_type}** الأول.",
                ephemeral=True
            )
            return

        try:
            amount = async_log_chapter_done(self.project_name, self.chapter_number, interaction.user, self.role_type)
        except Exception as e:
            await interaction.followup.send(f"❌ حصل خطأ أثناء التسجيل في الشيت: {e}")
            return

        if amount is None:
            await interaction.followup.send("❌ لم يتم العثور على السعر الصحيح للمشروع. تأكد من إعداد المشروع في الشيت.")
            return

        if self.auto_detected:
            await interaction.followup.send(
                f"✅ تم تسجيل الفصل {self.chapter_number} بنجاح في مشروع '{self.project_name}' (تم التعرف على المشروع تلقائياً من اسم القناة).",
                ephemeral=True
            )

        if self.role_type == "TL":
            editor_role = interaction.guild.get_role(EDITOR_ROLE_ID)
            mention_text = editor_role.mention if editor_role else "@Editors"
            embed = discord.Embed(
                title="✅ Translation Done!",
                description=f"**{self.project_name}** • Chapter {self.chapter_number}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="🎙️ Translator", value=interaction.user.mention, inline=True)
            embed.add_field(name="🔗 Link", value=link_display, inline=False)
            embed.add_field(name="💰 Amount", value=f"${amount:.2f}", inline=True)
            embed.add_field(name="المسجل بواسطة", value=f"{interaction.user.mention}", inline=False)
            embed.add_field(name="التاريخ والوقت", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)

            await interaction.followup.send(content=mention_text, embed=embed)
            try:
                await self.send_done_log(interaction, role_type="TL", amount=amount)
            except Exception:
                pass
        else:
            embed = discord.Embed(
                title="📢 Editing Done — Ready for Release!",
                description=f"**{self.project_name}** • Chapter {self.chapter_number}",
                color=discord.Color.purple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="✏️ Editor", value=interaction.user.mention, inline=True)
            embed.add_field(name="🔗 Final Link", value=link_display, inline=False)
            embed.add_field(name="💰 Amount", value=f"${amount:.2f}", inline=True)
            embed.add_field(name="المسجل بواسطة", value=f"{interaction.user.mention}", inline=False)
            embed.add_field(name="التاريخ والوقت", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)

            admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
            mention_text = admin_role.mention if admin_role else "@Admins"
            await interaction.followup.send(content=mention_text, embed=embed)
            try:
                await self.send_done_log(interaction, role_type="ED", amount=amount)
            except Exception:
                pass

    async def send_done_log(self, interaction: discord.Interaction, role_type: str, amount: float):
        try:
            if LOGS_CHANNEL_ID == 0 or not interaction.guild:
                return

            logs_channel = interaction.guild.get_channel(LOGS_CHANNEL_ID)
            if logs_channel is None:
                return

            embed = discord.Embed(
                title="📝 تم تسجيل إنجاز فصل",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="المشروع", value=self.project_name, inline=False)
            embed.add_field(name="رقم الفصل", value=self.chapter_number, inline=True)
            embed.add_field(name="الدور", value=role_type, inline=True)
            embed.add_field(name="المسجل بواسطة", value=f"{interaction.user.mention}", inline=False)
            embed.add_field(name="المبلغ", value=f"${amount:.2f}", inline=True)
            embed.add_field(name="التاريخ والوقت", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)

            await logs_channel.send(embed=embed)
        except Exception:
            pass
