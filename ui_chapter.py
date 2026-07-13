import discord
from config import ADMIN_ROLE_ID, EDITOR_ROLE_ID
from sheets import log_chapter_done, fix_url


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
