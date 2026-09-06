# Platforma Gestio

Pagina din `index.html` este publicată ca Artifact pe claude.ai și rulează cu
capacitatea `db` — o bază de date pe server, partajată între dispozitive. Se
deschide din contul Claude al proprietarului, de pe telefon sau de pe calculator.

Ce face: datele firmei, facturi emise și primite, rapoarte Z, bonuri de consum,
nomenclator de articole pe categorii cu cost mediu ponderat, corecții de stoc după
inventar, istoric lunar, clienți, grafice — și un panou de sfaturi în care Claude
citește cifrele din aplicație și răspunde la întrebări despre firmă.

Fiecare articol are o **categorie**. Fila Stoc grupează după ea, arată valoarea pe
categorii și filtrează cu un rând de chips-uri. `clasificare.py` conține regulile
care încadrează automat un articol după denumire — le poți rula peste un export nou
de stoc ca să păstrezi aceleași categorii de la o lună la alta.

Fila **Istoric** ține o linie pe lună (venituri, cheltuieli, stoc final) și o poate
precompleta din facturile, rapoartele Z și bonurile deja înregistrate pe luna aceea.

Fila **Setări** ține datele firmei (denumire, CUI, adresă, cota implicită de TVA,
seria facturilor) în `meta/state` și conține un tabel cu locul fiecărei operațiuni.
Un articol nou poate porni direct cu stoc și cost — corecțiile ulterioare se fac
apăsând pe rândul lui în tabelul de stoc și rămân în `adjustments`, cu motiv.

## Cum se actualizează

Pagina se republică pe același URL din conversația care a publicat-o prima dată,
sau din altă conversație dându-i URL-ul artefactului. Datele nu se pierd la
republicare: trăiesc în baza artefactului, nu în pagină.

## Ce nu e

Nu e agentul Python din `gestio/`. Platforma își are propria logică, scrisă în
JavaScript în pagină, pentru că rulează în browserul vizitatorului fără server.
Cele două împart regulile de business (bani în unități întregi, cost mediu
ponderat, TVA la 21%), dar sunt implementări separate — o modificare într-una
nu se propagă singură în cealaltă.

Fila **Service** ține fișele de reparație preluate din aplicația de service
(Supabase, proiectul `gestiune-service`): client, aparat, defect, stare, manoperă,
piese, avans, încasat. Soldul unui client adună restanțele de pe fișe, nu doar
facturile. Costul pieselor vine ca sumă pe fișă, pentru că fișele preluate până acum
sunt dinainte de legarea pieselor de stoc.

**Stocul are de acum două locuri, cu roluri diferite.** Sursa de adevăr e aplicația de
service (vezi `service/`): acolo articolele sunt legate de piesele de pe fișă, acolo se
vede la primire dacă piesa e în casă sau trebuie comandată, și tot acolo ies pe bon de
consum. Nomenclatorul de aici e o copie, folosită pentru rapoartele și sfaturile care
privesc firma întreagă — o mișcare făcută în service nu se propagă singură în platformă.

Colecțiile din baza artefactului: `products` (cu `categorie` și `gestiune`),
`clients`, `invoices` (cu `tip` `out` sau `in`), `zreports`, `consumptions`,
`adjustments`, `periods` (o lună per document, id `YYYY-MM`), `fise`, `meta`.

Capacitățile declarate: `db` pentru bază, `sample` pentru panoul de sfaturi.
Rezumatul trimis modelului e construit din datele paginii — categorii, cele mai
valoroase poziții, adaosurile mici, istoricul lunar, consumurile, soldurile — nu
baza întreagă. Sumele sunt numere întregi
de bani, ca în engine-ul Python.
