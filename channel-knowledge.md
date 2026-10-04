### POST 0 — 0:27

LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/10']

### POST 1 — 19:11
🔥 استفاده از Claude Code با مدل‌های مختلف AIبا پ

روژه متن‌باز Claude Code Router (CCR) می‌تونید Claude Code رو به مدل‌ها و سرویس‌های مختلف مثل Gemini، DeepSeek، OpenRouter، Kimi و حتی مدل‌های Local متصل کنید.⚠️ نکته

مهم:این روش
«Claude Sonnet/Opus رایگان» به شما نمی‌ده. در واقع رابط و قابلیت‌های Claude Code رو نگه می‌دارید، ولی پردازش درخواست‌ها می‌تونه توسط مدل دیگری انجام بشه. اگر Provider موردنظرتون Free Tier داشته باشه، می‌تونید تا سقف رایگان همون سرویس بدون هزینه ازش استفاده کنید.🔗 GitHu

b پروژه:https://gith

ub.com/musistudio/claude-code-router📚 Documenta

tion:https://ccrdesk.

top/━━━━━━━━━━━━━━1️


⃣ ساده‌ترین رو

ش نصبوارد GitHub بالا بشی

د و از قسمت Releases آخرین نسخه Claude Code Router رو دانلود کنید.برای:Windows → فایل .exe

macOS

→ فایل .dmgLinux → ف

ایل .AppImageبرنامه

رو نصب و اجرا کنید.━━━━

━━━━━━━━━━2️⃣ اضافه کردن م


دل AIداخل Clau

de Code Router وارد:Provi

ders → Add Providerبشید.اینجا

Provider موردنظرتون رو انتخ

اب کن

ید.مثلاً:• Gemini• OpenRouter• DeepSeek•

Kimi•

سرویس‌های
OpenAI-compati
ble• یا API
دلخواه خ
ودتونبعد API Key سرویس موردنظر
رو وارد کنید.CCR می‌تو

نه Protocol و مدل‌های قابل استفاده اون Prov

ider رو تشخیص بده.در پایان روی:Check Connectionبزنید.اگر Connection مو

فق بود، یعنی

مدل آماده استفاده اس

ت.━━━━

━━━━━━━━━━3️⃣ اگر هدفتون استفاده کم‌هزینه/رایگانهبای


د Providerای ا

نتخاب کنید که خودش Free Tier یا مدل رایگان

داشته باشه.مثلاً در صورت موجود بودن Free Tier می‌تونید API Key اون Provider

رو بگیرید و داخل CCR قرار بدید.نکته:CCR محدودیت‌های Provider رو دور نمی‌زنه.اگر Provider برای A

PI مح

دودیت روزانه، Rate Limit یا هزینه تعیین کرده

باشه، همون قوانین همچنان اعمال می‌شن.━━━━━━━━━━━━━━4️⃣ روشن کردن Routerحالا وارد:Serverبشید و روی:Startبز


نید.به‌صورت پی

ش‌فرض Gateway روی:http:/

/127.0.0.1

:3456اجرا

می‌شه.این G

ateway وا

سطه بی

ن Coding Agent و مدل AI شماس

ت.━━━━━━━━━━━━━━5️⃣ اتص

ال Claude C

odeحالا وارد:Agent Configبشید.از بین Agentها:Claud


e Codeرو انتخا

ب کنید.مدلی که قبلاً اضاف

ه کردید رو

انتخاب کنید و P

rofil

e رو Apply کنید

.از اینجا به بع

د ساختار تقریبا

ً این شکلیه:Claude Code↓Claude Code Router↓Provider انتخابی↓مدل AIیعن

ی می‌تونید محیط Claude Code رو داشته باشی

د، در حالی که م
د
ل پشت اون مثلاً Gemini

یا DeepSeek باشه.━━━
━
━━━━━━━━━━

6️⃣ تست کردنبعد از اجرای Claude Code یک درخواست ساده بدید، مثلاً:Explain this projectیا ازش بخواید ف


ایل‌های پروژه

رو بررسی کنه.بعد

داخل CCR وارد:Logsبشید.اونجا می‌تونید ببینید:• درخوا

ست به کدوم Provider رف

ته• کدوم Model استفاده شده• تعداد Tokenها•

