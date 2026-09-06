-- Stocul in aplicatia de service: nomenclator, miscari, bonuri de consum.
--
-- Pana acum fisa stia doar o suma pe "cost_piese", scrisa de mana, iar piesele
-- nu erau legate de nimic. De aici incolo piesa de pe fisa arata spre un articol
-- din stoc, asa ca la deschiderea fisei se vede daca piesa e in casa sau trebuie
-- comandata, iar cand se monteaza pleaca din stoc printr-un bon de consum.
--
-- Doua feluri de articole, cu drumuri diferite:
--   marfa       - se vinde separat de reparatie (huse, folii, cabluri)
--   consumabil  - se foloseste in reparatii si iese pe bon de consum
-- Sumele sunt numerice, in lei, fara TVA - ca peste tot in aplicatia de service.

-- ------------------------------------------------------------ nomenclator
create table if not exists public.articole (
  id              uuid primary key default gen_random_uuid(),
  cod             text not null unique,
  denumire        text not null,
  um              text not null default 'buc',
  tip             text not null default 'consumabil'
                    check (tip in ('marfa', 'consumabil')),
  categorie       text not null default 'Altele',
  gestiune        text not null default 'Consumabile Service',
  stoc            numeric(12,3) not null default 0 check (stoc >= 0),
  cost            numeric(12,2) not null default 0 check (cost >= 0),
  pret            numeric(12,2) not null default 0 check (pret >= 0),
  -- Firma nu e platitoare de TVA, de aceea cota porneste de la zero; campul
  -- exista pentru ziua in care asta se schimba.
  cota_tva        integer not null default 0,
  prag            numeric(12,3) not null default 0,
  activ           boolean not null default true,
  note            text,
  -- carligele pentru importul din Oblio
  oblio_cod       text,
  oblio_gestiune  text,
  sincronizat_la  timestamptz,
  creat_la        timestamptz not null default now(),
  actualizat_la   timestamptz not null default now()
);

create index if not exists articole_tip_idx on public.articole (tip) where activ;
create index if not exists articole_categorie_idx on public.articole (categorie);
create index if not exists articole_denumire_idx on public.articole (upper(denumire));

create or replace function public.articole_before_update()
returns trigger language plpgsql set search_path = public as $$
begin
  new.actualizat_la := now();
  return new;
end $$;

drop trigger if exists articole_touch on public.articole;
create trigger articole_touch before update on public.articole
  for each row execute function public.articole_before_update();

-- ------------------------------------------------------- miscari de stoc
-- Fiecare schimbare de stoc lasa un rand aici. Cantitatea e semnata: intrarile
-- pozitiv, iesirile negativ, asa ca suma coloanei trebuie sa dea stocul curent.
create table if not exists public.stoc_miscari (
  id           uuid primary key default gen_random_uuid(),
  articol_id   uuid not null references public.articole(id) on delete restrict,
  data         timestamptz not null default now(),
  tip          text not null check (tip in ('intrare', 'iesire', 'corectie')),
  cantitate    numeric(12,3) not null,
  cost_unitar  numeric(12,2) not null default 0,
  valoare      numeric(12,2) not null default 0,
  stoc_dupa    numeric(12,3) not null default 0,
  document     text,
  bon_id       uuid,
  fisa_id      uuid references public.fise(id) on delete set null,
  motiv        text,
  creat_de     uuid references public.profiluri(id)
);

create index if not exists stoc_miscari_articol_idx on public.stoc_miscari (articol_id, data desc);
create index if not exists stoc_miscari_bon_idx on public.stoc_miscari (bon_id);
create index if not exists stoc_miscari_fisa_idx on public.stoc_miscari (fisa_id);

-- --------------------------------------------------------- bonuri de consum
-- Bonul e documentul cu care piesele ies din stoc. Se opereaza mai departe
-- manual in Oblio, de aceea are stare proprie si loc pentru referinta de acolo.
create sequence if not exists public.bonuri_numar_seq;

create table if not exists public.bonuri_consum (
  id           uuid primary key default gen_random_uuid(),
  numar        text unique,
  data         date not null default current_date,
  fisa_id      uuid references public.fise(id) on delete set null,
  centru_cost  text not null default 'Service',
  motiv        text,
  valoare      numeric(12,2) not null default 0,
  status       text not null default 'emis'
                 check (status in ('emis', 'preluat_oblio', 'anulat')),
  oblio_ref    text,
  preluat_la   timestamptz,
  note         text,
  creat_la     timestamptz not null default now(),
  creat_de     uuid references public.profiluri(id)
);

