-- ============================================================
-- AcquaMap Business — migration 0002 (Versione 1: SaaS console)
-- Esegui nel SQL Editor di Supabase DOPO 0001.
-- Aggiunge: campi ricchi (extra jsonb), badge, stati estesi, token onboarding
-- e creazione account, account business + PIN.
-- ============================================================

-- Applications: campi extra della candidatura avanzata.
alter table business_applications
  add column if not exists extra jsonb not null default '{}'::jsonb;

-- Profiles: dati ricchi, badge, account, token.
alter table business_profiles
  add column if not exists extra jsonb not null default '{}'::jsonb,
  add column if not exists badges text[] not null default '{}',
  add column if not exists account_created boolean not null default false,
  add column if not exists pin_hash text,
  add column if not exists onboarding_token text,
  add column if not exists onboarding_expires timestamptz,
  add column if not exists account_token text,
  add column if not exists account_expires timestamptz,
  add column if not exists submitted_at timestamptz,
  add column if not exists published_at timestamptz;

create index if not exists idx_profiles_onboarding_token on business_profiles(onboarding_token);
create index if not exists idx_profiles_account_token on business_profiles(account_token);

-- Stati profilo estesi (pipeline admin).
alter table business_profiles drop constraint if exists business_profiles_status_check;
alter table business_profiles add constraint business_profiles_status_check
  check (status in ('draft','in_review','changes_requested','approved','published','hidden','suspended','archived'));

-- RLS: i token onboarding/account NON devono uscire dalle letture pubbliche.
-- (Il backend usa la secret key e bypassa la RLS; la policy pubblica di 0001
--  resta valida — i campi sensibili vengono comunque filtrati lato Flask.)
