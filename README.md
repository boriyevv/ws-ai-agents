# WS-Tizim: o'quv markazlar uchun AI jamoa

Web Street IT Academy uchun: bitta dastur, ikki xil kirish.

- **Telegram bot.** Siz, managerlar, administratorlar va o'qituvchilar matn yoki ovoz bilan buyruq berasiz. Ota-onalar
  xabar oladi, mijozlar va ishga nomzodlar ham shu bot orqali murojaat qiladi.
- **Panel.** Kompyuterda va telefonda brauzerda ochiladi. Telefonga ilova qilib o'rnatish ham mumkin.

**AI yordamchining ismi Jimi.** Unga odamga gapirgandek murojaat qilasiz: "Jimi, Ingliz 1 da Ali kelmadi",
"Jimi, Zufar bugun darsini 1 soat ertaroq boshlasin", "Jimi, ertaga 18:00 da kanalga ochiq eshiklar kuni haqida post
chiqar". Jimi oddiy ishlarni o'zi qiladi, chuqur ishni jamoadagi mutaxassis agentga beradi.

### AI jamoa (19 ta agent + HR katalogi)

| Yo'nalish | Agentlar |
|---|---|
| Rahbariyat | Jimi (bosh), HR (xodimlar va AI jamoa), Moliyachi (hisobchi), Haftalik hisobot |
| Media va marketing | Kontent strateg, Kopirayter (o'zbek/rus), Video, Dizayn, Nashr (publisher), Izoh va direkt, Reklama, Raqobatchilar monitoringi |
| O'quv jarayoni | Office manager, O'qituvchilar sifat nazorati, O'quvchini ushlab qolish, Fikr-mulohaza va sharh, Tavsiya (referral), O'qituvchi yollash, Jadval va xonalar |

**Yangi agent.** Markazda yangi ish paydo bo'lsa, HR agenti sizdan so'raydi. Keyin u katalogdan tayyor agentni olib keladi
(hozir katalogda Sotuv menejeri, Tadbirlar menejeri, Ota-onalar bilan aloqa bor) yoki yangisini yozadi.

- Siz tasdiqlamaguningizcha hech narsa ishga tushmaydi.
- Agentlar faqat tizimdagi vositalardan foydalanadi. Ular internetdan dastur o'rnatmaydi.
- HR har oyning 1-sanasida jamoani ko'rib chiqib taklif beradi.
- Panelda **AI jamoa** bo'limi bor.

### Asosiy imkoniyatlar

- **O'quv:** davomat va ota-onaga xabar, 30 kunlik to'lov tsikli va qarzdorlar, muzlatish, o'quvchi ketishi
  (sababi bilan), imtihon natijalari, Excelga eksport.
- **Vazifalar:** "Jimi, Zufarga ayt..." yoki panel orqali. Xodimga Telegramda «✅ Bajarildi» tugmasi bilan boradi.
  Bajarilsa sizga xabar keladi, muddati o'tsa eslatma boradi. Bir kishiga, rol bo'yicha yoki hammaga yuborish mumkin.
- **Kontent:**
  - Telegram kanal, Instagram (post va Reels), YouTube Shorts va TikTok (n8n/Make orqali).
  - Darhol yoki rejalashtirilgan vaqtda chiqadi.
  - Oylik reja bor; "Jimi yozib bersin" tugmasi bor; dizayn kartochkalari (natija, aksiya, yangi guruh, e'lon) yasaladi.
  - Video qirqiladi, 9:16 vertikal formatga keltiriladi, sarlavha va avtomatik o'zbekcha subtitr qo'shiladi.
- **Murojaatlar:**
  - Har Telegram postda «yozilish» havolasi bo'ladi. Bosgan odam bilan qabul agenti suhbatlashadi, ism va telefon
    so'raydi, lid yaratadi, adminga xabar beradi va qaysi post murojaat keltirgani saqlanadi.
  - Instagram forma lidlari n8n/Make webhook orqali keladi.
  - Instagram va Telegram kanal izohlariga AI javob tayyorlaydi, salbiy izohlar sizga boradi.
- **Reklama va raqobatchilar:** Meta Ads sarfi avtomatik tortiladi va bir murojaat narxi hisoblanadi. Raqobatchilarning
  ochiq Telegram kanallari kuzatiladi va haftalik xulosa beriladi.
- **O'qituvchi sifati:**
  - O'qituvchi botda `/dars` bilan «Boshladim/Tugatdim» bosadi.
  - Kuzatiladi: uy vazifasi, jurnalni o'z vaqtida to'ldirish, test natijalari va o'sishi.
  - Ota-onalardan 1-5 baho so'raladi. 5 baho berganlarga Google Maps sharh havolasi boradi.
  - Dars yozuvi **faqat o'qituvchi roziligi bilan** tahlil qilinadi.
- **Ushlab qolish:** davomati yoki bahosi pasaygan, to'lovi kechikkan o'quvchi haqida har kuni adminga signal boradi.
- **Referral va yollash:**
  - Do'stini olib kelganga bonus beriladi; do'sti to'laganda avtomatik tasdiqlanadi.
  - Vakansiya uchun bot orqali ariza havolasi yaratiladi. AI nomzodni 1-10 baholaydi, suhbat vaqti nomzodga yuboriladi.
- **Hisobotlar:**
  - Har kuni 08:00 da ertalabki hisobot.
  - Har dushanba haftalik hisobot: murojaatlar va konversiya, daromad, qarz, bo'sh joylar, davomat va ketish,
    marketing, o'qituvchilar, "e'tibor berish kerak bo'lgan 3 ta masala".
  - Har oyning 25-sanasida keyingi oy kontent rejasi.

> **Halol eslatma.**
> - **Sinovdan o'tgan:** hamma mantiq haqiqiy PostgreSQL bazada sinaldi (137 ta backend tekshiruvi). Panel brauzerda
>   kompyuter va telefon o'lchamida sinaldi. Video qirqish va subtitr ffmpeg bilan, dizayn kartochkalari Pillow bilan
>   haqiqatda yaratib ko'rildi.
> - **Sinovdan o'tmagan:** **jonli** Telegram, Supabase, Claude, Instagram, Meta Ads va ElevenLabs'ga ulanib sinab
>   ko'rilmagan, chunki kalitlar sizda. Xato chiqsa, terminaldagi matnni yuboring.
> - **Tizimdan tashqarida:** CapCut, Opus Clip, Submagic va Canva'ning ochiq API'si yo'q yoki cheklangan. Telegram Ads
>   va Instagram Direct ham shunday. Shuning uchun video qirqish va dizaynni tizim o'zi qiladi; Telegram Ads sarfi qo'lda
>   kiritiladi; Direct ulanmagan. AI video va rasm Higgsfield orqali (pastda "AI video va rasm").

---

## 1-qadam. Akkauntlar va kalitlar (o'zingiz qilasiz)

Hamma kalit **faqat sizda**, `.env` faylda turadi. Chatga, GitHub'ga yoki boshqa joyga yubormang.

**1.1 Telegram bot.** `@BotFather` → `/newbot` → nom bering (masalan **WS-Tizim**), username bering (masalan
`ws_tizim_bot`; band bo'lsa boshqasini tanlang) → **token** oling.
Keyin `@userinfobot` ga yozing: u sizning **Telegram ID** raqamingizni aytadi.

**1.2 Anthropic (Claude) kaliti.** `console.anthropic.com` → Billing'da kredit qo'shing va **oylik sarf limiti**
qo'ying (masalan 30 dollar) → API Keys → kalit yarating.

**1.3 Supabase (baza).**
1. `supabase.com` da yangi loyiha oching, **baza parolini** yozib qo'ying. Region: Yevropa (Frankfurt) yaqinroq.
2. Chap menyuda **SQL Editor** → **New query**. `sql/setup.sql` faylining **hamma** matnini yopishtiring →
   **Run**. "Success" chiqishi kerak. (Faqat bir marta ishga tushiriladi.)
   - Agar `setup.sql` ni **oldingi versiyadan** ishga tushirib qo'ygan bo'lsangiz: navbat bilan `sql/yangilash_1.sql`,
     keyin `sql/yangilash_2.sql`, keyin `sql/yangilash_3.sql` ni ishga tushiring (qayta ishga tushirsa ham zarari yo'q).
3. Tepada **Connect** tugmasi → **Session pooler** havolasini nusxalang, `[YOUR-PASSWORD]` o'rniga baza parolini
   yozing. Bu `DATABASE_URL` bo'ladi.

**1.4 Ovoz (ixtiyoriy).** O'zbekcha ovozli buyruq uchun `elevenlabs.io` dan API kalit (`ELEVENLABS_API_KEY`).
Jimining ovozli javobi bepul ishlaydi, kalit kerak emas.

## 2-qadam. Kompyuterga o'rnatish

1. `python.org` dan **Python 3.11+** o'rnating (Windows'da "Add Python to PATH" ni belgilang).
2. Loyiha papkasida terminal oching.

Windows (PowerShell):
```
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Mac / Linux:
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
3. `.env` ni oching va to'ldiring: `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `DATABASE_URL`,
   `OWNER_TELEGRAM_ID`, `OWNER_NAME`.

Panel uchun Node.js **shart emas**: panel tayyor holda `web/` papkada turadi.

## 3-qadam. Excel ma'lumotlarini yuklash (bir marta)

Format: har bir varaq = bitta guruh, ustunlar: `№ | Ism-familiya | To'lov | sana ustunlari (+ yoki -)`.
```
python -m scripts.import_excel fayl_nomi.xlsx
```
Skript har guruh uchun kunlar, vaqt, o'qituvchi va xonani so'raydi. "To'lov" ustunidagi summa **joriy oy
to'lovi** deb olinadi (oldingi oylar uchun qarz yozilmaydi). Ota-ona telefonlari Excelda yo'q, ularni keyin
botga yoki panelga kiritasiz.

## 4-qadam. Ishga tushirish

```
python main.py
```
Terminalda `WS-Tizim ishga tushdi (AI: Jimi): @botingiz` va `Panel: http://localhost:8080` chiqadi.

- **Telegram:** botingizga yozing: "Salom, nimalar qila olasan?", "Qarzdorlar kimlar?", yoki ovozli xabar.
- **Panel:** botga **`/panel`** deb yozing → bot bergan havolani shu kompyuterda bosing. Havola 15 daqiqa amal
  qiladi va bir marta ishlaydi; keyin brauzer sizni 30 kun eslab qoladi. Panelni "dastur" qilib o'rnatish
  uchun Chrome/Edge manzil satridagi **"O'rnatish"** (Install) belgisini bosing: u ish stolida alohida oyna
  bo'lib ochiladi.

Kompyuter o'chsa, bot ham, panel ham to'xtaydi. 24/7 uchun 6-qadamga qarang.

## 5-qadam. Jamoani ulash

Hammasini botga (yoki paneldagi Jimiga) **gapirib** qilasiz:
- "Jimi, Aziz ismli manager qo'sh, 1-filial." → bot kirish havolasini beradi, uni Azizga yuborasiz.
- "Jimi, Zufar bugun darsini 1 soat ertaroq boshlasin" → Zufarga Telegramda vazifa boradi, bajarganini bilasiz.
- "Jimi, Dilnoza administrator, 1-filial." → xuddi shunday.
- "Jimi, ingliz tili guruhi och: 1-filial, dushanba chorshanba juma, 14:00-16:00, Sardor ustoz." (bo'sh xonani topadi)
- "Jimi, Ali Valiyevni Ingliz 1 ga qo'sh, otasi Karim, +998901234567" → ota-ona havolasini beradi.
- Kundalik: "Jimi, Ingliz 1 da Ali kelmadi", "Jimi, Ali 300 ming to'ladi", "Jimi, Olimni muzlat, kasal".

Xodimlar ham `/panel` orqali panelga kira oladi va faqat o'z ruxsati doirasini ko'radi: admin moliya va
xodimlarni ko'rmaydi, o'qituvchi faqat o'z guruhlari davomati va natijalarini ko'radi.

**Ruxsatlar:** `role_permissions` jadvalida (Supabase → Table Editor). Har harakat uchun `allow`,
`needs_owner_approval` (sizga tugma bilan so'rov keladi) yoki `deny`. Jadvalda yo'q harakat = rad.

## 6-qadam. 24/7 ishlashi (hosting)

Railway.app (oyiga taxminan 5 dollar):
1. Loyihani GitHub'ga **`.env` siz** yuklang (`.gitignore` buni o'zi qiladi).
2. Railway → New Project → Deploy from GitHub.
3. **Variables** bo'limiga `.env` dagi hamma qiymatlarni kiriting.
4. Settings → Networking → **Generate Domain**. Hosil bo'lgan manzilni `PANEL_URL` ga yozing
   (masalan `https://ws-tizim-production.up.railway.app`). Panel shu manzilda internetdan ochiladi; kirish baribir
   faqat `/panel` havolasi orqali.

Bot faqat bitta joyda ishlashi kerak: Railway'da yoqsangiz, kompyuterdagisini o'chiring.

## Panelni o'zgartirish (React)

Panel `frontend/` papkada: **React 19 + Vite + TypeScript**, qo'shimcha kutubxonasiz.

```
cd frontend
npm install
npm run dev        # http://localhost:5173, API so'rovlari 8080 dagi Python serverga boradi
npm run build      # tayyor fayllar ../web ga yoziladi, Python ularni o'zi ko'rsatadi
```
`npm run dev` paytida `python main.py` ham ishlab turishi kerak. Avval odatdagidek `/panel` havolasi bilan
`localhost:8080` da kiring, keyin `localhost:5173` ni oching: kirish cookie'si ikkalasida ham ishlaydi.

Tuzilma:
- `src/App.tsx` — menyu va marshrutlar (har bo'lim faqat ruxsati borlarga ko'rinadi)
- `src/pages/*.tsx` — sahifalar; `src/ui.tsx` — umumiy komponentlar va `useLoad` / `useAction` hooklari
- `src/api.ts` — server bilan aloqa va turlar
- Server tomoni: `app/web.py` (FastAPI). Har bir endpoint `app/tools.py` dagi vositani chaqiradi, shuning uchun
  yangi endpoint qo'shganda ruxsat tekshiruvi avtomatik ishlaydi.

## Kontent va marketing ulanishlari (ixtiyoriy, bosqichma-bosqich)

Hammasi shart emas. Tavsiya: **avval faqat Telegram kanal**, ishonch hosil qilgach Instagram, keyin qolganlari.
Birinchi 1-2 oy har bir postni o'zingiz tasdiqlang: Jimi baribir har postdan oldin "ha" ni kutadi.

| Nima | Qanday ulanadi |
|---|---|
| **Telegram kanal** | Botni kanalga **admin** qiling, `.env`: `TELEGRAM_CHANNEL_ID=@kanal_nomi`. Rasm va video Supabase Storage'siz ham ishlaydi |
| **Fayl saqlash** (Instagram, YouTube va TikTok uchun) | Supabase → Storage → `media` nomli **public** bucket. `.env`: `SUPABASE_URL` (https://...supabase.co), `SUPABASE_SERVICE_KEY` = **secret** kalit (`sb_secret_...`, Project Settings → API Keys). Publishable kalit emas! |
| **Instagram** (post, Reels, izohlar) | Ikki usul: (1) **Instagram Login** — Facebook sahifasiz: developers.facebook.com → ilova → Instagram → "API setup with Instagram login" → akkauntni qo'shib token oling (`IG...` bilan boshlanadi), `.env`: `IG_ACCESS_TOKEN` (`IG_USER_ID` bo'sh qolsa ham bo'ladi). Token har hafta avtomatik uzaytiriladi. (2) **Facebook sahifa orqali**: sahifa tokeni (`EAA...`) va `IG_USER_ID` |
| **YouTube Shorts, TikTok** | n8n yoki Make'da "Webhook → YouTube/TikTok upload" ssenariysi. `.env`: `N8N_WEBHOOK_URL`. Tizim JSON yuboradi: `platform, text, media_url, media_kind, post_id` |
| **Instagram forma lidlari** | n8n/Make: "Facebook Lead Ads → HTTP POST" `https://<panel>/api/hooks/lead?key=<HOOK_SECRET>`, JSON: `full_name, phone, source, campaign`. Faqat 24/7 hostingda (6-qadam) ishlaydi |
| **Meta Ads sarfi** | `.env`: `META_AD_ACCOUNT_ID=act_...`, `META_ACCESS_TOKEN` (ads_read ruxsati). Dollar kursi panelda: Sozlamalar → `meta_usd_rate`. Har kuni 07:30 da tortiladi |
| **Telegram kanal izohlari** | Kanalga muhokama guruhini ulang, botni guruhga qo'shing (admin). `.env`: `TELEGRAM_DISCUSSION_ID=-100...` |
| **Raqobatchilar** | Jimiga ayting: "Jimi, raqobatchi qo'sh: X markaz, @ularning_kanali". Ochiq Telegram kanallari avtomatik kuzatiladi, Instagram bo'yicha kuzatuvni o'zingiz yozasiz |
| **Google sharh** | Panel → Sozlamalar → `review_url` (Google Maps "Sharh yozish" havolasi) |

**Postdan kelgan murojaatlarni kuzatish.** Har Telegram postga «👉 Yozilish» havolasi qo'shiladi. Uni bosgan odam bilan
botdagi **qabul agenti** gaplashadi:
1. ism va telefon so'raydi;
2. lid yaratadi va adminga xabar beradi;
3. savollariga guruhlar va eslatmalaringiz asosida javob beradi.

Qaysi post qancha murojaat keltirgani panelda (Kontent, Lidlar) ko'rinadi. Kontent strateg shunga qarab keyingi oy rejasini tuzadi.

**Markaz ohangi.** Bir marta o'rgatasiz: "Jimi, postlar samimiy bo'lsin, lekin «siz» deb yozinglar, emoji kam". Yoki
panelda: Sozlamalar → Markaz ohangi. Shundan keyin hamma agentlar shu uslubda yozadi.

## Video agenti (ffmpeg)

O'qituvchi telefonda 30 soniyalik dars lavhasini olib botga yuboradi va "Jimi, shu videoni Reels qil: 0:05 dan 0:35
gacha, sarlavha: IELTS darsidan lavha" deydi. Tizim:
1. kerakli qismni qirqadi;
2. 9:16 formatga keltiradi (kadr kesilmaydi, orqa fon xiralashadi);
3. sarlavha va avtomatik o'zbekcha subtitr qo'shadi (subtitr uchun `ELEVENLABS_API_KEY` kerak);
4. tayyor videoni sizga yuboradi; "kanalga chiqar" desangiz, chiqaradi.

ffmpeg o'rnatish:
- **Windows:** PowerShell'da `winget install ffmpeg`, keyin terminalni qayta oching.
- **Mac:** `brew install ffmpeg`.
- **Railway:** `nixpacks.toml` fayli ffmpeg'ni o'zi o'rnatadi.

Cheklovlar:
- Botga 20 MB gacha video yuboriladi (Telegram cheklovi); panelga 50 MB gacha.
- Bitta video 3 daqiqagacha bo'lishi kerak.

## AI video va rasm (Higgsfield)

**Asosiy xizmat — Higgsfield:**
- **Video:** Kling 3.0 Pro, 3-15 soniya, vertikal 9:16 (Reels, Shorts, TikTok).
- **Rasmni jonlantirish:** rasm yuborsangiz, u videoga aylanadi (MiniMax).
- **Rasm:** Seedream 2K, ustiga logo va sarlavha qo'yiladi.

Higgsfield ulanmagan bo'lsa, zaxira sifatida OpenAI ishlatiladi.

Ishlatish:
- "Jimi, dasturlash kursi uchun 10 soniyalik Reels video qil": Jimi professional prompt yozadi va "ha" so'raydi (pullik).
  Video fonda 2-6 daqiqa tayyorlanadi va botga keladi.
- O'quvchi rasmi yoki afisha yuborib: "shuni jonlantirib video qil".
- "Jimi, ochiq eshiklar kuni uchun afisha chiz": AI rasm, logo va sarlavha bilan.
- Keyin: "Jimi, shuni kanalga chiqar" yoki "Instagramga Reels qilib qo'y".

Ulash:
1. `cloud.higgsfield.ai` → hisobga kredit qo'shing → **API keys** → yangi kalit. Sizga **Key ID** va **Secret** beriladi.
2. `.env`:
   ```
   HIGGSFIELD_API_KEY=...key id...
   HIGGSFIELD_API_SECRET=...secret...
   ```
3. Tekshiring: `python -m scripts.tekshirish` → "Higgsfield ... kalit ishlayapti".

Boshqa model (masalan Seedance, Wan, Veo) kerak bo'lsa, Higgsfield saytidagi model nomini `.env` dagi
`HIGGSFIELD_T2V_MODEL` (matndan video), `HIGGSFIELD_I2V_MODEL` (rasmdan video) yoki `HIGGSFIELD_IMAGE_MODEL` ga yozing.
Narxlar Higgsfield saytida.

## O'qituvchilar: dars, uy vazifasi, sifat

- **Dars eslatmasi:** dars boshlanishidan ~15 daqiqa oldin o'qituvchiga «▶️ Darsni boshladim» tugmasi keladi, keyin
  «⏹ Tugatdim». Istalgan vaqtda `/dars` buyrug'i bilan ham ochiladi.
- **Davomat va uy vazifasi:** o'qituvchi Jimiga yozadi, masalan: "Jimi, Ingliz 1: Ali kelmadi. Uy vazifasi: 5-mashq".
- **Dars yozuvi tahlili:** avval o'qituvchiga ochiq ayting. U o'zi "Jimi, dars yozuvi tahliliga roziman" deb yozadi.
  Shundan keyingina audio tahlil qilinadi. Roziliksiz tizim tahlilni rad etadi.
- **Natijadan foydalanish:** Sifat nazorati bo'limidagi ko'rsatkichlar yordam va rivojlanish uchun; qaror sizda.

## Ovoz haqida

O'zbekcha ovoz ElevenLabs Scribe orqali matnga aylanadi (aniqligi haqidagi raqamlar ularning o'z o'lchovi).
**O'z ovozingiz bilan sinab ko'ring**, ayniqsa ism va summalarda. Shuning uchun bot "Eshitdim: ..." deb
ko'rsatadi va pul/xabar amallarini tasdiqsiz bajarmaydi. Panelda 🎤 tugmasi ham shu xizmatdan foydalanadi.

## Xarajat (taxminiy)

Rahbar va managerlar Claude Sonnet 5.5, administrator va o'qituvchilar arzon Claude Haiku 5.5 dan foydalanadi.
Aniq raqamni birinchi hafta `console.anthropic.com` → Usage bo'limida ko'ring va limit qo'ying.

## Yangi agent qo'shish

- **Eng oson:** "Jimi, HRga ayt: bizga sotuv bo'yicha agent kerak". HR katalogdan olib keladi yoki yangisini yozadi.
  Siz "ha" degandan keyin ishga tushadi.
- **Panel orqali:** AI jamoa → Katalog → «Qo'shish». Keraksiz agent → «To'xtatish» (katalogga qaytadi).
- **Qo'lda:** `agents/` papkasiga `.md` fayl qo'shing (`name`, `title`, `desc`, `tools` va yo'riqnoma), bot qayta
  ishga tushganda ko'rinadi.
- **Yangi vosita** (masalan yangi tashqi xizmat API'si) kerak bo'lsa, `plugins/` ga fayl qo'shiladi. Bu dasturchi
  ishi: agentlar o'zi kod yozib o'rnatmaydi.

## Xavfsizlik

- `.env` ni hech kimga ko'rsatmang. Token chiqib ketsa: `@BotFather` → `/revoke`; Anthropic kalitini console'da
  o'chirib yangisini oling.
- Panel havolasini hech kimga yubormang (u sizning nomingizdan kirish beradi). Kompyuterda panel faqat shu
  kompyuterdan ochiladi.
- Hamma o'zgarish `audit_log` jadvalida (kim, qachon, nima). Supabase'da zaxira nusxani va 2 bosqichli himoyani
  yoqing: bu bolalar va ota-onalar ma'lumoti.

## Muammolar

| Xato | Yechim |
|---|---|
| Nima ishlamayotganini bilish | `python -m scripts.tekshirish` — baza, Telegram, Claude, ovoz, Storage, Instagram, ffmpeg ni tekshiradi |
| `.env faylda ... to'ldirilmagan` | `.env` da shu qatorni to'ldiring |
| Bazaga ulanmayapti | `DATABASE_URL` da **Session pooler** havolasi va to'g'ri parol bo'lsin |
| Bot javob bermayapti | `OWNER_TELEGRAM_ID` to'g'rimi? Terminalda xato bormi? |
| Panel ochilmayapti | `python main.py` ishlayaptimi? 8080 port band bo'lsa `.env` da `PANEL_PORT=8081` |
| "Havola eskirgan" | Botga qayta `/panel` yozing (havola 15 daqiqa, bir marta) |
| Ovozga javob yo'q | `ELEVENLABS_API_KEY` to'ldirilganini tekshiring |
| "Ota-ona botga ulanmagan" | Ota-ona havolasini bosmagan: telefon orqali bog'laning |