create index if not exists bonuri_consum_fisa_idx on public.bonuri_consum (fisa_id);
create index if not exists bonuri_consum_status_idx on public.bonuri_consum (status, data desc);

create table if not exists public.bon_linii (
  id           uuid primary key default gen_random_uuid(),
  bon_id       uuid not null references public.bonuri_consum(id) on delete cascade,
  articol_id   uuid references public.articole(id) on delete restrict,
  piesa_id     uuid,
  cod          text,
  denumire     text not null,
  um           text not null default 'buc',
  cantitate    numeric(12,3) not null,
  cost_unitar  numeric(12,2) not null default 0,
  valoare      numeric(12,2) not null default 0
);

create index if not exists bon_linii_bon_idx on public.bon_linii (bon_id);

alter table public.stoc_miscari
  drop constraint if exists stoc_miscari_bon_id_fkey;
alter table public.stoc_miscari
  add constraint stoc_miscari_bon_id_fkey
  foreign key (bon_id) references public.bonuri_consum(id) on delete set null;

create or replace function public.bonuri_before_insert()
returns trigger language plpgsql set search_path = public as $$
begin
  if new.numar is null then
    new.numar := coalesce((select serie_bon from public.setari where id = 1), 'BC') || '-' ||
                 to_char(coalesce(new.data, current_date), 'YYYY') || '-' ||
                 lpad(nextval('public.bonuri_numar_seq')::text, 4, '0');
  end if;
  return new;
end $$;

drop trigger if exists bonuri_numerotare on public.bonuri_consum;
create trigger bonuri_numerotare before insert on public.bonuri_consum
  for each row execute function public.bonuri_before_insert();

-- ------------------------------------------------- piesele de pe fisa, legate
alter table public.piese add column if not exists articol_id uuid references public.articole(id);
alter table public.piese add column if not exists um text not null default 'buc';
alter table public.piese add column if not exists bon_id uuid references public.bonuri_consum(id) on delete set null;
alter table public.piese add column if not exists consumat_la timestamptz;

-- Cantitatile fractionare exista (folie la metru), asa ca piesa tine acelasi
-- tip de numar ca stocul.
alter table public.piese alter column cantitate type numeric(12,3);

-- Piesa care e in casa si tinuta pentru fisa asta e 'rezervata'; cea care
-- trebuie adusa merge mai departe pe drumul de_comandat -> comandata -> sosita.
alter table public.piese drop constraint if exists piese_status_check;
alter table public.piese add constraint piese_status_check
  check (status in ('rezervata', 'de_comandat', 'comandata', 'sosita', 'montata', 'anulata'));

create index if not exists piese_articol_idx on public.piese (articol_id);
create index if not exists piese_status_idx on public.piese (status);
create index if not exists piese_bon_idx on public.piese (bon_id);

-- ------------------------------------------------------------------ setari
alter table public.setari add column if not exists serie_bon text not null default 'BC';
alter table public.setari add column if not exists centru_cost_implicit text not null default 'Service';
alter table public.setari add column if not exists gestiune_implicita text not null default 'Consumabile Service';

-- --------------------------------------------------------------------- RLS
alter table public.articole enable row level security;
alter table public.stoc_miscari enable row level security;
alter table public.bonuri_consum enable row level security;
alter table public.bon_linii enable row level security;

do $$
declare t text;
begin
  foreach t in array array['articole', 'stoc_miscari', 'bonuri_consum', 'bon_linii'] loop
    execute format('drop policy if exists personal_select on public.%I', t);
    execute format('drop policy if exists personal_insert on public.%I', t);
    execute format('drop policy if exists personal_update on public.%I', t);
    execute format('drop policy if exists personal_delete on public.%I', t);
    execute format('create policy personal_select on public.%I for select to authenticated using (true)', t);
    execute format('create policy personal_insert on public.%I for insert to authenticated with check (true)', t);
    execute format('create policy personal_update on public.%I for update to authenticated using (true) with check (true)', t);
    execute format('create policy personal_delete on public.%I for delete to authenticated using (true)', t);
  end loop;
end $$;

revoke all on public.articole from anon;
revoke all on public.stoc_miscari from anon;
revoke all on public.bonuri_consum from anon;
revoke all on public.bon_linii from anon;

