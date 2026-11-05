-- Employer role submissions (pending -> approved/rejected), reviewed manually.
create table if not exists public.job_submissions (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  company text not null,
  website text not null default '',
  location text not null default '',
  apply_url text not null,
  description text not null default '',
  employment_type text not null default '',
  contact_email text not null default '',
  status text not null default 'pending',   -- pending | approved | rejected
  created_at timestamptz not null default now()
);

alter table public.job_submissions enable row level security;

-- Public (anon) users may insert a submission but cannot read the queue.
create policy "anon insert" on public.job_submissions
  for insert with check (true);