مدت زمان پاسخ• Er

rorها• ت

خمین

هزینهاگر درخواست داخل

Logs نمایش داده شد، راه‌اندازی با
موفقیت انجام شده. ✅━━━━━━
━━━━━━━━🧑‍💻 روش
دوم: نصب با Term
inalاگر Des
ktop App نمی‌

خواید، نسخه CLI هم وجود داره.برای نسخه فعلی باید Node.js 22 یا بالاتر


نصب داشته باشی

د.برای چک کردن:node --versionبعد C

CR رو نصب کنید:npm install -g @musistudio/claude-

code-routerو اجرا کنید:ccr uiپنل مدیریت معمولاً در:http://127

.0.0.1:3458با

ز می‌شه.Gateway

مدل هم به‌صورت پیش‌ف

رض:http://127.0.0.1:3456خواهد بود.از اینجا مراح

ل همونن:Add

Provider

→ API Key → Model → S

erver → Agent Config →

Claude Cod

e━━━━━━━━━━━━━━🔥 مزیت اصلی Cla

ude Code Router چیه؟مجب

ور نیستید

فقط به یک مدل وابسته

باشید.مثلاً می‌تونید:کارهای ساده → مدل سریع و ارزانCoding → مدل قوی‌ترRe


asoning → مدل

متفاوتLong Context → مدل با Context بزرگ

‌ترحتی می‌شه Fallback تعریف کرد؛ یعنی اگ

ر مدل اول در دس

ترس نبود، درخواست به مدل بعدی

فرستاده بشه.━━━━━━━

━━━━━━━⚠️ چند نکته مهم

API Key خودتون رو هیچ‌وقت برای کسی ار

سال نکنید یا داخل GitHub قرار ندید.رایگان بودن CCR به معنی رایگان بودن تمام مدل‌ها نیست؛ خود CCR م


تن‌باز و رایگا

نه، ولی هزینه مدل ب

ه Provider انتخابی شما بستگی داره.همچنین چون این پروژه مرتب آپدیت می‌شه،

اگر ظاهر منوها یا روش نصب تغییر کرد، README و Documentation رسمی پروژه رو بررسی کنید.🔗 GitHub:https://github.com/musistudio/claude-c

ode-router📚 Documentation:https://ccrdesk.top/⭐ پروژه در GitHub متن‌بازه و تحت لایسنس MIT منتشر شده.
LINKS: ['http://127.0.0.1/', 'http://127.0.0.1:3456/', 'http://ub.com/musistudio/claude-code-router%F0%9F%93%9A', 'https://ccrdesk.top/%E2%AD%90', 'https://github.com/musistudio/claude-c', 'https://t.me/musistudio', 'https://t.me/shayanode', 'https://t.me/shayanode/11']

### POST 2 — 20:52

LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/12']

### POST 3 — 20:53
🎁 ۱۰ ورک‌فلو آماده n8n

داخل فایل ZIP، ده ورک‌فلو کاربردی مثل تولید محتوا با AI، جذب لید اینستاگرام، مانیتور قیمت کریپتو، بررسی سایت، بات تلگرام، خلاصه اخبار و انتشار خودکار در شبکه‌های اجتماعی قرار دارد.

روش استفاده:

فایل ZIP را دانلود و از حالت فشرده خارج کنید.وار
د n8n شوید و یک Workflow جدید بسازید.از منو
ی سه‌نقطه، گزینه Import from File را انتخاب کنید.فایل JSON مور
دنظر را وارد کنید.Credentialها و م
واردی مثل API Key، Chat ID و Spreadsheet ID را با اطلاعات خودتان جایگزین کنید.ابتدا Test Workflow
را بزنید و بعد از اطمینان، آن را Activate کنید.⚠️ خود فایل ZIP را مستقیماً وا

رد n8n نکنید؛ ابتدا باید Extract شود.
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/13']

### POST 4 — 20:55
۱۰ تا workflow آماده n8n که تو پست آخر قولشو داده بودم🔥
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/12', 'https://t.me/shayanode/14']

### POST 5 — 22:45

LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/15']

### POST 6 — 22:48
🎙 از صفر تا استفاده از Jev توی اولین AI Agent خودت!

