-- Operatiunile de stoc, ca functii apelabile din aplicatie (supabase.rpc).
--
-- Tot ce misca stocul trece pe aici, ca sa nu ramana niciodata o cantitate
-- schimbata fara miscarea care o explica. Fiecare functie e o singura
-- tranzactie: daca o linie nu are stoc, nu se scade nici una.

-- ------------------------------------------------- cauta ce ai in nomenclator
-- Cautarea de la deschiderea fisei: scrii "ecran a34" si vezi ce ai si cat.
create or replace function public.cauta_articole(
  p_text   text default null,
  p_tip    text default null,
  p_limita integer default 20
)
returns table (
  id uuid, cod text, denumire text, um text, tip text, categorie text,
  stoc numeric, disponibil numeric, cost numeric, pret numeric, in_casa boolean
)
language sql stable
set search_path = public
as $$
  select s.id, s.cod, s.denumire, s.um, s.tip, s.categorie,
         s.stoc, s.disponibil, s.cost, s.pret, s.disponibil > 0
  from public.v_stoc s
  where s.activ
    and (p_tip is null or s.tip = p_tip)
    -- Cuvintele se cauta separat si in orice ordine: "ecran a15" gaseste si
    -- "Ecran Samsung A155/A156 Galaxy A15", care altfel n-ar iesi niciodata.
    and (
      p_text is null or btrim(p_text) = ''
      or (select bool_and(s.cod || ' ' || s.denumire ilike '%' || cuvant || '%')
          from unnest(regexp_split_to_array(btrim(p_text), '\s+')) as cuvant)
    )
  order by (s.disponibil > 0) desc, s.denumire
  limit greatest(1, least(coalesce(p_limita, 20), 200));
$$;

-- ----------------------------------------------------- pune o piesa pe fisa
-- Aici se raspunde la intrebarea "am sau comand?": daca articolul are
-- disponibil cat ceri, piesa ramane rezervata pentru fisa; daca nu, pleaca pe
-- drumul de comanda si fisa trece in "de comandat piese".
create or replace function public.adauga_piesa(
  p_fisa_id     uuid,
  p_articol_id  uuid default null,
  p_cantitate   numeric default 1,
  p_denumire    text default null,
  p_pret_client numeric default null,
  p_furnizor    text default null,
  p_note        text default null
)
returns public.piese
language plpgsql
set search_path = public
as $$
declare
  v_articol    public.articole;
  v_disponibil numeric := 0;
  v_fisa       public.fise;
  v_piesa      public.piese;
  v_status     text;
  v_denumire   text;
  v_pret       numeric := coalesce(p_pret_client, 0);
begin
  if p_cantitate is null or p_cantitate <= 0 then
    raise exception 'Cantitatea trebuie sa fie mai mare ca zero.';
  end if;

  select * into v_fisa from public.fise where id = p_fisa_id;
  if not found then
    raise exception 'Fisa % nu exista.', p_fisa_id;
  end if;

  if p_articol_id is not null then
    select * into v_articol from public.articole where id = p_articol_id;
    if not found then
      raise exception 'Articolul % nu exista in nomenclator.', p_articol_id;
    end if;
    select s.disponibil into v_disponibil from public.v_stoc s where s.id = p_articol_id;
    v_denumire := coalesce(nullif(btrim(p_denumire), ''), v_articol.denumire);
    if p_pret_client is null then
      v_pret := v_articol.pret;
    end if;
    v_status := case when coalesce(v_disponibil, 0) >= p_cantitate
                     then 'rezervata' else 'de_comandat' end;
  else
    -- Piesa scrisa de mana, fara articol in nomenclator: n-ai de unde sti ca o
    -- ai, deci se comanda.
    if nullif(btrim(coalesce(p_denumire, '')), '') is null then
      raise exception 'O piesa fara articol de stoc are nevoie de denumire.';
    end if;
    v_denumire := btrim(p_denumire);
    v_status := 'de_comandat';
  end if;

  insert into public.piese (fisa_id, articol_id, denumire, cod_piesa, um, cantitate,
                            cost_achizitie, pret_client, furnizor, status, note)
  values (p_fisa_id, p_articol_id, v_denumire, v_articol.cod,
          coalesce(v_articol.um, 'buc'), p_cantitate,
          coalesce(v_articol.cost, 0), v_pret, p_furnizor, v_status, p_note)
  returning * into v_piesa;

  -- Fisa abia primita care asteapta o piesa isi spune asta singura.
  if v_status = 'de_comandat' and v_fisa.status in ('de_reparat', 'in_lucru') then
    update public.fise set status = 'de_comandat_piese' where id = p_fisa_id;
  end if;

  return v_piesa;
