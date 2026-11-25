-- =====================================================
-- YANGILASH 2: setup.sql ni avval ishga tushirgan bo'lsangiz: avval yangilash_1.sql, keyin SHU fayl.
-- Yangi loyihada kerak emas. Qayta ishga tushirsa ham zarari yo'q.
-- =====================================================

-- =====================================================
-- 5-QISM: media va marketing jamoasi, o'quv sifati, yollash, referral
-- =====================================================

-- Umumiy sozlamalar (markaz ohangi, sharh havolasi, referral bonusi ...)
create table if not exists settings (
  key        text primary key,
  value      text not null,
  updated_by uuid references staff(id),
  updated_at timestamptz not null default now()
);
insert into settings (key, value) values
  ('brand_voice', 'Samimiy, lekin hurmatli ("siz"). Qisqa gaplar, aniq foyda, ortiqcha va''dasiz. Emoji kam va joyida.'),
  ('referral_bonus_percent', '10'),
  ('group_capacity_default', '12')
on conflict (key) do nothing;

-- Oylik kontent reja
create table if not exists content_plan (
  id         uuid primary key default gen_random_uuid(),
  plan_date  date not null,
  category   text not null default 'boshqa'
             check (category in ('natija', 'oqituvchi', 'maslahat', 'aksiya', 'tadbir', 'boshqa')),
  topic      text not null,
  channels   text[] not null default '{telegram,instagram}',
  status     text not null default 'rejada' check (status in ('rejada', 'tayyor', 'chiqdi', 'bekor')),
  post_id    uuid references content_posts(id),
  notes      text,
  created_by uuid references staff(id),
  created_at timestamptz not null default now()
);
create index if not exists idx_plan_date on content_plan (plan_date);

-- Post -> murojaat bog'lanishi: har postda "yozilish" havolasi (t.me/bot?start=ld_<ref_code>)
alter table content_posts add column if not exists ref_code text unique default substr(md5(gen_random_uuid()::text), 1, 8);
alter table content_posts add column if not exists plan_id  uuid references content_plan(id);
alter table content_posts add column if not exists signup_link boolean not null default true;
alter table leads add column if not exists post_id     uuid references content_posts(id);
alter table leads add column if not exists telegram_id bigint;

-- Botga yozgan notanish odamlar (mijoz yoki ishga nomzod) bilan suhbat holati
create table if not exists bot_visitors (
  telegram_id bigint primary key,
  kind        text not null default 'lead' check (kind in ('lead', 'candidate')),
  ref         text,
  step        text,
  data        jsonb not null default '{}',
  updated_at  timestamptz not null default now()
);

-- O'quvchi ketishi (sana va sabab: haftalik hisobot va tahlil uchun)
alter table students add column if not exists left_on date;
alter table students add column if not exists left_reason text;
alter table enrollments add column if not exists left_on date;

-- Guruh sig'imi (bo'sh joylar hisobi uchun)
alter table groups add column if not exists capacity smallint not null default 12;

-- O'qituvchi: dars yozuvini tahlil qilishga rozilik (rozilik bo'lmasa tahlil qilinmaydi)
alter table staff add column if not exists recording_consent boolean not null default false;
alter table staff add column if not exists consent_at timestamptz;

