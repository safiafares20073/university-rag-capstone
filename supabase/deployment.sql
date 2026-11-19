-- Private deployment state. No user/chat tables are changed.
create table if not exists public.rag_deployment_state (
 id integer primary key check(id=1), token_hash text not null,
 limit_micro bigint not null default 12000000 check(limit_micro=12000000),
 prior_allowance_micro bigint not null default 2000000 check(prior_allowance_micro>=0),
 index_payload text, index_sha256 text
);
create table if not exists public.rag_api_requests (
 request_id uuid primary key, amount_micro bigint not null check(amount_micro>=0),
 state text not null check(state in ('reserved','usage')), endpoint text not null,
 model text not null, created_at timestamptz not null default now()
);
alter table public.rag_deployment_state enable row level security;
alter table public.rag_api_requests enable row level security;
revoke all on public.rag_deployment_state,public.rag_api_requests from public,anon,authenticated;
create or replace function public.rag_reserve(p_token text,p_request_id uuid,p_amount_micro bigint,p_endpoint text,p_model text)
returns bigint language plpgsql security definer set search_path='' as $$
declare cfg public.rag_deployment_state%rowtype; used bigint;
begin
 select * into cfg from public.rag_deployment_state where id=1 for update;
 if cfg.id is null or p_token is null or cfg.token_hash is distinct from encode(sha256(convert_to(p_token,'UTF8')),'hex') then raise exception 'Unauthorized deployment'; end if;
 if p_amount_micro is null or p_amount_micro<=0 or p_amount_micro>1000000 then raise exception 'Invalid reservation'; end if;
 if exists(select 1 from public.rag_api_requests where request_id=p_request_id) then raise exception 'Duplicate request id'; end if;
 select coalesce(sum(amount_micro),0)+cfg.prior_allowance_micro into used from public.rag_api_requests;
 if used+p_amount_micro>cfg.limit_micro-500000 then raise exception 'DEPLOYMENT_BUDGET_REACHED'; end if;
 insert into public.rag_api_requests values(p_request_id,p_amount_micro,'reserved',p_endpoint,p_model,now());
 return used+p_amount_micro;
end $$;
create or replace function public.rag_settle(p_token text,p_request_id uuid,p_amount_micro bigint)
returns void language plpgsql security definer set search_path='' as $$
declare cfg public.rag_deployment_state%rowtype; held bigint;
begin
 select * into cfg from public.rag_deployment_state where id=1 for update;
 if cfg.id is null or p_token is null or cfg.token_hash is distinct from encode(sha256(convert_to(p_token,'UTF8')),'hex') then raise exception 'Unauthorized deployment'; end if;
 select amount_micro into held from public.rag_api_requests where request_id=p_request_id and state='reserved';
 if held is null or p_amount_micro is null or p_amount_micro<0 or p_amount_micro>held then raise exception 'Invalid settlement'; end if;
 update public.rag_api_requests set amount_micro=p_amount_micro,state='usage' where request_id=p_request_id;
end $$;
create or replace function public.rag_budget_status(p_token text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare cfg public.rag_deployment_state%rowtype; used bigint; priced bigint; attempts bigint;
begin
 select * into cfg from public.rag_deployment_state where id=1;
 if cfg.id is null or p_token is null or cfg.token_hash is distinct from encode(sha256(convert_to(p_token,'UTF8')),'hex') then raise exception 'Unauthorized deployment'; end if;
 select coalesce(sum(amount_micro),0),coalesce(sum(amount_micro) filter(where state='usage'),0),count(*) into used,priced,attempts from public.rag_api_requests;
 return jsonb_build_object('limit_usd',cfg.limit_micro/1000000.0,'prior_allowance_usd',cfg.prior_allowance_micro/1000000.0,'token_priced_since_deployment_usd',priced/1000000.0,'including_reservations_usd',used/1000000.0,'remaining_before_stop_usd',greatest(0,cfg.limit_micro-500000-cfg.prior_allowance_micro-used)/1000000.0,'attempts',attempts,'provider_balance_available',false);
end $$;
create or replace function public.rag_publish_index(p_token text,p_payload text,p_sha256 text)
returns void language plpgsql security definer set search_path='' as $$
declare cfg public.rag_deployment_state%rowtype;
begin
 select * into cfg from public.rag_deployment_state where id=1 for update;
 if cfg.id is null or p_token is null or cfg.token_hash is distinct from encode(sha256(convert_to(p_token,'UTF8')),'hex') then raise exception 'Unauthorized deployment'; end if;
 if p_payload is null or length(p_payload)>60000000 or p_sha256 is distinct from encode(sha256(decode(p_payload,'base64')),'hex') then raise exception 'Invalid snapshot'; end if;
 update public.rag_deployment_state set index_payload=p_payload,index_sha256=p_sha256 where id=1;
end $$;
create or replace function public.rag_get_index(p_token text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare cfg public.rag_deployment_state%rowtype;
begin
 select * into cfg from public.rag_deployment_state where id=1;
 if cfg.id is null or p_token is null or cfg.token_hash is distinct from encode(sha256(convert_to(p_token,'UTF8')),'hex') then raise exception 'Unauthorized deployment'; end if;
 if cfg.index_payload is null then raise exception 'Snapshot has not been published'; end if;
 return jsonb_build_object('payload',cfg.index_payload,'sha256',cfg.index_sha256);
end $$;
revoke all on function public.rag_reserve(text,uuid,bigint,text,text),public.rag_settle(text,uuid,bigint),public.rag_budget_status(text),public.rag_publish_index(text,text,text),public.rag_get_index(text) from public;
grant execute on function public.rag_reserve(text,uuid,bigint,text,text),public.rag_settle(text,uuid,bigint),public.rag_budget_status(text),public.rag_publish_index(text,text,text),public.rag_get_index(text) to anon,authenticated;

-- Generate the credential once; save the returned token privately.
with credential as (select gen_random_uuid()::text||gen_random_uuid()::text as token),
inserted as (
 insert into public.rag_deployment_state(id,token_hash)
 select 1,encode(sha256(convert_to(token,'UTF8')),'hex') from credential
 on conflict(id) do nothing returning id
)
select token as deployment_token from credential where exists(select 1 from inserted);