end $$;

-- ------------------------------------------------------ bonul de consum
-- Scoate din stoc consumabilele tinute pentru fisa si le pune pe un bon.
-- Marfa nu intra aici: se vinde separat de reparatie.
create or replace function public.genereaza_bon_consum(
  p_fisa_id     uuid,
  p_data        date default current_date,
  p_motiv       text default null,
  p_centru_cost text default null
)
returns public.bonuri_consum
language plpgsql
set search_path = public
as $$
declare
  v_fisa    public.fise;
  v_bon     public.bonuri_consum;
  v_linie   record;
  v_valoare numeric(12,2) := 0;
  v_val     numeric(12,2);
  v_stoc    numeric(12,3);
  v_marfa   integer;
begin
  select * into v_fisa from public.fise where id = p_fisa_id;
  if not found then
    raise exception 'Fisa % nu exista.', p_fisa_id;
  end if;

  select count(*) into v_marfa
  from public.piese p
  join public.articole a on a.id = p.articol_id
  where p.fisa_id = p_fisa_id
    and p.status in ('rezervata', 'sosita')
    and a.tip = 'marfa';

  if not exists (
    select 1 from public.piese p
    join public.articole a on a.id = p.articol_id
    where p.fisa_id = p_fisa_id
      and p.status in ('rezervata', 'sosita')
      and a.tip = 'consumabil'
  ) then
    raise exception 'Fisa % nu are consumabile de dat in consum.%', v_fisa.numar,
      case when v_marfa > 0
           then format(' Are %s linii de marfa, care se vand separat de reparatie.', v_marfa)
           else '' end;
  end if;

  insert into public.bonuri_consum (data, fisa_id, centru_cost, motiv, creat_de)
  values (coalesce(p_data, current_date), p_fisa_id,
          coalesce(nullif(btrim(coalesce(p_centru_cost, '')), ''),
                   (select centru_cost_implicit from public.setari where id = 1),
                   'Service'),
          coalesce(nullif(btrim(coalesce(p_motiv, '')), ''),
                   'Piese montate pe fisa ' || coalesce(v_fisa.numar, '')),
          auth.uid())
  returning * into v_bon;

  for v_linie in
    select p.id, p.cantitate, p.articol_id,
           a.cod, a.denumire, a.um, a.cost, a.stoc
    from public.piese p
    join public.articole a on a.id = p.articol_id
    where p.fisa_id = p_fisa_id
      and p.status in ('rezervata', 'sosita')
      and a.tip = 'consumabil'
    order by a.cod
    for no key update of a
  loop
    if v_linie.stoc < v_linie.cantitate then
      raise exception 'Stoc insuficient pentru % (%): ai %, ceri %.',
        v_linie.denumire, v_linie.cod, v_linie.stoc, v_linie.cantitate;
    end if;

    v_val := round(v_linie.cantitate * v_linie.cost, 2);
    v_valoare := v_valoare + v_val;

    update public.articole
       set stoc = stoc - v_linie.cantitate
     where id = v_linie.articol_id
    returning stoc into v_stoc;

    insert into public.bon_linii (bon_id, articol_id, piesa_id, cod, denumire, um,
                                  cantitate, cost_unitar, valoare)
    values (v_bon.id, v_linie.articol_id, v_linie.id, v_linie.cod, v_linie.denumire,
            v_linie.um, v_linie.cantitate, v_linie.cost, v_val);

    insert into public.stoc_miscari (articol_id, tip, cantitate, cost_unitar, valoare,
                                     stoc_dupa, document, bon_id, fisa_id, motiv, creat_de)
    values (v_linie.articol_id, 'iesire', -v_linie.cantitate, v_linie.cost, v_val,
            v_stoc, 'bon', v_bon.id, p_fisa_id,
            'Bon ' || v_bon.numar || ' - fisa ' || coalesce(v_fisa.numar, ''), auth.uid());

    update public.piese
       set status = 'montata',
           bon_id = v_bon.id,
           consumat_la = now(),
           cost_achizitie = v_linie.cost
     where id = v_linie.id;
  end loop;

  update public.bonuri_consum set valoare = v_valoare where id = v_bon.id
  returning * into v_bon;

  return v_bon;