-- ------------------------------------------------------------------ vederi
-- Stocul asa cum il vezi cand deschizi o fisa: ce ai pe raft, cat e deja promis
-- altor fise deschise si ce ramane cu adevarat disponibil.
create or replace view public.v_stoc
with (security_invoker = true) as
select a.id, a.cod, a.denumire, a.um, a.tip, a.categorie, a.gestiune,
       a.stoc, a.cost, a.pret, a.prag, a.activ,
       coalesce(r.rezervat, 0)::numeric(12,3) as rezervat,
       (a.stoc - coalesce(r.rezervat, 0))::numeric(12,3) as disponibil,
       round(a.stoc * a.cost, 2) as valoare,
       (a.prag > 0 and a.stoc <= a.prag) as sub_prag
from public.articole a
left join (
  select p.articol_id, sum(p.cantitate) as rezervat
  from public.piese p
  join public.fise f on f.id = p.fisa_id
  where p.articol_id is not null
    and p.status = 'rezervata'
    and f.status not in ('predat', 'nereparabil')
  group by p.articol_id
) r on r.articol_id = a.id;

-- Ce trebuie comandat, adunat pe articol peste toate fisele deschise.
create or replace view public.v_piese_de_comandat
with (security_invoker = true) as
select a.id as articol_id,
       coalesce(a.cod, '-') as cod,
       coalesce(a.denumire, p.denumire) as denumire,
       coalesce(a.um, p.um) as um,
       sum(p.cantitate)::numeric(12,3) as cantitate_ceruta,
       coalesce(max(s.disponibil), 0)::numeric(12,3) as disponibil,
       greatest(sum(p.cantitate) - coalesce(max(s.disponibil), 0), 0)::numeric(12,3) as de_comandat,
       count(distinct p.fisa_id) as fise,
       string_agg(distinct f.numar, ', ') as numere_fise,
       min(p.creat_la) as cerut_din
from public.piese p
join public.fise f on f.id = p.fisa_id
left join public.articole a on a.id = p.articol_id
left join public.v_stoc s on s.id = a.id
where p.status in ('de_comandat', 'comandata')
  and f.status not in ('predat', 'nereparabil')
group by a.id, a.cod, a.um, coalesce(a.denumire, p.denumire), coalesce(a.um, p.um);

-- Cum sta fiecare fisa cu piesele ei.
create or replace view public.v_fise_piese
with (security_invoker = true) as
select f.id as fisa_id, f.numar, f.status,
       count(p.id) as linii,
       count(*) filter (where p.status = 'rezervata') as rezervate,
       count(*) filter (where p.status in ('de_comandat', 'comandata')) as de_comandat,
       count(*) filter (where p.status = 'sosita') as sosite,
       count(*) filter (where p.status = 'montata') as montate,
       coalesce(sum(p.cantitate * p.cost_achizitie)
                filter (where p.status = 'montata'), 0)::numeric(12,2) as cost_consumat,
       coalesce(sum(p.cantitate * p.pret_client)
                filter (where p.status <> 'anulata'), 0)::numeric(12,2) as valoare_client
from public.fise f
left join public.piese p on p.fisa_id = f.id
group by f.id, f.numar, f.status;

-- Bonurile care asteapta sa fie trecute manual in Oblio.
create or replace view public.v_bonuri_de_operat
with (security_invoker = true) as
select b.id, b.numar, b.data, b.centru_cost, b.motiv, b.valoare, b.status,
       f.numar as fisa, count(l.id) as linii
from public.bonuri_consum b
left join public.fise f on f.id = b.fisa_id
left join public.bon_linii l on l.bon_id = b.id
where b.status = 'emis'
group by b.id, b.numar, b.data, b.centru_cost, b.motiv, b.valoare, b.status, f.numar;

-- Marfa ajunsa pe fise: nu intra pe bon de consum, se factureaza separat.
create or replace view public.v_marfa_pe_fise
with (security_invoker = true) as
select f.id as fisa_id, f.numar as fisa, f.status as stare_fisa,
       a.cod, a.denumire, p.cantitate, p.pret_client,
       round(p.cantitate * p.pret_client, 2) as valoare,
       p.status as stare_piesa
from public.piese p
join public.fise f on f.id = p.fisa_id
join public.articole a on a.id = p.articol_id
where a.tip = 'marfa' and p.status <> 'anulata';

grant select on public.v_stoc, public.v_piese_de_comandat, public.v_fise_piese,
                public.v_bonuri_de_operat, public.v_marfa_pe_fise to authenticated;
revoke all on public.v_stoc, public.v_piese_de_comandat, public.v_fise_piese,
              public.v_bonuri_de_operat, public.v_marfa_pe_fise from anon;
