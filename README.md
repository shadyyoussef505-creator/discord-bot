# Discord Bot Deployment Guide

This repository contains a Discord bot that uses Google Sheets for project, chapter, and profile management.

## الملفات في المشروع
- `bot.py` - الملف الرئيسي لتشغيل البوت.
- `config.py` - إعدادات ثوابت السيرفر وGoogle Sheet ID.
- `sheets.py` - دوال الربط مع Google Sheets وعمليات التسجيل.
- `ui_project.py` - واجهات ومودالات نظام المشاريع.
- `ui_chapter.py` - واجهات ومودالات نشر الفصول وإعلان الإنجاز.
- `ui_profile.py` - واجهات ومودالات البروفايل وتعديل البيانات.
- `requirements.txt` - مكتبات بايثون المطلوبة.
- `Procfile` - تعريف التشغيل على Railway.

> هذه الملفات يجب أن تكون جميعها في المجلد `discord bot/`.

## المتطلبات الأساسية
- Python 3.11 أو أحدث.
- حساب Google Cloud مع credentials لخدمة Google Sheets.
- تفعيل Google Sheets API على المشروع.
- حساب Discord bot مع توكن.

## إعداد المتغيرات البيئية
### 1. `DISCORD_TOKEN`
ضع توكن البوت في متغير بيئي باسم `DISCORD_TOKEN`.

### 2. `GOOGLE_CREDENTIALS`
ضع محتوى ملف JSON الخاص بخدمة حساب Google (Service Account) كله في متغير بيئي باسم `GOOGLE_CREDENTIALS`.

مثال:
```bash
export DISCORD_TOKEN="your-discord-token"
export GOOGLE_CREDENTIALS='{"type": "service_account", "project_id": ... }'
```

### 3. تحديث `config.py`
في `config.py` عدّل القيم التالية برقم السيرفر الحقيقي ورقم شيت Google:
- `EDITOR_ROLE_ID`
- `ADMIN_ROLE_ID`
- `TRANSLATOR_ROLE_ID` (إذا تحتاجه لاحقًا)
- `LEADER_ROLE_ID`
- `SHEET_ID`

## تثبيت المتطلبات
في المجلد `discord bot/` شغل:
```bash
pip install -r requirements.txt
```

## تشغيل البوت محليًا
في نفس المجلد شغل:
```bash
python bot.py
```

## محتوى `requirements.txt`
يحتوي على المكتبات التالية:
- `discord.py>=2.3.0`
- `gspread>=5.0.0`
- `oauth2client>=4.1.3`

## محتوى `Procfile`
```procfile
worker: python bot.py
```

## رفع المشروع إلى GitHub
### 1. إنشاء مستودع محلي
في المجلد `discord bot/` شغل:
```bash
git init
git add .
git commit -m "Initial commit"
```

### 2. ربط المستودع بـ GitHub
- أنشئ مستودع جديد على GitHub.
- انسخ رابط الـ HTTPS أو SSH.
- نفّذ الأمر:
```bash
git remote add origin <YOUR_GITHUB_REPO_URL>
git branch -M main
git push -u origin main
```

## نشر البوت على Railway
### 1. تسجيل الدخول إلى Railway
- افتح https://railway.app
- سجّل دخولك أو أنشئ حساب.

### 2. إنشاء مشروع جديد
- اضغط `New Project`.
- اختَر `Deploy from GitHub`.
- اربط حساب GitHub إذا طلب منك.
- اختر المستودع الذي أنشأته.

### 3. إعداد المتغيرات السرية
في إعدادات المشروع على Railway أضف:
- `DISCORD_TOKEN` = توكن البوت
- `GOOGLE_CREDENTIALS` = JSON كامل من ملف الخدمة

### 4. ضبط تشغيل Railway
- Railway سيكتشف `Procfile` ويشغل البوت كـ `worker`.
- إذا لم يحدث تلقائيًا، حدّد `worker: python bot.py` يدوياً.

### 5. نشر المشروع
- اضغط `Deploy` أو انتظر Railway ينشر تلقائيًا عند push.
- تأكد من أن العملية بدأت وأن البوت يعمل.

## ملاحظات مهمة
- لا ترفع ملف `bot token.txt` أو أي بيانات سرية إلى GitHub.
- `config.py` يمكن أن يكون حساسًا إذا كان يحتوي على IDs حقيقية.
- إذا واجهت خطأ في `GOOGLE_CREDENTIALS`, تأكد أن القيمة نص JSON صالح تمامًا.

---

## ملحوظة أخيرة
ضع هذا `README.md` في نفس المجلد `discord bot/` ليكون واضحًا مع بقية ملفات البوت.

## آخر التحديثات
- تم تحسين الكاش في `sheets.py`:
  - تنظيف الكاش بالكامل عند بدء التشغيل أو التحديث.
  - تطبيع أسماء المشاريع باستخدام `strip()` و`lower()` ومطابقة المسافات والرموز.
  - تحويل أسعار الشيت إلى `float` آمن حتى لو كانت مكتوبة بنقاط أو فواصل.
  - إضافة فالباك مباشر إلى Google Sheets إذا لم تُوجد الأسعار في الكاش.
- تم تأمين أوامر وواجهات المشروع:
  - حماية `ui_project.py` و`ui_chapter.py` من قيم `TL` و`ED` الفارغة أو `غير محدد`.
  - منع فشل التفاعل (`This interaction failed`) عبر تغليف ردود الأزرار والـ Views بـ `try/except`.
  - ضمان أن أزرار تعديل السعر والروابط (`Edit Pricing`, `Edit Folder`, `Edit Sort`, `Edit Raw`) تعمل حتى لو كانت بيانات الشيت ناقصة.
- سجل الأخطاء الآمن:
  - تم استخدام ردود آمنة `safe_component_reply` عند فشل التفاعل.
  - تم عزل فشل إرسال السجلات حتى لا يؤثر على عمل الإجراء الرئيسي.