end $$;

-- Bonul gresit se storneaza intreg: piesele se intorc rezervate, stocul creste
-- la loc si miscarile de intrare raman ca urma.
create or replace function public.anuleaza_bon(p_bon_id uuid, p_motiv text default null)
returns public.bonuri_consum
language plpgsql
set search_path = public
as $$
declare
  v_bon   public.bonuri_consum;
  v_linie record;
  v_stoc  numeric(12,3);
begin
  select * into v_bon from public.bonuri_consum where id = p_bon_id for update;
  if not found then
    raise exception 'Bonul % nu exista.', p_bon_id;
  end if;
  if v_bon.status = 'anulat' then
    raise exception 'Bonul % e deja anulat.', v_bon.numar;
  end if;

  for v_linie in
    select l.id, l.articol_id, l.cantitate, l.cost_unitar, l.valoare, l.piesa_id
    from public.bon_linii l
    where l.bon_id = p_bon_id and l.articol_id is not null
  loop
    update public.articole
       set stoc = stoc + v_linie.cantitate
     where id = v_linie.articol_id
    returning stoc into v_stoc;

    insert into public.stoc_miscari (articol_id, tip, cantitate, cost_unitar, valoare,
                                     stoc_dupa, document, bon_id, fisa_id, motiv, creat_de)
    values (v_linie.articol_id, 'intrare', v_linie.cantitate, v_linie.cost_unitar,
            v_linie.valoare, v_stoc, 'stornare', p_bon_id, v_bon.fisa_id,
            coalesce(nullif(btrim(coalesce(p_motiv, '')), ''),
                     'Stornare bon ' || coalesce(v_bon.numar, '')), auth.uid());

    if v_linie.piesa_id is not null then
      update public.piese
         set status = 'rezervata', bon_id = null, consumat_la = null
       where id = v_linie.piesa_id;
    end if;
  end loop;

  update public.bonuri_consum
     set status = 'anulat',
         note = coalesce(nullif(btrim(coalesce(p_motiv, '')), ''), note)
   where id = p_bon_id
  returning * into v_bon;

  return v_bon;
end $$;

-- Bifa pusa dupa ce bonul a fost trecut de mana in Oblio.
create or replace function public.marcheaza_bon_preluat(
  p_bon_id uuid,
  p_oblio_ref text default null
)
returns public.bonuri_consum
language plpgsql
set search_path = public
as $$
declare v_bon public.bonuri_consum;
begin
  update public.bonuri_consum
     set status = 'preluat_oblio',
         oblio_ref = coalesce(nullif(btrim(coalesce(p_oblio_ref, '')), ''), oblio_ref),
         preluat_la = now()
   where id = p_bon_id and status <> 'anulat'
  returning * into v_bon;

  if not found then
    raise exception 'Bonul % nu exista sau e anulat.', p_bon_id;
  end if;
  return v_bon;
end $$;

-- --------------------------------------------------------- intrari in stoc
-- Receptia recalculeaza costul mediu ponderat: valoarea veche plus cea noua,
-- impartite la stocul rezultat.
create or replace function public.receptie_articol(
  p_articol_id  uuid,
  p_cantitate   numeric,
  p_cost_unitar numeric,
  p_document    text default 'receptie',
  p_motiv       text default null
)
returns public.articole
language plpgsql
set search_path = public
as $$
declare
  v_articol public.articole;
  v_stoc    numeric(12,3);
  v_cost    numeric(12,2);
