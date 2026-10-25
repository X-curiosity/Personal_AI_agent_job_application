-- Hosted MVP private data model. Run in the Supabase SQL editor or via Supabase CLI.
-- The application uses only a publishable/anon key; never give it a service-role key.

create table if not exists public.cv_profiles (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    filename text not null check (char_length(filename) between 1 and 120),
    object_path text not null unique,
    mime_type text not null check (mime_type in (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'text/markdown'
    )),
    byte_size bigint not null check (byte_size between 1 and 10485760),
    created_at timestamptz not null default now(),
    unique (owner_id, id)
);

create table if not exists public.target_companies (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    company_name text not null check (char_length(company_name) between 1 and 160),
    company_website text check (company_website is null or company_website ~* '^https://[^[:space:]]+$'),
    created_at timestamptz not null default now(),
    unique (owner_id, id),
    unique (owner_id, company_name)
);

create table if not exists public.application_queue (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    company_name text not null check (char_length(company_name) between 1 and 160),
    job_title text not null check (char_length(job_title) between 1 and 200),
    job_url text not null check (job_url ~* '^https://[^[:space:]]+$'),
    cv_profile_id uuid,
    stage text not null default 'saved' check (stage in ('saved', 'preparing', 'ready', 'applied')),
    notes text not null default '' check (char_length(notes) <= 4000),
    created_at timestamptz not null default now(),
    unique (owner_id, id),
    constraint application_queue_cv_owner_fk
        foreign key (owner_id, cv_profile_id)
        references public.cv_profiles(owner_id, id)
        on delete set null (cv_profile_id)
);

-- The operator configures the published notice before enabling registration.
create table if not exists public.hosted_privacy_config (
    singleton boolean primary key default true check (singleton),
    notice_version text,
    notice_url text check (notice_url is null or notice_url ~* '^https://[^[:space:]]+$'),
    updated_at timestamptz not null default now()
);
insert into public.hosted_privacy_config(singleton) values (true)
on conflict (singleton) do nothing;

-- Inserted only by the auth.users trigger; authenticated users can read their
-- own receipt but cannot write, alter, or delete it.
create table if not exists public.privacy_notice_acceptances (
    user_id uuid primary key references auth.users(id) on delete cascade,
    notice_version text not null,
    notice_url text not null check (notice_url ~* '^https://[^[:space:]]+$'),
    accepted_at timestamptz not null default now()
);
alter table public.privacy_notice_acceptances enable row level security;
drop policy if exists "privacy_notice_acceptances_owner_read" on public.privacy_notice_acceptances;
create policy "privacy_notice_acceptances_owner_read" on public.privacy_notice_acceptances
    for select to authenticated using (user_id = (select auth.uid()));
revoke all on public.hosted_privacy_config, public.privacy_notice_acceptances from PUBLIC, anon, authenticated;
grant select on public.privacy_notice_acceptances to authenticated;

create or replace function public.record_hosted_privacy_acceptance()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    configured_version text;
    configured_url text;
begin
    select notice_version, notice_url into configured_version, configured_url
    from public.hosted_privacy_config where singleton = true;
    if configured_version is null or configured_url is null
       or (new.raw_user_meta_data ->> 'privacy_notice_version') is distinct from configured_version
       or (new.raw_user_meta_data ->> 'privacy_notice_url') is distinct from configured_url then
        raise exception 'A current Privacy Notice acknowledgment is required';
    end if;
    insert into public.privacy_notice_acceptances(user_id, notice_version, notice_url, accepted_at)
    values (new.id, configured_version, configured_url, now());
    return new;
end;
$$;
revoke all on function public.record_hosted_privacy_acceptance() from PUBLIC, anon, authenticated;
drop trigger if exists hosted_privacy_acceptance_after_signup on auth.users;
create trigger hosted_privacy_acceptance_after_signup
    after insert on auth.users
    for each row execute function public.record_hosted_privacy_acceptance();

create or replace function public.hosted_user_has_privacy_acceptance()
returns boolean
language sql
stable
security definer
set search_path = pg_catalog
as $$
    select exists (
        select 1 from public.privacy_notice_acceptances
        where user_id = (select auth.uid())
    );
$$;
revoke all on function public.hosted_user_has_privacy_acceptance() from PUBLIC, anon;
grant execute on function public.hosted_user_has_privacy_acceptance() to authenticated;

