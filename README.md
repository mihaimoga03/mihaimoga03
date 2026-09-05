# Gestio — agent de contabilitate, clienți și stocuri

Un agent construit peste Claude API care ține evidența unei firme mici: contabilitate
în partidă dublă, fișa clienților și gestiunea stocului. Vorbești cu el în română, el
execută operațiunile prin unelte care scriu într-o bază de date SQLite — nu inventează
cifre și nu „povestește" ce ar face.

```
tu > am primit 200 saci de ciment de la Holcim cu 26 lei bucata, factura HD-5510
  ... receptie_marfa(sku='CIM-42', qty=200.0, unit_cost_ron=26.0, supplier='Holcim...')

Am înregistrat recepția: stoc 480 saci, cost mediu 26,00 RON.
Valoare 5.200,00 RON + TVA 1.092,00 RON = 6.292,00 RON datorie către Holcim.
```

## Ce știe să facă

| Domeniu | Operațiuni |
| --- | --- |
| **Clienți** | adăugare și actualizare, căutare, fișă de client, extras de cont, raport de scadențe (aging) pe intervale de întârziere |
| **Stoc** | nomenclator de produse și servicii, recepții cu recalcularea costului mediu ponderat, ajustări de inventar, istoric de mișcări, raport de reaprovizionare |
| **Facturare** | ciornă → linii → emitere, numerotare pe serie, descărcare de gestiune, încasări totale și parțiale, stornare |
| **Contabilitate** | note în partidă dublă pe planul de conturi românesc, cheltuieli, plăți către furnizori, balanță de verificare, cont de profit și pierdere, decont de TVA, jurnal |

## Instalare

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...        # sau: ant auth login
```

## Utilizare

```bash
gestio seed            # date demonstrative: 3 clienți, 4 produse, 3 facturi
gestio chat            # conversație interactivă
gestio ask "cum stăm?" # o singură întrebare
gestio unelte          # lista uneltelor disponibile
gestio sql "SELECT * FROM invoices"   # doar SELECT, pentru depanare
```

În `chat` ai comenzile `/reset` (șterge conversația, nu datele), `/unelte` și `/ieșire`.

Exemple de cereri care funcționează:

- „adaugă clientul Delta Prod SRL, CUI RO99887766, termen de plată 45 de zile"
- „fă o factură către Alfa Construct cu 50 de saci de ciment și 8 ore de manoperă"
- „cine îmi datorează bani de peste 60 de zile?"
- „ce marjă am avut luna trecută?"
- „am plătit 3.500 lei chirie pe depozit, prin bancă"
- „ce am de plată la TVA pe trimestrul acesta?"

## Cum e construit

```
gestio/
├── agent.py        bucla de conversație peste client.beta.messages.tool_runner
├── config.py       setări din mediu (model, TVA, monedă, serie facturi)
├── db.py           schema SQLite și tranzacțiile
├── money.py        aritmetica în bani, întregi — niciun float în calcule
├── accounting.py   planul de conturi și înregistrarea notelor contabile
├── seed.py         date demonstrative
├── cli.py          interfața de linie de comandă
└── tools/          cele 29 de unelte pe care le apelează modelul
    ├── clients.py     clienți, solduri, scadențe
    ├── inventory.py   produse, recepții, mișcări de stoc
    ├── invoices.py    facturare, încasări, stornare
    └── books.py       cheltuieli, rapoarte, jurnal
```

Modelul folosit este `claude-opus-5`, cu gândire adaptivă și cu *server-side fallback*
activat, ca o cerere refuzată de clasificatoarele de siguranță să fie preluată automat
de un model alternativ în loc să întrerupă conversația. Promptul de sistem este împărțit
în două blocuri, cel stabil fiind marcat pentru *prompt caching*.

### Reguli de proiectare

**Banii sunt numere întregi.** Toate sumele se stochează în bani (1 RON = 100 bani).
Rotunjirea se face half-up, ca la fisc. Conversia în RON apare doar la afișare, deci
un total nu poate să difere de suma liniilor lui.

**Fiecare operațiune economică produce o notă contabilă echilibrată.** `accounting.post`
refuză să scrie o notă în care debitul nu egalează creditul, așa că o eroare de logică
oprește operațiunea în loc să corupă evidența. Testele verifică invariantul după fiecare
scenariu.

**Totul sau nimic.** O emitere de factură care descarcă cinci produse și constată la al
patrulea că stocul nu ajunge nu lasă în urmă patru descărcări: tranzacția se anulează
integral și factura rămâne ciornă.

**Stocul se evaluează la cost mediu ponderat**, recalculat la fiecare recepție. Ieșirile
se descarcă la CMP-ul curent, iar costul efectiv al fiecărei linii de factură se
memorează, ca stornarea să repună marfa la costul cu care a plecat.

**Erorile de business ajung la model ca text, nu ca excepții.** Un client inexistent sau
un stoc insuficient întorc `{"eroare": "..."}`, iar agentul poate corecta din mers —
o excepție ar opri bucla.

## Teste

```bash
pytest
```

Cele 35 de teste rulează pe o bază de date în memorie și acoperă rotunjirile, costul
mediu ponderat, ciclul complet de facturare, încasările parțiale, stornarea, decontul de
TVA și bucla agentului (cu un client fals — nu se apelează API-ul).

## Limitări cunoscute

- Un singur exercițiu financiar, fără închidere de lună sau de an și fără reportarea
  soldurilor inițiale.
- Fără facturi în valută, discounturi pe linie sau taxare inversă.
- Fără e-Factura / SAF-T; datele sunt exportabile doar prin `gestio sql`.
- Cotele de TVA implicite sunt cele din România (21% standard, 11% redusă) și se
  configurează prin `GESTIO_VAT_RATE`.
- Aplicația ține evidența, dar nu ține locul unui contabil autorizat.