begin
  if p_cantitate is null or p_cantitate <= 0 then
    raise exception 'Cantitatea receptionata trebuie sa fie mai mare ca zero.';
  end if;
  if p_cost_unitar is null or p_cost_unitar < 0 then
    raise exception 'Costul unitar nu poate lipsi si nu poate fi negativ.';
  end if;

  select * into v_articol from public.articole where id = p_articol_id for update;
  if not found then
    raise exception 'Articolul % nu exista in nomenclator.', p_articol_id;
  end if;

  v_stoc := v_articol.stoc + p_cantitate;
  v_cost := case when v_stoc > 0
                 then round((v_articol.stoc * v_articol.cost + p_cantitate * p_cost_unitar) / v_stoc, 2)
                 else p_cost_unitar end;

  update public.articole set stoc = v_stoc, cost = v_cost where id = p_articol_id
  returning * into v_articol;

  insert into public.stoc_miscari (articol_id, tip, cantitate, cost_unitar, valoare,
                                   stoc_dupa, document, motiv, creat_de)
  values (p_articol_id, 'intrare', p_cantitate, p_cost_unitar,
          round(p_cantitate * p_cost_unitar, 2), v_stoc, p_document, p_motiv, auth.uid());

  return v_articol;
end $$;

-- Corectia de dupa inventar: spui cat ai numarat, nu cu cat sa se schimbe.
create or replace function public.corectie_stoc(
  p_articol_id uuid,
  p_stoc_real  numeric,
  p_motiv      text default 'inventar'
)
returns public.articole
language plpgsql
set search_path = public
as $$
declare
  v_articol public.articole;
  v_diferenta numeric(12,3);
begin
  if p_stoc_real is null or p_stoc_real < 0 then
    raise exception 'Stocul numarat nu poate lipsi si nu poate fi negativ.';
  end if;

  select * into v_articol from public.articole where id = p_articol_id for update;
  if not found then
    raise exception 'Articolul % nu exista in nomenclator.', p_articol_id;
  end if;

  v_diferenta := p_stoc_real - v_articol.stoc;
  if v_diferenta = 0 then
    return v_articol;
  end if;

  update public.articole set stoc = p_stoc_real where id = p_articol_id
  returning * into v_articol;

  insert into public.stoc_miscari (articol_id, tip, cantitate, cost_unitar, valoare,
                                   stoc_dupa, document, motiv, creat_de)
  values (p_articol_id, 'corectie', v_diferenta, v_articol.cost,
          round(v_diferenta * v_articol.cost, 2), p_stoc_real, 'inventar',
          p_motiv, auth.uid());

  return v_articol;
end $$;

-- ------------------------------------------------------- carligul pentru Oblio
-- Un articol asa cum vine din Oblio: se creeaza daca nu exista, iar daca stocul
-- de acolo difera de cel de aici se scrie o corectie, ca sa se vada de ce.
create or replace function public.upsert_articol_oblio(
  p_cod       text,
  p_denumire  text default null,
  p_um        text default null,
  p_tip       text default null,
  p_gestiune  text default null,
  p_categorie text default null,
  p_stoc      numeric default null,
  p_cost      numeric default null,
  p_pret      numeric default null,
  p_oblio_cod text default null
)
returns public.articole
language plpgsql
set search_path = public
as $$
declare
  v_articol public.articole;
  v_cod     text := btrim(coalesce(p_cod, ''));
