-- =====================================================
-- YANGILASH 1: sql/setup.sql ni AVVAL ishga tushirgan bo'lsangiz, faqat SHU faylni ishga tushiring.
-- (Yangi loyihada kerak emas: setup.sql ichida bu qism ham bor.) Bir necha marta ishga tushirsa ham zarari yo'q.
-- =====================================================

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
