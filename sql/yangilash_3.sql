-- =====================================================
-- YANGILASH 3: setup.sql ni avval ishga tushirgan bo'lsangiz SHU faylni ham ishga tushiring.
-- (yangilash_1 va yangilash_2 dan keyin). Qayta ishga tushirsa ham zarari yo'q.
-- =====================================================

-- =====================================================
-- 6-QISM: AI yaratgan rasm/videolarni eslab qolish ("shuni kanalga chiqar")
-- =====================================================
create table if not exists generated_media (
  id         uuid primary key default gen_random_uuid(),
  staff_id   uuid references staff(id) on delete cascade,
  kind       text not null check (kind in ('photo', 'video')),
  url        text,
  file_id    text,
  prompt     text,
  source     text,                    -- design / ai_image / ai_video / edit_video
  created_at timestamptz not null default now()
);
create index if not exists idx_genmedia_staff on generated_media (staff_id, created_at desc);

do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;