توی این پادکست ۱۵ دقیقه‌ای یاد می‌گیری Jev چیه، چطور تصمیم می‌گیره و چجوری می‌تونی ازش توی پروژه‌های واقعی و AI Agentهای خودت استفاده کنی.

از مفاهیم اولیه تا کاربردهای عملی، همه‌چیز رو ساده و قابل‌فهم توضیح دادیم.👌

🎧 اگه می‌خوای اولین قدم رو برای ساخت یه AI Agent تصمیم‌گیرنده برداری، این پادکست برای توئه!
@shayanode 🔥
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/16']

### POST 7 — 1:29

LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/17']

### POST 8 — 00:09
🎙 از صفر تا استفاده از Jev توی اولین AI Agent خودت! توی این پادکست ۱۵ دقیقه‌ای یاد می‌گیری Jev چیه، چطور تصمیم می‌گیره و چجوری می‌تونی ازش توی پروژه‌های واقعی و AI Agentهای خودت استفاده کنی. از مفاهیم اولیه تا کاربردهای عملی، همه‌چیز رو ساده و قابل‌فهم توضیح…
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/16', 'https://t.me/shayanode/18']

### POST 9 — 06:46
این پرامپت برای اوناییه که قصد محاجرت تحصیلی یا اپلای رو دارن



@shayanode 🔥
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/19']

### POST 10 — 05:38
Jacobo AI Agent – GitHub

این سیستم دو سال برای یک تعمیرگاه موبایل استفاده شده و حدود ۹۰٪ پیام‌های مشتری‌ها را خودکار مدیریت کرده.(لذت ببرید🔥💯)

Channel: @shayanode 🔥
LINKS: ['https://github.com/santifer/jacobo-workflows', 'https://t.me/shayanode', 'https://t.me/shayanode/20']

### POST 11 — 07:19
ایجنت n8n مخصوص واتس اپ 📞
اگه برای اتصال واتس اپ با شماره ایران مشکل داشتین یا هر سوالی داشتین همینجا بپرسین🖐🏼❤️
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/21']

### POST 12 — 07:30
یه اکستنشن کروم ساختم که باعث میشه مصرف توکن تو هر کدوم از مدل های AI نصف بشه احتمالن تو Chrome Web Store بزارمش اما اینجا میزارم رایگان استفاده کنید از ۰ تا ۱۰۰ ساخشم ویدیو یوتوب گرفتم

اگه حمایت میشه 🔥بزارین که بفهمم🫶🏼
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/22']

### POST 13 — 23:00
Shayanode pinned «یه اکستنشن کروم ساختم که باعث میشه مصرف توکن تو هر کدوم از مدل های AI نصف بشه احتمالن تو Chrome Web Store بزارمش اما اینجا میزارم رایگان استفاده کنید از ۰ تا ۱۰۰ ساخشم ویدیو یوتوب گرفتم اگه حمایت میشه 🔥بزارین که بفهمم🫶🏼»
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/23']

### POST 14 — 03:07
دمتون گرم چنل ۱۰۰۰ نفرو رد کرد 🫶🏼 حالا نوبت منه براتون جبران کنم اکستنشن کروم و آموزش ساختش با chatgpt رو امشب براتون میزارم🔥
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/24']

### POST 15 — 06:39
اینم از سوپرایز امشب اکستنشنی که قولشو داده بودم🔥
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/25']

### POST 16 — 06:43
MD extention-Shayanode.rar
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/25', 'https://t.me/shayanode/26']

### POST 17 — 15:41
https://youtu.be/RMwQMgMTZxQ?si=kdTLKkp2rFg7aNif
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/33', 'https://youtu.be/RMwQMgMTZxQ', 'https://youtu.be/RMwQMgMTZxQ?si=kdTLKkp2rFg7aNif']

### POST 18 — 15:41
https://youtu.be/RMwQMgMTZxQ?si=kdTLKkp2rFg7aNif
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/33', 'https://t.me/shayanode/34']

### POST 19 — 15:42
Shayanode pinned «اینم اینک یوتوب ساخت صفر تا صد این اکستنشن با chatgpt🔥 یادتون نره که چنلو سابسکرایب کنید🫶🏼»
LINKS: ['https://t.me/shayanode', 'https://t.me/shayanode/35']
