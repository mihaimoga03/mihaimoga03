-- Click-urile pe linkurile de afiliere. Fără IP și fără date personale.
create table if not exists public.clicks (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),
  product       text not null,
  store         text not null,
  country       text not null,
  country_source text,
  referrer      text
);

create index if not exists clicks_created_at_idx on public.clicks (created_at desc);

-- Doar funcția /go scrie, cu cheia service_role; nimeni nu citește din browser.
alter table public.clicks enable row level security;

-- Raportul zilnic: câte click-uri pe produs, magazin și țară
create or replace view public.clicks_pe_zi
with (security_invoker = true) as
select date_trunc('day', created_at)::date as zi, product, store, country, count(*) as clicks
from public.clicks
group by 1, 2, 3, 4
order by 1 desc, clicks desc;
