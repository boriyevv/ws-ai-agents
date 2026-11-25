-- =====================================================
-- WS-TIZIM: o'quv markazlar CRM bazasi (HAMMASI BITTA FAYLDA)
-- Supabase > SQL Editor > New query: shu faylning HAMMA matnini yopishtiring va Run bosing.
-- Faqat BIR MARTA ishga tushiriladi (yangi, bo'sh loyihada).
-- =====================================================

create extension if not exists pgcrypto;

-- ---------- Turlar (enum) ----------
create type user_role         as enum ('owner', 'manager', 'admin', 'teacher');
create type student_status    as enum ('active', 'frozen', 'left');
create type attendance_status as enum ('present', 'absent');
create type lead_status       as enum ('new', 'contacted', 'trial', 'enrolled', 'rejected');
create type request_status    as enum ('pending', 'approved', 'rejected', 'expired');
create type permission_level  as enum ('allow', 'needs_owner_approval', 'deny');

-- ---------- Filiallar va xonalar ----------
create table branches (
  id         uuid primary key default gen_random_uuid(),
  name       text not null unique,
  address    text,
  is_active  boolean not null default true,   -- 2-filial hozircha false
  created_at timestamptz not null default now()
);

create table rooms (
  id        uuid primary key default gen_random_uuid(),
  branch_id uuid not null references branches(id),
  name      text not null,
  unique (branch_id, name)
);

-- ---------- Xodimlar (siz, manager, admin, o'qituvchi) ----------
create table staff (
  id          uuid primary key default gen_random_uuid(),
  full_name   text not null,
  role        user_role not null,
  telegram_id bigint unique,                  -- tanish uchun asosiy kalit
  phone       text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- Kim qaysi filialni ko'ra oladi (egasi kodda hammasini ko'radi)
create table staff_branch_access (
  staff_id   uuid references staff(id) on delete cascade,
  branch_id  uuid references branches(id) on delete cascade,
  granted_by uuid references staff(id),
  granted_at timestamptz not null default now(),
  primary key (staff_id, branch_id)
);

create table teachers (
  id        uuid primary key default gen_random_uuid(),
  staff_id  uuid unique references staff(id),
  subject   text,
  pay_type  text,                             -- masalan: fix / foiz
  notes     text
);

-- ---------- Guruhlar ----------
create table groups (
  id          uuid primary key default gen_random_uuid(),
  branch_id   uuid not null references branches(id),
  name        text not null,                  -- Excel varaq nomi bilan bir xil bo'lsin
  subject     text not null,
  teacher_id  uuid references teachers(id),
  room_id     uuid references rooms(id),
  days        smallint[] not null,            -- 1=Du, 2=Se, 3=Chor, 4=Pay, 5=Juma, 6=Shanba, 7=Yak
  start_time  time not null,
  end_time    time not null,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  check (end_time > start_time)
);

-- Bir xonaga ikki guruh bir vaqtda tushib qolmasligi uchun
create or replace function check_room_conflict() returns trigger as $$
begin
  if new.room_id is not null and new.is_active and exists (
    select 1 from groups g
    where g.room_id = new.room_id
      and g.is_active
      and g.id <> new.id
      and g.days && new.days
      and g.start_time < new.end_time
      and g.end_time   > new.start_time
  ) then
    raise exception 'Bu xona shu kun va vaqtda band';
  end if;
  return new;
end;
$$ language plpgsql;

create trigger trg_room_conflict
  before insert or update on groups
  for each row execute function check_room_conflict();

-- ---------- O'quvchilar va ota-onalar ----------
create table students (
  id          uuid primary key default gen_random_uuid(),
  branch_id   uuid not null references branches(id),
  full_name   text not null,
  status      student_status not null default 'active',
  joined_on   date,
  -- Telegram havolasi uchun noyob kod: t.me/BotNomi?start=<invite_code>
  invite_code text not null unique default substr(md5(gen_random_uuid()::text), 1, 10),
  created_at  timestamptz not null default now()
);

create table parents (
  id          uuid primary key default gen_random_uuid(),
  full_name   text,
  phone       text,
  telegram_id bigint unique,                  -- ota-ona havolani bosganda to'ldiriladi
  created_at  timestamptz not null default now()
);

create table student_parents (
  student_id uuid references students(id) on delete cascade,
  parent_id  uuid references parents(id)  on delete cascade,
  relation   text,                            -- ota / ona / boshqa
  primary key (student_id, parent_id)
);

-- ---------- Guruhga yozilish (to'lov tsikli shu yerda) ----------
create table enrollments (
  id                uuid primary key default gen_random_uuid(),
  student_id        uuid not null references students(id),
  group_id          uuid not null references groups(id),
  joined_on         date not null,            -- tsikl shu sanadan boshlanadi
  next_payment_due  date,                     -- keyingi to'lov sanasi (30 kunlik tsikl)
  monthly_fee       numeric(12,0),
  status            student_status not null default 'active',
  unique (student_id, group_id)
);

-- ---------- Davomat (Excel dagi "+" / "-" ustunlari) ----------
create table attendance (
  id            uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references enrollments(id) on delete cascade,
  lesson_date   date not null,
  status        attendance_status not null,
  reason        text,
  marked_by     uuid references staff(id),
  marked_at     timestamptz not null default now(),
  unique (enrollment_id, lesson_date)
);

-- ---------- To'lovlar ----------
create table payments (
  id            uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references enrollments(id),
  amount        numeric(12,0) not null,
  paid_on       date not null,
  period_start  date,
  period_end    date,
  method        text,                         -- naqd / karta / o'tkazma
  recorded_by   uuid references staff(id),
  note          text
);

-- ---------- Muzlatish (1 haftadan ko'p uzluksiz qoldirish) ----------
create table freezes (
  id            uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references enrollments(id),
  start_date    date not null,
  end_date      date,
  reason        text,
  status        request_status not null default 'pending',
  requested_by  uuid references staff(id),
  approved_by   uuid references staff(id),
  created_at    timestamptz not null default now()
);

-- ---------- Imtihon natijalari (o'qituvchi tahlili uchun) ----------
create table exams (
  id           uuid primary key default gen_random_uuid(),
  student_id   uuid not null references students(id),
  group_id     uuid not null references groups(id),
  exam_name    text not null,                 -- masalan: IELTS mock
  exam_date    date not null,
  score        numeric(5,2),
  target_score numeric(5,2),
  notes        text
);

-- ---------- Marketing: lidlar, kampaniyalar, xarajat ----------
create table campaigns (
  id         uuid primary key default gen_random_uuid(),
  branch_id  uuid references branches(id),
  name       text not null,
  platform   text,                            -- instagram / telegram
  start_date date,
  end_date   date
);

create table marketing_spend (
  id          uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id),
  spend_date  date not null,
  amount      numeric(12,0) not null
);

create table leads (
  id          uuid primary key default gen_random_uuid(),
  branch_id   uuid references branches(id),
  full_name   text,
  phone       text,
  source      text,                           -- instagram_forma / telegram / tavsiya
  campaign_id uuid references campaigns(id),
  status      lead_status not null default 'new',
  assigned_to uuid references staff(id),
  student_id  uuid references students(id),   -- o'quvchi bo'lsa bog'lanadi
  created_at  timestamptz not null default now()
);

create table lead_activities (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references leads(id) on delete cascade,
  staff_id   uuid references staff(id),
  kind       text,                            -- qo'ng'iroq / yozishma / sinov darsi
  note       text,
  created_at timestamptz not null default now()
);

-- ---------- Ruxsatlar, tasdiqlar, jurnal ----------
create table role_permissions (
  role   user_role not null,
  action text not null,
  level  permission_level not null,
  primary key (role, action)
);

-- Jadvalda yo'q harakat = rad etiladi (deny). Keyin xohlagancha o'zgartirasiz.
insert into role_permissions (role, action, level) values
  ('owner',   'mark_attendance',    'allow'),
  ('owner',   'message_parents',    'allow'),
  ('owner',   'grant_branch_access','allow'),
  ('owner',   'open_group',         'allow'),
  ('owner',   'view_finance',       'allow'),
  ('owner',   'publish_post',       'allow'),
  ('manager', 'mark_attendance',    'allow'),
  ('manager', 'message_parents',    'allow'),
  ('manager', 'grant_branch_access','needs_owner_approval'),
  ('manager', 'open_group',         'needs_owner_approval'),
  ('manager', 'view_finance',       'allow'),
  ('manager', 'publish_post',       'needs_owner_approval'),
  ('admin',   'mark_attendance',    'allow'),
  ('admin',   'message_parents',    'allow'),
  ('admin',   'grant_branch_access','deny'),
  ('admin',   'open_group',         'deny'),
  ('admin',   'view_finance',       'deny'),
  ('admin',   'publish_post',       'deny');

create table approval_requests (
  id           uuid primary key default gen_random_uuid(),
  requested_by uuid not null references staff(id),
  action       text not null,
  payload      jsonb not null default '{}',
  status       request_status not null default 'pending',
  decided_by   uuid references staff(id),
  created_at   timestamptz not null default now(),
  decided_at   timestamptz
);

create table audit_log (
  id         bigint generated always as identity primary key,
  actor_id   uuid references staff(id),
  action     text not null,
  details    jsonb not null default '{}',
  created_at timestamptz not null default now()
);

-- ---------- Xavfsizlik ----------
-- Hamma jadvalda RLS yoqiladi. Siyosat yo'q, ya'ni tashqaridan (anon kalit bilan)
-- hech narsa o'qib bo'lmaydi. Bot serverda service_role kaliti bilan ishlaydi.
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;

-- ---------- Boshlang'ich ma'lumot ----------
insert into branches (name, is_active) values
  ('1-filial', true),
  ('2-filial', false);

-- =====================================================

-- To'lov tsikli (har 30 kunda yangilanadi)
alter table enrollments add column if not exists cycle_start   date;
alter table enrollments add column if not exists cycle_paid    boolean not null default false;
alter table enrollments add column if not exists unpaid_cycles int     not null default 0;  -- manfiy = oldindan to'langan

alter table students add column if not exists notes text;

-- Xodimni botga taklif qilish kodi
alter table staff add column if not exists invite_code text unique;

alter table leads add column if not exists alerted_at timestamptz;
alter table leads add column if not exists note       text;

-- Xarajatlar
create table if not exists expenses (
  id          uuid primary key default gen_random_uuid(),
  branch_id   uuid references branches(id),
  amount      numeric(12,0) not null,
  category    text,
  note        text,
  spent_on    date not null default current_date,
  recorded_by uuid references staff(id),
  created_at  timestamptz not null default now()
);

-- Suhbat xotirasi (har bir xodim bilan oxirgi xabarlar)
create table if not exists conversations (
  id         bigint generated always as identity primary key,
  staff_id   uuid not null references staff(id) on delete cascade,
  role       text not null check (role in ('user', 'assistant')),
  content    text not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_conv_staff on conversations (staff_id, id desc);

-- Biznes haqida doimiy eslatmalar ("eslab qol...")
create table if not exists business_notes (
  id         bigint generated always as identity primary key,
  note       text not null,
  created_by uuid references staff(id),
  created_at timestamptz not null default now()
);

-- Tasdiq kutayotgan amallar (agent "ha" kutadi)
create table if not exists pending_actions (
  id         uuid primary key default gen_random_uuid(),
  staff_id   uuid not null references staff(id) on delete cascade,
  tool       text not null,
  args       jsonb not null default '{}',
  summary    text,
  status     text not null default 'pending',   -- pending / executed / cancelled / replaced
  created_at timestamptz not null default now()
);

-- Yuborilgan xabarlar jurnali (ota-ona, xodim)
create table if not exists message_log (
  id         bigint generated always as identity primary key,
  sender_id  uuid references staff(id),
  to_kind    text,            -- parent / staff
  to_ref     text,
  body       text,
  ok         boolean,
  error      text,
  created_at timestamptz not null default now()
);

-- Chop etilgan postlar
create table if not exists social_posts (
  id         uuid primary key default gen_random_uuid(),
  platform   text not null,
  body       text,
  image_url  text,
  ok         boolean,
  result     text,
  posted_by  uuid references staff(id),
  created_at timestamptz not null default now()
);

-- Qo'shimcha ruxsatlar (mavjudlarini yangilaydi)
insert into role_permissions (role, action, level) values
  ('owner',   'add_student',        'allow'),
  ('owner',   'record_payment',     'allow'),
  ('owner',   'freeze_student',     'allow'),
  ('owner',   'add_staff',          'allow'),
  ('owner',   'view_staff',         'allow'),
  ('owner',   'add_expense',        'allow'),
  ('owner',   'manage_leads',       'allow'),
  ('owner',   'view_marketing',     'allow'),
  ('owner',   'manage_marketing',   'allow'),
  ('owner',   'view_teacher_reports','allow'),
  ('owner',   'add_exam_result',    'allow'),
  ('owner',   'message_staff',      'allow'),
  ('owner',   'export_data',        'allow'),
  ('owner',   'remember',           'allow'),
  ('owner',   'edit_payment_cycle', 'allow'),

  ('manager', 'add_student',        'allow'),
  ('manager', 'record_payment',     'allow'),
  ('manager', 'freeze_student',     'allow'),
  ('manager', 'add_staff',          'deny'),
  ('manager', 'view_staff',         'allow'),
  ('manager', 'add_expense',        'allow'),
  ('manager', 'manage_leads',       'allow'),
  ('manager', 'view_marketing',     'allow'),
  ('manager', 'manage_marketing',   'allow'),
  ('manager', 'view_teacher_reports','allow'),
  ('manager', 'add_exam_result',    'allow'),
  ('manager', 'message_staff',      'allow'),
  ('manager', 'export_data',        'allow'),
  ('manager', 'remember',           'allow'),
  ('manager', 'edit_payment_cycle', 'allow'),

  ('admin',   'add_student',        'allow'),
  ('admin',   'record_payment',     'allow'),
  ('admin',   'freeze_student',     'needs_owner_approval'),
  ('admin',   'add_staff',          'deny'),
  ('admin',   'view_staff',         'deny'),
  ('admin',   'add_expense',        'deny'),
  ('admin',   'manage_leads',       'allow'),
  ('admin',   'view_marketing',     'deny'),
  ('admin',   'manage_marketing',   'deny'),
  ('admin',   'view_teacher_reports','deny'),
  ('admin',   'add_exam_result',    'allow'),
  ('admin',   'message_staff',      'deny'),
  ('admin',   'export_data',        'deny'),
  ('admin',   'remember',           'deny'),
  ('admin',   'edit_payment_cycle', 'deny')
on conflict (role, action) do update set level = excluded.level;

-- Yangi jadvallarda ham RLS yoqiladi (tashqaridan kirishni yopadi)
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;

-- =====================================================
-- 3-QISM: xonalar, o'qituvchi ruxsatlari, kompyuter paneli
-- =====================================================

-- Xonalar: 1-filialda 3 ta, 2-filialda 6 ta (nomlarini keyin Table Editor'da o'zgartirsangiz bo'ladi)
insert into rooms (branch_id, name)
select b.id, n || '-xona' from branches b, generate_series(1, 3) n where b.name = '1-filial'
on conflict do nothing;
insert into rooms (branch_id, name)
select b.id, n || '-xona' from branches b, generate_series(1, 6) n where b.name = '2-filial'
on conflict do nothing;

-- O'qituvchi: faqat o'z guruhlari davomati va imtihon natijalari
insert into role_permissions (role, action, level) values
  ('teacher', 'mark_attendance', 'allow'),
  ('teacher', 'add_exam_result', 'allow')
on conflict (role, action) do update set level = excluded.level;

-- Kompyuter paneli (brauzer) uchun kirish sessiyalari. Faqat xesh saqlanadi.
create table if not exists web_sessions (
  token_hash text primary key,
  staff_id   uuid not null references staff(id) on delete cascade,
  kind       text not null check (kind in ('login', 'session')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_web_sessions_staff on web_sessions (staff_id);

-- Tez ishlashi uchun indekslar
create index if not exists idx_enr_group   on enrollments (group_id);
create index if not exists idx_enr_student on enrollments (student_id);
create index if not exists idx_pay_enr     on payments (enrollment_id, paid_on);
create index if not exists idx_leads_br    on leads (branch_id, created_at desc);

-- Yangi jadvallarda ham RLS (tashqaridan kirish yopiq)
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;

-- =====================================================
-- 4-QISM: vazifalar, kontent (post/video), AI agentlar
-- =====================================================

-- Xodimlarga vazifalar ("Jimi, Zufar bugun darsini 1 soat ertaroq boshlasin")
create table if not exists tasks (
  id          uuid primary key default gen_random_uuid(),
  text        text not null,
  assigned_to uuid not null references staff(id) on delete cascade,
  created_by  uuid references staff(id),
  batch_id    uuid,                         -- bitta buyruq bilan bir nechta odamga yuborilganlar
  due_at      timestamptz,
  status      text not null default 'sent' check (status in ('sent', 'seen', 'done', 'cancelled')),
  delivered   boolean not null default false,
  reminded_at timestamptz,
  done_at     timestamptz,
  created_at  timestamptz not null default now()
);
create index if not exists idx_tasks_assignee on tasks (assigned_to, status);
create index if not exists idx_tasks_creator  on tasks (created_by, created_at desc);

-- Telegram kanal va Instagram uchun postlar (darhol yoki rejalashtirilgan)
create table if not exists content_posts (
  id           uuid primary key default gen_random_uuid(),
  body         text,
  media_kind   text not null default 'none' check (media_kind in ('none', 'photo', 'video')),
  media_url    text,
  tg_file_id   text,
  targets      text[] not null,
  status       text not null default 'scheduled'
               check (status in ('scheduled', 'publishing', 'published', 'partial', 'failed', 'cancelled')),
  scheduled_at timestamptz not null default now(),
  published_at timestamptz,
  results      jsonb not null default '{}',
  created_by   uuid references staff(id),
  created_at   timestamptz not null default now()
);
create index if not exists idx_posts_due on content_posts (status, scheduled_at);

insert into role_permissions (role, action, level) values
  ('owner',   'assign_tasks',  'allow'),
  ('owner',   'manage_agents', 'allow'),
  ('manager', 'assign_tasks',  'allow'),
  ('manager', 'manage_agents', 'needs_owner_approval'),
  ('admin',   'assign_tasks',  'deny'),
  ('admin',   'manage_agents', 'deny')
on conflict (role, action) do update set level = excluded.level;

do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;

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
