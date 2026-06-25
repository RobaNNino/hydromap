-- ============================================================
-- AcquaMap Business — migration 0003 (Versione 2: Professionale)
-- Esegui nel SQL Editor di Supabase DOPO 0002.
-- Analytics, notifiche, modifiche in attesa, messaggi, audit log,
-- completezza profilo e trust score.
-- ============================================================

-- ---------- Analytics: eventi grezzi + aggregato giornaliero ----------
create table if not exists business_events (
  id                  uuid primary key default gen_random_uuid(),
  business_profile_id uuid not null references business_profiles(id) on delete cascade,
  event_type          text not null,   -- view, open_map, click_phone, click_maps, click_website, click_instagram, click_whatsapp, open_gallery
  device              text,            -- mobile | desktop
  session_id          text,
  created_at          timestamptz not null default now()
);
create index if not exists idx_events_profile_time on business_events(business_profile_id, created_at desc);

create table if not exists business_event_daily (
  id                  uuid primary key default gen_random_uuid(),
  business_profile_id uuid not null references business_profiles(id) on delete cascade,
  day                 date not null,
  event_type          text not null,
  count               integer not null default 0,
  unique (business_profile_id, day, event_type)
);
create index if not exists idx_event_daily_profile on business_event_daily(business_profile_id, day);

-- ---------- Notifiche (admin + business) ----------
create table if not exists business_notifications (
  id                  uuid primary key default gen_random_uuid(),
  audience            text not null,   -- admin | business
  business_profile_id uuid references business_profiles(id) on delete cascade,
  type                text,
  title               text not null,
  body                text default '',
  read                boolean not null default false,
  created_at          timestamptz not null default now()
);
create index if not exists idx_notif_audience on business_notifications(audience, read, created_at desc);
create index if not exists idx_notif_profile on business_notifications(business_profile_id);

-- ---------- Modifiche in attesa ----------
create table if not exists business_pending_changes (
  id                  uuid primary key default gen_random_uuid(),
  business_profile_id uuid not null references business_profiles(id) on delete cascade,
  field               text not null,
  old_value           text,
  new_value           text,
  status              text not null default 'pending' check (status in ('pending','approved','rejected')),
  requested_by        text,
  admin_notes         text default '',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists idx_pending_status on business_pending_changes(status, created_at desc);
create index if not exists idx_pending_profile on business_pending_changes(business_profile_id);

-- ---------- Messaggi admin <-> business ----------
create table if not exists business_messages (
  id                  uuid primary key default gen_random_uuid(),
  business_profile_id uuid not null references business_profiles(id) on delete cascade,
  sender              text not null,   -- admin | business
  body                text not null,
  created_at          timestamptz not null default now()
);
create index if not exists idx_messages_profile on business_messages(business_profile_id, created_at);

-- ---------- Audit log ----------
create table if not exists business_audit_log (
  id                  uuid primary key default gen_random_uuid(),
  business_profile_id uuid references business_profiles(id) on delete set null,
  actor               text,
  action              text not null,
  note                text default '',
  created_at          timestamptz not null default now()
);
create index if not exists idx_audit_time on business_audit_log(created_at desc);

-- ---------- Profili: completezza + trust score (cache calcolata) ----------
alter table business_profiles
  add column if not exists completeness integer not null default 0,
  add column if not exists trust_score  integer not null default 0;

-- ---------- RLS: tutte queste tabelle solo via secret key (server) ----------
alter table business_events          enable row level security;
alter table business_event_daily     enable row level security;
alter table business_notifications   enable row level security;
alter table business_pending_changes enable row level security;
alter table business_messages        enable row level security;
alter table business_audit_log       enable row level security;
-- Nessuna policy pubblica: l'accesso passa dal backend Flask (secret key).
