-- Copy to homeall-ecommerce-api/supabase/migrations/.
-- Requires the existing admin notification events migration. No history backfill.
create table public.frappe_notification_outbox (
 event_id uuid primary key references public.admin_notification_events(id) on delete cascade,
 status text not null default 'pending' check(status in ('pending','processing','sent','failed')),
 attempts integer not null default 0 check(attempts >= 0),
 next_attempt_at timestamptz not null default now(),
 claimed_at timestamptz,
 claim_id uuid,
 last_error text,
 sent_at timestamptz,
 created_at timestamptz not null default clock_timestamp()
);
create index frappe_notification_due_idx on public.frappe_notification_outbox(next_attempt_at)
 where status in ('pending','processing');
alter table public.frappe_notification_outbox enable row level security;
revoke all on public.frappe_notification_outbox from public, anon, authenticated;
grant all on public.frappe_notification_outbox to service_role;

create function private.queue_frappe_notification() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if new.event_type in ('order_created','chat_message') then
  insert into public.frappe_notification_outbox(event_id) values(new.id) on conflict do nothing;
 end if;
 return new;
end; $$;
create trigger queue_frappe_notification after insert on public.admin_notification_events
 for each row execute function private.queue_frappe_notification();

create function public.api_claim_frappe_notifications(p_limit integer default 25)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_result jsonb;
begin
 if p_limit<1 or p_limit>100 then raise exception 'VALIDATION_ERROR'; end if;
 update public.frappe_notification_outbox set status='failed',claimed_at=null,claim_id=null,
  last_error='LEASE_EXHAUSTED' where status='processing' and attempts>=8
  and claimed_at < now()-interval '5 minutes';
 with due as (
  select event_id from public.frappe_notification_outbox where attempts<8 and
   ((status='pending' and next_attempt_at<=now()) or
    (status='processing' and claimed_at<now()-interval '5 minutes'))
  order by next_attempt_at,event_id for update skip locked limit p_limit
 ), claimed as (
  update public.frappe_notification_outbox o set status='processing',attempts=attempts+1,
   claimed_at=now(),claim_id=gen_random_uuid() from due where o.event_id=due.event_id returning o.*
 )
 select coalesce(jsonb_agg(jsonb_build_object(
  'id',c.event_id,'claim_id',c.claim_id,'attempts',c.attempts,
  'event',jsonb_build_object('id',e.id,'type',e.event_type,'created_at',e.created_at,
   'payload',case when e.event_type='order_created' then jsonb_build_object('order_id',e.order_id)
    else jsonb_build_object('conversation_id',e.payload->>'conversation_id','message_id',e.message_id) end)
  ) order by c.created_at,c.event_id),'[]'::jsonb) into v_result
 from claimed c join public.admin_notification_events e on e.id=c.event_id;
 return v_result;
end; $$;

create function public.api_finish_frappe_notification(p_event uuid,p_claim uuid,p_success boolean,p_error text default null)
returns void language plpgsql security definer set search_path='' as $$
begin
 update public.frappe_notification_outbox set
  status=case when p_success then 'sent' when attempts>=8 then 'failed' else 'pending' end,
  sent_at=case when p_success then now() else sent_at end,
  next_attempt_at=case when p_success then next_attempt_at
   else now()+least(interval '24 hours',interval '1 minute'*power(3,attempts-1)) end,
  last_error=case when p_success then null else left(coalesce(p_error,'WEBHOOK_FAILED'),100) end,
  claimed_at=null,claim_id=null
 where event_id=p_event and claim_id=p_claim and status='processing';
end; $$;

create function public.api_replay_frappe_notification(p_event uuid)
returns void language sql security definer set search_path='' as $$
 update public.frappe_notification_outbox set status='pending',attempts=0,
 next_attempt_at=now(),claimed_at=null,claim_id=null,last_error=null where event_id=p_event and status='failed';
$$;
revoke all on function private.queue_frappe_notification(),public.api_claim_frappe_notifications(integer),
 public.api_finish_frappe_notification(uuid,uuid,boolean,text),public.api_replay_frappe_notification(uuid)
 from public,anon,authenticated;
grant execute on function private.queue_frappe_notification(),public.api_claim_frappe_notifications(integer),
 public.api_finish_frappe_notification(uuid,uuid,boolean,text),public.api_replay_frappe_notification(uuid) to service_role;