begin
  if v_cod = '' then
    raise exception 'Codul articolului e obligatoriu.';
  end if;
  if p_tip is not null and p_tip not in ('marfa', 'consumabil') then
    raise exception 'Tipul poate fi doar marfa sau consumabil, nu %.', p_tip;
  end if;

  select * into v_articol from public.articole where cod = v_cod for update;

  if not found then
    insert into public.articole (cod, denumire, um, tip, gestiune, categorie,
                                 cost, pret, oblio_cod, sincronizat_la)
    values (v_cod, coalesce(nullif(btrim(coalesce(p_denumire, '')), ''), v_cod),
            coalesce(p_um, 'buc'), coalesce(p_tip, 'consumabil'),
            coalesce(p_gestiune, (select gestiune_implicita from public.setari where id = 1),
                     'Consumabile Service'),
            coalesce(p_categorie, 'Altele'), coalesce(p_cost, 0), coalesce(p_pret, 0),
            nullif(btrim(coalesce(p_oblio_cod, '')), ''), now())
    returning * into v_articol;
  else
    update public.articole
       set denumire = coalesce(nullif(btrim(coalesce(p_denumire, '')), ''), denumire),
           um = coalesce(p_um, um),
           tip = coalesce(p_tip, tip),
           gestiune = coalesce(p_gestiune, gestiune),
           categorie = coalesce(p_categorie, categorie),
           cost = coalesce(p_cost, cost),
           pret = coalesce(p_pret, pret),
           oblio_cod = coalesce(nullif(btrim(coalesce(p_oblio_cod, '')), ''), oblio_cod),
           sincronizat_la = now()
     where id = v_articol.id
    returning * into v_articol;
  end if;

  if p_stoc is not null and p_stoc <> v_articol.stoc then
    v_articol := public.corectie_stoc(v_articol.id, p_stoc, 'Sincronizare Oblio');
    update public.articole set sincronizat_la = now() where id = v_articol.id
    returning * into v_articol;
  end if;

  return v_articol;
end $$;

-- ------------------------------------------- valoarea pieselor trecuta pe fisa
-- Nu se face singura: cat ii ceri clientului pe piese ramane decizia ta, iar
-- fisele vechi au sume scrise de mana pe care nimeni nu trebuie sa le rescrie
-- pe nesimtite. Cand vrei ca fisa sa ia suma de pe linii, chemi asta.
create or replace function public.sincronizeaza_cost_piese(
  p_fisa_id   uuid,
  p_forteaza  boolean default false
)
returns numeric
language plpgsql
set search_path = public
as $$
declare
  v_total numeric(12,2);
  v_fisa  public.fise;
begin
  select * into v_fisa from public.fise where id = p_fisa_id;
  if not found then
    raise exception 'Fisa % nu exista.', p_fisa_id;
  end if;

  select coalesce(sum(p.cantitate * p.pret_client), 0)
    into v_total
  from public.piese p
  where p.fisa_id = p_fisa_id and p.status <> 'anulata';

  -- Consumabilele n-au pret de vanzare in nomenclator, deci liniile pornesc de
  -- la zero. Daca fisa are deja o suma trecuta de mana, nu i-o stergem fara sa
  -- fie cerut: intai pui pretul pe linii, sau ceri explicit zero.
  if v_total = 0 and coalesce(v_fisa.cost_piese, 0) > 0 and not p_forteaza then
    raise exception 'Fisa % are % lei pe piese, dar liniile n-au niciun pret de client. '
                    'Pune pretul pe linii sau cheama functia cu p_forteaza => true.',
                    v_fisa.numar, v_fisa.cost_piese;
  end if;

  update public.fise set cost_piese = v_total where id = p_fisa_id;
  return v_total;
end $$;

-- ------------------------------------------------------------------ drepturi
do $$
declare f text;
begin
  foreach f in array array[
    'cauta_articole(text,text,integer)',
    'adauga_piesa(uuid,uuid,numeric,text,numeric,text,text)',
    'genereaza_bon_consum(uuid,date,text,text)',
    'anuleaza_bon(uuid,text)',
    'marcheaza_bon_preluat(uuid,text)',
    'receptie_articol(uuid,numeric,numeric,text,text)',
    'corectie_stoc(uuid,numeric,text)',
    'upsert_articol_oblio(text,text,text,text,text,text,numeric,numeric,numeric,text)',
    'sincronizeaza_cost_piese(uuid,boolean)'
  ] loop
    execute format('revoke all on function public.%s from public, anon', f);
    execute format('grant execute on function public.%s to authenticated', f);
  end loop;
end $$;