-- Dars boshlandi/tugadi (o'qituvchi botda tugma bosadi)
create table if not exists lesson_sessions (
  id            uuid primary key default gen_random_uuid(),
  group_id      uuid not null references groups(id) on delete cascade,
  teacher_id    uuid references staff(id),
  lesson_date   date not null,
  planned_start time,
  planned_end   time,
  started_at    timestamptz,
  ended_at      timestamptz,
  unique (group_id, lesson_date)
);

-- Uy vazifalari
create table if not exists homework (
  id          uuid primary key default gen_random_uuid(),
  group_id    uuid not null references groups(id) on delete cascade,
  lesson_date date not null default current_date,
  text        text not null,
  given_by    uuid references staff(id),
  checked     boolean not null default false,
  checked_at  timestamptz,
  created_at  timestamptz not null default now()
);

-- So'rovnomalar (ota-onadan oylik 1-5 baho, kurs yakunidagi sharh)
create table if not exists surveys (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null default 'oylik' check (kind in ('oylik', 'kurs_yakuni')),
  student_id  uuid references students(id) on delete cascade,
  parent_id   uuid references parents(id) on delete cascade,
  group_id    uuid references groups(id) on delete set null,
  teacher_id  uuid references staff(id),
  rating      smallint check (rating between 1 and 5),
  comment     text,
  status      text not null default 'sent' check (status in ('sent', 'answered')),
  sent_at     timestamptz not null default now(),
  answered_at timestamptz
);
create index if not exists idx_surveys_teacher on surveys (teacher_id, answered_at);

-- O'qituvchi dars yozuvi tahlili (faqat rozilik bilan)
create table if not exists lesson_reviews (
  id          uuid primary key default gen_random_uuid(),
  teacher_id  uuid references staff(id),
  group_id    uuid references groups(id) on delete set null,
  lesson_date date,
  transcript  text,
  analysis    text,
  created_by  uuid references staff(id),
  created_at  timestamptz not null default now()
);

-- O'quvchini ushlab qolish signallari (bir xil signal har kuni takrorlanmasin)
create table if not exists retention_alerts (
  id            uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references enrollments(id) on delete cascade,
  week_start    date not null,
  reasons       text not null,
  created_at    timestamptz not null default now(),
  unique (enrollment_id, week_start)
);

-- Tavsiya (referral): do'stini olib kelganlar
create table if not exists referrals (
  id                  uuid primary key default gen_random_uuid(),
  referrer_student_id uuid not null references students(id) on delete cascade,
  new_student_id      uuid references students(id) on delete set null,
  new_lead_id         uuid references leads(id) on delete set null,
  bonus_percent       numeric(5,2),
  bonus_amount        numeric(12,0),
  status              text not null default 'kutilmoqda' check (status in ('kutilmoqda', 'tasdiqlandi', 'berildi', 'bekor')),
  note                text,
  created_by          uuid references staff(id),
  created_at          timestamptz not null default now()
);

-- Yollash: vakansiya va nomzodlar (nomzod bot havolasi orqali ariza beradi)
create table if not exists vacancies (
  id           uuid primary key default gen_random_uuid(),
  title        text not null,
  description  text,
  requirements text,
  questions    text[] not null default '{}',
  status       text not null default 'ochiq' check (status in ('ochiq', 'yopiq')),
  code         text not null unique default substr(md5(gen_random_uuid()::text), 1, 8),
  created_by   uuid references staff(id),
  created_at   timestamptz not null default now()
);
create table if not exists candidates (
  id           uuid primary key default gen_random_uuid(),
  vacancy_id   uuid references vacancies(id) on delete set null,
  full_name    text,
  phone        text,
  telegram_id  bigint,
  answers      jsonb not null default '{}',
  ai_score     smallint,
  ai_summary   text,
  status       text not null default 'yangi' check (status in ('yangi', 'saralandi', 'suhbat', 'qabul', 'rad')),
  interview_at timestamptz,
  created_at   timestamptz not null default now()
);

-- Raqobatchilar va ularning ochiq Telegram kanal postlari
create table if not exists competitors (
  id               uuid primary key default gen_random_uuid(),
  name             text not null unique,
  telegram_channel text,
  instagram        text,
  notes            text,
  created_at       timestamptz not null default now()
);
create table if not exists competitor_posts (
  id            uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references competitors(id) on delete cascade,
  post_key      text not null unique,
  text          text,
  posted_at     timestamptz,
  fetched_at    timestamptz not null default now()
);

-- Instagram izohlari (kuzatish va javob)
create table if not exists ig_comments (
  id              text primary key,
  media_id        text,
  username        text,
  text            text,
  commented_at    timestamptz,
  category        text,
  suggested_reply text,
  status          text not null default 'yangi' check (status in ('yangi', 'javob_berildi', 'etiborsiz')),
  created_at      timestamptz not null default now()
);

-- Reklama: tashqi kampaniya id (Meta Ads) va kunlik sarfni yangilash
alter table campaigns add column if not exists external_id text unique;
create unique index if not exists uq_spend_day on marketing_spend (campaign_id, spend_date);

insert into role_permissions (role, action, level) values
  ('owner',   'manage_content',  'allow'), ('manager', 'manage_content',  'allow'), ('admin', 'manage_content',  'deny'),
  ('owner',   'view_quality',    'allow'), ('manager', 'view_quality',    'allow'), ('admin', 'view_quality',    'deny'),
  ('owner',   'manage_homework', 'allow'), ('manager', 'manage_homework', 'allow'), ('admin', 'manage_homework', 'allow'),
  ('teacher', 'manage_homework', 'allow'),
  ('owner',   'send_surveys',    'allow'), ('manager', 'send_surveys',    'allow'), ('admin', 'send_surveys',    'allow'),
  ('owner',   'manage_referrals','allow'), ('manager', 'manage_referrals','allow'), ('admin', 'manage_referrals','allow'),
  ('owner',   'manage_hiring',   'allow'), ('manager', 'manage_hiring',   'allow'), ('admin', 'manage_hiring',   'deny'),
  ('owner',   'manage_ads',      'allow'), ('manager', 'manage_ads',      'allow'), ('admin', 'manage_ads',      'deny'),
  ('owner',   'manage_comments', 'allow'), ('manager', 'manage_comments', 'allow'), ('admin', 'manage_comments', 'allow'),
  ('owner',   'analyze_lessons', 'allow'), ('manager', 'analyze_lessons', 'needs_owner_approval'), ('admin', 'analyze_lessons', 'deny')
on conflict (role, action) do update set level = excluded.level;

do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;
