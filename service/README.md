# Stocul in aplicatia de service

Aplicatia de service (Supabase, proiectul `gestiune-service`) tine de acum si stocul:
nomenclatorul de articole, miscarile lor si bonurile de consum cu care piesele ies din
gestiune. Fisa de reparatie nu mai are doar o suma scrisa de mana pe „piese" — are linii
care arata spre articole reale, asa ca la primirea aparatului se vede pe loc daca piesa e
in casa sau trebuie comandata.

Aici e sursa de adevar pentru stoc. Platforma Gestio (`platforma/`) ramane locul unde se
vede firma intreaga; stocul de acolo e o copie preluata din baza asta, nu invers.

## Cele doua feluri de articole

| Tip | Ce e | Cum iese din stoc |
| --- | --- | --- |
| `marfa` | huse, folii, cabluri, incarcatoare — se vand la tejghea | se vinde separat de reparatie, pe factura sau bon fiscal |
| `consumabil` | ecrane, acumulatori, conectori, flux — se monteaza in aparat | pe **bon de consum**, legat de fisa |

Distinctia nu e cosmetica: marfa pusa din greseala pe o fisa nu intra pe bonul de consum,
iar `genereaza_bon_consum` spune limpede ca a gasit-o si a lasat-o deoparte. Ce ramane de
facturat separat se vede in `v_marfa_pe_fise`.

## Drumul unei piese

```
                   ai pe stoc?
                    /        \
                  da          nu
                  |            |
             rezervata    de_comandat -> comandata -> sosita
                  \            /
                   \          /
                  genereaza_bon_consum()
                          |
                       montata          stocul scade, bonul asteapta Oblio
```

**Rezervarea nu scade stocul.** Cat timp piesa e `rezervata`, cantitatea ramane pe raft
dar nu mai e disponibila pentru alta fisa — `v_stoc` arata separat `stoc`, `rezervat` si
`disponibil`. Stocul scade abia la bon, cand piesa chiar pleaca in aparat.

Cand adaugi o piesa care nu ajunge, fisa trece singura in `de_comandat_piese` (doar daca
era in `de_reparat` sau `in_lucru` — o fisa reparata nu se intoarce).

## Ce apeleaza interfata

Toate sunt functii RPC, apelabile doar de utilizatori autentificati.

**La deschiderea fisei — am sau comand?**

```js
const { data } = await supabase.rpc('cauta_articole', {
  p_text: 'ecran a15', p_tip: 'consumabil', p_limita: 20
})
// -> [{ id, cod, denumire, um, stoc, disponibil, cost, pret, in_casa }]
```

Cuvintele se cauta separat si in orice ordine, deci „ecran a15" gaseste si
„Ecran Samsung A155/A156 Galaxy A15 4G". `in_casa` e raspunsul scurt la intrebare.

**Pun piesa pe fisa** (statusul il decide functia, dupa disponibil):

```js
await supabase.rpc('adauga_piesa', {
  p_fisa_id: fisa.id, p_articol_id: articol.id, p_cantitate: 1,
  p_pret_client: 250          // optional; fara el ia pretul din nomenclator
})
```

Pentru o piesa care nu e in nomenclator, dai `p_denumire` in loc de `p_articol_id`: intra
direct ca `de_comandat`, pentru ca n-ai de unde sti ca o ai.

**Scot piesele din stoc, pe bon:**

```js
const { data: bon } = await supabase.rpc('genereaza_bon_consum', { p_fisa_id: fisa.id })
// -> { numar: 'BC-2026-0001', data, valoare, status: 'emis', ... }
```

Bonul ia toate consumabilele `rezervata` sau `sosita` de pe fisa, le scade din stoc, scrie
miscarile si trece piesele pe `montata`. Daca o linie n-are stoc, nu se scade nici una —
operatiunea e intreaga sau deloc.

**Dupa ce l-am trecut in Oblio:**

```js
await supabase.rpc('marcheaza_bon_preluat', { p_bon_id: bon.id, p_oblio_ref: 'BC 142' })
```

`v_bonuri_de_operat` arata exact bonurile care asteapta sa fie operate — lista de lucru
din Oblio, in ordine.

**Daca bonul a fost gresit:** `anuleaza_bon(p_bon_id, p_motiv)` pune stocul la loc, scrie
miscarile de intrare si intoarce piesele pe `rezervata`. Nu se sterge nimic.

