import discord
from datetime import datetime
from config import LOGS_CHANNEL_ID
from sheets import get_member_profile, update_member_field, is_gender_locked, record_payment


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
            await interaction.followup.send(f"❌ حصل خطأ أثناء تسجيل الدفعة: {e}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ تم تسجيل دفعة ${amount:.2f} لـ {self.target_user.mention}\n"
            f"💰 الرصيد المتبقي عليه دلوقتي: ${new_unpaid:.2f}",
            ephemeral=True
        )

        try:
            await self.send_payment_log(interaction, amount)
        except Exception:
            pass

    async def send_payment_log(self, interaction: discord.Interaction, amount: float):
        try:
            if LOGS_CHANNEL_ID == 0 or not interaction.guild:
                return

            logs_channel = interaction.guild.get_channel(LOGS_CHANNEL_ID)
            if logs_channel is None:
                return

            embed = discord.Embed(
                title="📌 تم تسجيل دفعة مالية",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="العضو", value=f"{self.target_user.mention}", inline=False)
            embed.add_field(name="المبلغ", value=f"${amount:.2f}", inline=True)
            embed.add_field(name="المسجل بواسطة", value=f"{interaction.user.mention}", inline=True)
            embed.add_field(name="التاريخ والوقت", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)

            await logs_channel.send(embed=embed)
        except Exception:
            pass


class AdminProfileView(discord.ui.View):
    def __init__(self, target_user: discord.User):
        super().__init__(timeout=180)
        self.target_user = target_user

    @discord.ui.button(label="Pay", style=discord.ButtonStyle.success, emoji="💵")
    async def pay(self, interaction: discord.Interaction, button: discord.ui.Button):
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
