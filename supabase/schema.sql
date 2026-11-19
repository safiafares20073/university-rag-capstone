create table if not exists public.conversations (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 title text not null check (char_length(title) between 1 and 100),
 messages jsonb not null default '[]'::jsonb check (jsonb_typeof(messages)='array' and jsonb_array_length(messages)<=500),
 last_search_question text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index if not exists conversations_owner_updated on public.conversations(user_id,updated_at desc);
create table if not exists public.feedback (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 score integer not null check (score between 1 and 5),
 note text not null default '' check (char_length(note)<=5000),
 created_at timestamptz not null default now()
);
alter table public.conversations enable row level security;
alter table public.feedback enable row level security;
revoke all on public.conversations,public.feedback from anon;
grant select,insert,update,delete on public.conversations to authenticated;
grant select,insert on public.feedback to authenticated;
drop policy if exists own_conversations on public.conversations;
create policy own_conversations on public.conversations for all to authenticated
 using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
drop policy if exists own_feedback on public.feedback;
create policy own_feedback on public.feedback for select to authenticated using ((select auth.uid())=user_id);
drop policy if exists insert_own_feedback on public.feedback;
create policy insert_own_feedback on public.feedback for insert to authenticated with check ((select auth.uid())=user_id);
create or replace function public.touch_conversation_updated_at()
 returns trigger language plpgsql security invoker set search_path='' as $$
 begin new.updated_at=now(); return new; end; $$;
drop trigger if exists touch_conversation_updated_at on public.conversations;
create trigger touch_conversation_updated_at before update on public.conversations
 for each row execute function public.touch_conversation_updated_at();
