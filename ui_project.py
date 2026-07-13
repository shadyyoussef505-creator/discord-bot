import discord
from config import LOGS_CHANNEL_ID
from sheets import async_upsert_project_pricing, fix_url


async def safe_send_logs_channel(interaction: discord.Interaction, embed: discord.Embed):
    try:
        if LOGS_CHANNEL_ID == 0 or not interaction.guild:
            return

        logs_channel = interaction.guild.get_channel(LOGS_CHANNEL_ID)
        if logs_channel is None:
            return

        await logs_channel.send(embed=embed)
    except Exception:
        pass


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

        try:
            embed = discord.Embed(
                title="✏️ تم تعديل مشروع",
                description=f"{self.field_name} تم تحديثه في بطاقة المشروع.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="الحقل", value=self.field_name, inline=True)
            embed.add_field(name="القيمة الجديدة", value=new_value, inline=True)
            embed.add_field(name="المشروع", value=self.embed.title.replace("📖", "").strip(), inline=False)
            await safe_send_logs_channel(interaction, embed)
        except Exception:
            pass


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

        try:
            embed = discord.Embed(
                title="✏️ تم تعديل رابط مشروع",
                description=f"رابط {self.link_name} تم تحديثه.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="الرابط", value=new_link, inline=False)
            embed.add_field(name="المشروع", value=self.project_view.embed.title.replace("📖", "").strip(), inline=False)
            await safe_send_logs_channel(interaction, embed)
        except Exception:
            pass


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
             await async_upsert_project_pricing(self.project_name, tl_price, ed_price)
        except Exception as e:
            await interaction.followup.send(f"❌ حصل خطأ أثناء تحديث الشيت: {e}", ephemeral=True)
            return

        for i, field in enumerate(self.embed.fields):
            if field.name == "السعر":
                self.embed.set_field_at(
                    i,
                    name="السعر",
                    value=f"TL: ${tl_price:.2f} | ED: ${ed_price:.2f} | PR: skipped",
                    inline=field.inline
                )
                break

        await self.message.edit(embed=self.embed)

        try:
            embed = discord.Embed(
                title="✏️ تم تعديل أسعار المشروع",
                description=f"تم تحديث السعر في المشروع {self.project_name}.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="TL", value=f"${tl_price:.2f}", inline=True)
            embed.add_field(name="ED", value=f"${ed_price:.2f}", inline=True)
            await safe_send_logs_channel(interaction, embed)
        except Exception:
            pass

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

        try:
            embed = discord.Embed(
                title="✏️ تم تعديل الفريق في مشروع",
                description=f"{self.field_name} تم تحديثه إلى {chosen_user.mention}.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="الدور", value=self.field_name, inline=True)
            embed.add_field(name="العضو", value=chosen_user.mention, inline=True)
            embed.add_field(name="المشروع", value=self.embed.title.replace("📖", "").strip(), inline=False)
            await safe_send_logs_channel(interaction, embed)
        except Exception:
            pass


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
