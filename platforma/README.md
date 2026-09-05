# Platforma Gestio

Pagina din `index.html` este publicată ca Artifact pe claude.ai și rulează cu
capacitatea `db` — o bază de date pe server, partajată între dispozitive. Se
deschide din contul Claude al proprietarului, de pe telefon sau de pe calculator.

Ce face: facturi emise și primite, rapoarte Z, bonuri de consum, nomenclator de
articole cu cost mediu ponderat, clienți, grafice de vânzări și scadențe.

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

Colecțiile din baza artefactului: `products`, `clients`, `invoices` (cu `tip`
`out` sau `in`), `zreports`, `consumptions`, `meta`. Sumele sunt numere întregi
de bani, ca în engine-ul Python.