create index if not exists cv_profiles_owner_created_idx on public.cv_profiles(owner_id, created_at desc);
create index if not exists target_companies_owner_created_idx on public.target_companies(owner_id, created_at desc);
create index if not exists application_queue_owner_created_idx on public.application_queue(owner_id, created_at desc);

-- A deleted Auth user can still present an unexpired JWT. Storage policies
-- must additionally confirm that the account remains active in auth.users.
create or replace function public.hosted_user_is_active()
returns boolean
language sql
stable
security definer
set search_path = pg_catalog
as $$
    select exists (
        select 1 from auth.users where id = (select auth.uid())
    );
$$;
revoke all on function public.hosted_user_is_active() from PUBLIC, anon;
grant execute on function public.hosted_user_is_active() to authenticated;

alter table public.cv_profiles enable row level security;
alter table public.target_companies enable row level security;
alter table public.application_queue enable row level security;

drop policy if exists "cv_profiles_owner_all" on public.cv_profiles;
create policy "cv_profiles_owner_all" on public.cv_profiles
    for all to authenticated
    using (
        owner_id = (select auth.uid())
        and (select public.hosted_user_has_privacy_acceptance())
    )
    with check (
        owner_id = (select auth.uid())
        and (select public.hosted_user_has_privacy_acceptance())
    );

drop policy if exists "target_companies_owner_all" on public.target_companies;
create policy "target_companies_owner_all" on public.target_companies
    for all to authenticated
    using (
        owner_id = (select auth.uid())
        and (select public.hosted_user_has_privacy_acceptance())
    )
    with check (
        owner_id = (select auth.uid())
        and (select public.hosted_user_has_privacy_acceptance())
    );

drop policy if exists "application_queue_owner_all" on public.application_queue;
create policy "application_queue_owner_all" on public.application_queue
    for all to authenticated
    using (
        owner_id = (select auth.uid())
        and (select public.hosted_user_has_privacy_acceptance())
    )
    with check (
        owner_id = (select auth.uid())
        and (select public.hosted_user_has_privacy_acceptance())
    );

revoke all on public.cv_profiles, public.target_companies, public.application_queue from anon;
grant select, insert, update, delete on public.cv_profiles, public.target_companies, public.application_queue to authenticated;

-- Private file bucket; path format is <auth-user-id>/<random-id>/<sanitized-name>.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'private-cvs', 'private-cvs', false, 10485760,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'text/markdown'
    ]
)
on conflict (id) do update set
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "private_cvs_owner_all" on storage.objects;
create policy "private_cvs_owner_all" on storage.objects
    for all to authenticated
    using (
        bucket_id = 'private-cvs'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and (select public.hosted_user_is_active())
        and (select public.hosted_user_has_privacy_acceptance())
    )
    with check (
        bucket_id = 'private-cvs'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and (select public.hosted_user_is_active())
        and (select public.hosted_user_has_privacy_acceptance())
    );

-- Short-lived, single-use OAuth state survives the external LinkedIn redirect.
-- The random state ID is a bearer secret; no anonymous table reads are granted.
create table if not exists public.hosted_oauth_states (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    provider text not null check (provider = 'linkedin_oidc'),
    code_verifier text,
    expires_at timestamptz not null default (now() + interval '10 minutes'),
    created_at timestamptz not null default now()
);
alter table public.hosted_oauth_states enable row level security;
drop policy if exists "hosted_oauth_states_owner_all" on public.hosted_oauth_states;
create policy "hosted_oauth_states_owner_all" on public.hosted_oauth_states
    for all to authenticated
    using (owner_id = (select auth.uid()) and (select public.hosted_user_is_active()))
    with check (owner_id = (select auth.uid()) and (select public.hosted_user_is_active()));
revoke all on public.hosted_oauth_states from PUBLIC, anon;
grant select, insert, update, delete on public.hosted_oauth_states to authenticated;

create or replace function public.consume_hosted_oauth_state(state_id uuid)
returns table(code_verifier text)
language plpgsql
security definer
set search_path = pg_catalog
as $$
begin
    return query
        delete from public.hosted_oauth_states as state
        where state.id = state_id and state.provider = 'linkedin_oidc'
          and state.code_verifier is not null and state.expires_at > now()
        returning state.code_verifier;
end;
$$;
revoke all on function public.consume_hosted_oauth_state(uuid) from PUBLIC;
grant execute on function public.consume_hosted_oauth_state(uuid) to anon, authenticated;

-- Anonymous access must never read/write CV metadata or private-cvs objects.