**Intrari si corectii:**

| Apel | Cand |
| --- | --- |
| `receptie_articol(articol, cantitate, cost_unitar)` | marfa venita de la furnizor; recalculeaza costul mediu ponderat |
| `corectie_stoc(articol, stoc_real, motiv)` | dupa inventar — spui cat ai numarat, nu cu cat sa se schimbe |
| `sincronizeaza_cost_piese(fisa)` | trece pe fisa suma pieselor (cantitate x pret client) |

`sincronizeaza_cost_piese` nu se cheama singura. `fise.cost_piese` e ce plateste clientul,
iar fisele vechi au sume scrise de mana pe care nimeni nu trebuie sa le rescrie pe
nesimtite; daca liniile n-au pret de client si fisa are deja o suma, functia refuza si
spune de ce (`p_forteaza => true` daca chiar vrei zero).

## Vederi

| Vedere | Ce arata |
| --- | --- |
| `v_stoc` | fiecare articol cu `stoc`, `rezervat`, `disponibil`, valoare si semnalul `sub_prag` |
| `v_piese_de_comandat` | ce trebuie adus, adunat pe articol peste toate fisele deschise, cu numerele fiselor care il asteapta |
| `v_fise_piese` | cum sta fiecare fisa: linii rezervate, de comandat, montate, cost consumat, valoare catre client |
| `v_bonuri_de_operat` | bonurile emise si neoperate inca in Oblio |
| `v_marfa_pe_fise` | marfa ajunsa pe fise, de facturat separat |

## Legatura cu Oblio

Bonurile se opereaza deocamdata manual in Oblio; `bonuri_consum` tine minte care au fost
duse acolo (`status`, `oblio_ref`, `preluat_la`), ca sa nu treci de doua ori acelasi bon
sau sa uiti unul.

Pentru citirea automata de mai tarziu, `articole` are `oblio_cod`, `oblio_gestiune` si
`sincronizat_la`, iar functia `upsert_articol_oblio` face toata treaba dintr-un apel:
creeaza articolul daca lipseste, ii actualizeaza datele, iar daca stocul din Oblio difera
de cel de aici scrie o **corectie** cu motivul `Sincronizare Oblio` — asa ramane vizibil
de ce s-a schimbat cantitatea, in loc sa se suprascrie tacut.

```js
await supabase.rpc('upsert_articol_oblio', {
  p_cod: 'C239', p_denumire: '...', p_um: 'buc', p_tip: 'consumabil',
  p_gestiune: 'Consumabile Service', p_stoc: 2, p_cost: 185.00
})
```

## Migratiile

Se aplica in ordinea numelui, o singura data; toate sunt scrise ca sa poata fi rulate din
nou fara sa strice ceva.

| Fisier | Ce face |
| --- | --- |
| `migrations/20260906120000_stoc.sql` | tabelele `articole`, `stoc_miscari`, `bonuri_consum`, `bon_linii`, coloanele noi pe `piese` si `setari`, RLS-ul si vederile |
| `migrations/20260906120100_functii.sql` | functiile RPC de mai sus |

Stocul de pornire — 384 articole, 889 bucati, 42.214,24 lei la cost — a fost incarcat separat,
preluat din platforma Gestio. Nu e tinut in acest depozit: sunt denumirile si **costurile de
achizitie** ale firmei, iar depozitul e public. Datele stau in baza de service si in istoricul
ei de migratii, unde le vede doar cine are acces la proiect.

Politicile RLS urmeaza conventia din restul bazei: `personal_select / insert / update /
delete` pentru rolul `authenticated`, iar `anon` n-are acces la nimic din stoc. Functiile
ruleaza cu drepturile celui care le cheama, nu ale proprietarului, deci RLS se aplica si
prin ele.

## Ce nu face

- Nu tine preturi de vanzare pentru consumabile — pretul catre client se pune pe linia de
  pe fisa, unde depinde de reparatie.
- Nu emite facturi si nu atinge casa de marcat; marfa vanduta se factureaza in Oblio.
- Nu comanda singura piesele: `v_piese_de_comandat` iti spune ce lipseste, comanda o dai
  tu si o treci pe piesa (`comandata`, `nr_comanda`, `data_comanda`).
- Nu are inca ecrane in aplicatia de service — partea de interfata se scrie peste
  functiile de aici.
