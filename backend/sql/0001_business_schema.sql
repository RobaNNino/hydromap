-- ============================================================
-- AcquaMap Business — schema Supabase (Postgres)
-- Esegui questo file una volta nel dashboard Supabase:
--   SQL Editor → New query → incolla → Run.
--
-- Modello: il backend Flask accede con la SECRET key (service_role),
-- che BYPASSA la RLS. Le policy RLS qui sotto sono una difesa in profondità
-- per l'accesso diretto con la publishable key (es. dal browser in futuro):
--   - chiunque può leggere i profili PUBBLICATI e la loro acqua;
--   - il titolare (owner_id = auth.uid()) può leggere/aggiornare il proprio profilo;
--   - le richieste (applications) NON sono leggibili pubblicamente.
-- ============================================================

create extension if not exists pgcrypto;

-- ---------- updated_at trigger ----------
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end; $$;

-- ============================================================
-- business_applications (richieste di accesso)
-- ============================================================
create table if not exists business_applications (
  id              uuid primary key default gen_random_uuid(),
  business_name   text not null,
  category        text not null default 'altro',
  contact_name    text not null,
  contact_email   text not null,
  contact_phone   text default '',
  address         text default '',
  city            text default '',
  province        text default '',
  region          text default '',
  website         text default '',
  instagram       text default '',
  message         text default '',
  wants_expand_program boolean not null default false,
  privacy_accepted     boolean not null default false,
  status          text not null default 'pending'
                    check (status in ('pending','approved','rejected')),
  admin_notes     text default '',
  profile_id      uuid,                 -- link soft al profilo creato (no FK: evita ciclo)
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_applications_status on business_applications(status);
create index if not exists idx_applications_created on business_applications(created_at desc);

drop trigger if exists trg_applications_updated on business_applications;
create trigger trg_applications_updated before update on business_applications
  for each row execute function set_updated_at();

-- ============================================================
-- business_profiles
-- ============================================================
create table if not exists business_profiles (
  id              uuid primary key default gen_random_uuid(),
  slug            text not null unique,
  business_name   text not null,
  category        text not null default 'altro',
  description     text default '',
  address         text default '',
  city            text default '',
  province        text default '',
  region          text default '',
  country         text default 'Italia',
  latitude        double precision,
  longitude       double precision,
  phone           text default '',
  public_email    text default '',
  website         text default '',
  instagram       text default '',
  logo_url        text default '',
  cover_image_url text default '',
  status          text not null default 'draft'
                    check (status in ('draft','published','hidden','suspended')),
  verification_status text not null default 'not_verified'
                    check (verification_status in ('not_verified','verified','business_verified')),
  is_expand_program boolean not null default false,
  is_premium        boolean not null default false,
  owner_id        uuid references auth.users(id) on delete set null,  -- titolare (Supabase Auth)
  owner_email     text default '',      -- per il "claim by email" alla prima login
  contact_email   text default '',      -- email referente privata (mai esposta pubblicamente)
  application_id  uuid,                 -- link soft alla richiesta d'origine
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_profiles_status on business_profiles(status);
create index if not exists idx_profiles_owner on business_profiles(owner_id);
create index if not exists idx_profiles_owner_email on business_profiles(lower(owner_email));

drop trigger if exists trg_profiles_updated on business_profiles;
create trigger trg_profiles_updated before update on business_profiles
  for each row execute function set_updated_at();

-- ============================================================
-- business_water_info (1:1 con business_profiles)
-- ============================================================
create table if not exists business_water_info (
  id              uuid primary key default gen_random_uuid(),
  business_profile_id uuid not null unique
                    references business_profiles(id) on delete cascade,
  water_type        text[] not null default '{}',
  has_filter_system text not null default 'undeclared'
                    check (has_filter_system in ('yes','no','undeclared')),
  has_sparkling_water boolean not null default false,
  has_natural_water   boolean not null default false,
  notes           text default '',
  ph              double precision,
  hardness        double precision,
  residue_fixed   double precision,
  conductivity    double precision,
  chlorine        double precision,
  nitrates        double precision,
  sodium          double precision,
  calcium         double precision,
  magnesium       double precision,
  last_updated_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_water_profile on business_water_info(business_profile_id);

drop trigger if exists trg_water_updated on business_water_info;
create trigger trg_water_updated before update on business_water_info
  for each row execute function set_updated_at();

-- ============================================================
-- Row Level Security (backstop: il server usa la secret key e la bypassa)
-- ============================================================
alter table business_applications enable row level security;
alter table business_profiles      enable row level security;
alter table business_water_info    enable row level security;

-- Profili: lettura pubblica solo se pubblicati.
drop policy if exists "public read published profiles" on business_profiles;
create policy "public read published profiles" on business_profiles
  for select using (status = 'published');

-- Profili: il titolare può leggere/aggiornare il proprio.
drop policy if exists "owner read own profile" on business_profiles;
create policy "owner read own profile" on business_profiles
  for select using (auth.uid() = owner_id);
drop policy if exists "owner update own profile" on business_profiles;
create policy "owner update own profile" on business_profiles
  for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- Acqua: leggibile se il profilo collegato è pubblicato, o se sei il titolare.
drop policy if exists "public read water of published" on business_water_info;
create policy "public read water of published" on business_water_info
  for select using (exists (
    select 1 from business_profiles p
    where p.id = business_profile_id
      and (p.status = 'published' or p.owner_id = auth.uid())
  ));

-- Nessuna policy su business_applications: l'accesso diretto (anon/authenticated)
-- è negato. Solo la secret key del server le legge/scrive.
