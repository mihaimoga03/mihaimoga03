# NewTech Picks — site de afiliere (Affiliate Market)

Unelte de service și gadgeturi recomandate de NewTech Repair. Fiecare produs arată doar
magazinele care livrează în țara vizitatorului, iar click-ul trece prin `/go/<produs>`,
care adaugă ID-ul de afiliat. Este experimentul #8 din „Portofoliu experimente online”.

Costul de funcționare pentru test: **0 lei** (Cloudflare Pages, plan gratuit, permite uz comercial).

## Structura

| Fișier | Rol |
| --- | --- |
| `public/catalog.js` | țări, magazine, produse și regulile de alegere — comun pentru pagină și server |
| `public/index.html`, `app.js`, `style.css`, `og.png` | pagina și imaginea de previzualizare pentru rețele |
| `lib/redirect.js` | alege magazinul și construiește linkul de afiliat |
| `functions/go/[slug].js` | `/go/<produs>?c=RO&s=emag&src=ig` → redirect 302 spre magazin |
| `functions/api/geo.js` | țara vizitatorului, dată de Cloudflare |

## Publicare pe Cloudflare Pages (o singură dată)

1. Cont gratuit pe cloudflare.com → **Workers & Pages → Create → Pages → Connect to Git**.
2. Alegi repo-ul `mihaimoga03/mihaimoga03` și branch-ul pe care e codul.
3. Project name: `affiliate-market` · Framework: **None** · Build command: gol ·
   Build output directory: `public` · Root directory: `newtech-picks`.
4. **Save and Deploy.** Site-ul apare la `https://affiliate-market.pages.dev`.

Dacă numele e luat și primești altă adresă, schimbă `og:image` din `public/index.html`.
Orice push pe branch republică automat site-ul.

## Linkuri pentru rețelele sociale

| Unde | Link |
| --- | --- |
| Bio Instagram | `https://affiliate-market.pages.dev/?src=ig` |
| TikTok | `…/?src=tiktok` · Facebook `…/?src=fb` |
| Un produs anume (story, postare) | `…/?src=ig#multimetru-true-rms` |

Cine deschide linkul din Instagram, Facebook sau TikTok ajunge în browserul aplicației, unde
nu e logat în eMag sau Amazon. Pagina îi arată un buton „Deschide în Chrome/Safari”, iar pe
Android ofertele se deschid direct în Chrome (de acolo în aplicația magazinului, dacă o are),
ca să cumpere din contul lui. Cookie-ul de afiliere se pune în browserul în care cumpără.

Butonul „Trimite produsul” de pe fiecare card copiază linkul direct al produsului.
Sursa ajunge ca sub-ID în rețelele de afiliere care o acceptă (Profitshare/2Performant prin
`{src}`, eBay prin `customid`), deci vezi în panoul lor ce rețea socială aduce comisioane.

## Programele de afiliere

| Magazin | Program | Variabilă |
| --- | --- | --- |
| eMag, PC Garage | Profitshare (sau 2Performant) | `AFF_TEMPLATE_EMAG`, `AFF_TEMPLATE_PCG` |
| Amazon | Amazon Associates, câte un cont pe marketplace | `AMAZON_TAG_DE`, `AMAZON_TAG_GB`… |
| eBay | eBay Partner Network | `EBAY_CAMPAIGN_ID` |
| AliExpress | AliExpress Portals | `AFF_TEMPLATE_ALI` |
| Temu | Temu Affiliate | `AFF_TEMPLATE_TEMU` |

Valorile se pun în Cloudflare → proiect → Settings → Variables and Secrets (lista în `.env.example`).

## Ce măsurăm

- Click-uri și comisioane: în panourile rețelelor de afiliere, pe sub-ID (sursă).
- Click-uri în timp real: Cloudflare → proiect → Functions → Real-time logs.
- Vizite: Cloudflare Web Analytics (gratuit, se activează din proiect).

## Rulare locală și teste

```bash
node dev.js                 # http://localhost:3000
COUNTRY=DE node dev.js      # simulează un vizitator din Germania
npm test                    # 15 teste, fără dependențe
```

## Adăugarea unui produs

Un obiect nou în `PRODUCTS` din `public/catalog.js`: `slug` unic (apare în link), `cat`,
titlu, de ce îl recomanzi, specificații, termenul de căutare în engleză (`en`) și română (`ro`).
