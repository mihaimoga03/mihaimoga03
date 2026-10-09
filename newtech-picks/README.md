# NewTech Picks — site de afiliere

Unelte de service și gadgeturi recomandate de NewTech Repair. Fiecare produs arată doar
magazinele care livrează în țara vizitatorului, iar click-ul trece prin `/go/<produs>`,
care adaugă ID-ul de afiliat și numără click-ul. Este experimentul #8 din
„Portofoliu experimente online” (Ghiduri digitale și afiliere).

## Cum funcționează

| Fișier | Rol |
| --- | --- |
| `catalog.js` | țări, magazine, produse și regulile de alegere — comun pentru pagină și server |
| `index.html`, `app.js`, `style.css` | pagina; țara vine din alegerea salvată, apoi fus orar, apoi IP |
| `api/go.js` | `/go/<produs>?c=RO&s=emag` → link de afiliat + click în Supabase + redirect 302 |
| `api/geo.js` | țara după IP, din header-ul `x-vercel-ip-country` |
| `supabase/clicks.sql` | tabelul `clicks` și raportul `clicks_pe_zi` |

Regulile de magazin: eMag doar RO/BG/HU, PC Garage doar RO (încărcare și audio), Amazon și
eBay pe domeniul local (US, GB, DE, FR, IT, ES), AliExpress și Temu peste tot. Magazinul cu
scorul cel mai mare în țara respectivă e marcat verde.

## Rulare locală

```bash
node dev.js                 # http://localhost:3000
COUNTRY=DE node dev.js      # simulează un vizitator din Germania
npm test                    # 12 teste, fără dependențe
```

## Publicare pe Vercel

1. Proiect nou din repo, cu **Root Directory** = `newtech-picks`. Fără build, fără framework.
2. Rulezi `supabase/clicks.sql` în Supabase (SQL Editor).
3. Pui variabilele din `.env.example` în Settings → Environment Variables. Oricare lipsește,
   linkul acelui magazin merge simplu, fără comision — site-ul funcționează din prima zi.

## Programele de afiliere de deschis

| Magazin | Program | Variabilă |
| --- | --- | --- |
| eMag, PC Garage | Profitshare (sau 2Performant) | `AFF_TEMPLATE_EMAG`, `AFF_TEMPLATE_PCG` |
| Amazon | Amazon Associates, câte un cont pe marketplace | `AMAZON_TAG_DE`, `AMAZON_TAG_GB`… |
| eBay | eBay Partner Network | `EBAY_CAMPAIGN_ID` |
| AliExpress | AliExpress Portals | `AFF_TEMPLATE_ALI` |
| Temu | Temu Affiliate | `AFF_TEMPLATE_TEMU` |

Șabloanele `AFF_TEMPLATE_*` sunt linkul de deep link al rețelei, cu `{url}` în locul adresei
magazinului (exemplu în `.env.example`).

## Adăugarea unui produs

Un obiect nou în `PRODUCTS` din `catalog.js`: `slug` unic (apare în link), `cat`, titlu,
de ce îl recomanzi, specificații, termenul de căutare în engleză (`en`) și în română (`ro`).

## Ce măsurăm

Metrica experimentului: click-uri pe zi din `clicks_pe_zi`, apoi comisioane din panourile
rețelelor. Nu se păstrează IP-ul și nu se pun cookie-uri; boții nu sunt numărați.
