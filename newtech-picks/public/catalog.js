// Catalogul comun: îl folosesc și pagina (în browser), și funcția /go (pe server).
// Aici nu intră nimic secret — ID-urile de afiliat vin din variabilele de mediu, doar pe server.

export const COUNTRIES = {
  RO: { n: "România", tz: ["Europe/Bucharest"] },
  BG: { n: "Bulgaria", tz: ["Europe/Sofia"] },
  HU: { n: "Ungaria", tz: ["Europe/Budapest"] },
  DE: { n: "Germania", tz: ["Europe/Berlin"] },
  GB: { n: "Marea Britanie", tz: ["Europe/London"] },
  FR: { n: "Franța", tz: ["Europe/Paris"] },
  IT: { n: "Italia", tz: ["Europe/Rome"] },
  ES: { n: "Spania", tz: ["Europe/Madrid"] },
  US: { n: "SUA", tz: ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"] },
  XX: { n: "Altă țară", tz: [] },
};

const enc = encodeURIComponent;
const AMZ = { US: "com", GB: "co.uk", DE: "de", FR: "fr", IT: "it", ES: "es" };
const EBAY = { US: "com", GB: "co.uk", DE: "de", FR: "fr", IT: "it", ES: "es" };
const EMAG = { RO: "ro", BG: "bg", HU: "hu" };
// eBay Partner Network: ID-ul de rotație al fiecărui site eBay
const EBAY_ROTATION = {
  US: "711-53200-19255-0", GB: "710-53481-19255-0", DE: "707-53477-19255-0",
  FR: "709-53476-19255-0", IT: "724-53478-19255-0", ES: "1185-53479-19255-0",
};

// prio: scorul magazinului într-o țară; cel mai mare câștigă eticheta „recomandat”.
export const STORES = [
  { id: "emag", name: "eMag", net: "Profitshare", cookie: "~30 zile",
    ships: c => c in EMAG, url: (p, c) => `https://www.emag.${EMAG[c]}/search/${enc(p.ro)}`,
    prio: { RO: 3, BG: 3, HU: 3 } },
  { id: "pcg", name: "PC Garage", net: "Profitshare", cookie: "vezi programul",
    ships: c => c === "RO", url: p => `https://www.pcgarage.ro/cauta/${enc(p.ro)}/`,
    prio: { RO: 2 }, only: ["power", "audio"] },
  { id: "amz", name: "Amazon", net: "Amazon Associates", cookie: "24 h / 90 zile în coș",
    ships: c => c in AMZ, url: (p, c) => `https://www.amazon.${AMZ[c]}/s?k=${enc(p.en)}`,
    prio: { US: 3, GB: 3, DE: 3, FR: 3, IT: 3, ES: 3 } },
  { id: "ebay", name: "eBay", net: "eBay Partner Network", cookie: "vezi programul",
    ships: c => c in EBAY, url: (p, c) => `https://www.ebay.${EBAY[c]}/sch/i.html?_nkw=${enc(p.en)}`,
    prio: {} },
  { id: "ali", name: "AliExpress", net: "AliExpress Portals", cookie: "vezi programul",
    ships: () => true, url: p => `https://www.aliexpress.com/w/wholesale-${p.en.trim().replace(/\s+/g, "-")}.html`,
    prio: { XX: 3, RO: 1 } },
  { id: "temu", name: "Temu", net: "Temu Affiliate", cookie: "vezi programul",
    ships: () => true, url: p => `https://www.temu.com/search_result.html?search_key=${enc(p.en)}`,
    prio: { XX: 2 } },
];

export const CATS = { tools: "Unelte service", measure: "Măsură", power: "Încărcare", audio: "Audio" };

export const PRODUCTS = [
  { slug: "statie-lipit-aer-cald", cat: "tools", t: "Stație de lipit cu aer cald 2 în 1",
    why: "Pentru conectori USB-C și piese SMD. Ia una cu temperatură afișată digital.",
    spec: "letcon 60–80 W · aer cald 100–480 °C", en: "soldering station hot air 2 in 1", ro: "statie lipit aer cald" },
  { slug: "multimetru-true-rms", cat: "measure", t: "Multimetru digital True RMS",
    why: "Măsori căderi de tensiune pe linii și scurturi pe placă. True RMS contează la rețea.",
    spec: "6000 counts · continuitate cu buzzer · NCV", en: "true rms digital multimeter", ro: "multimetru digital true rms" },
  { slug: "set-surubelnite-precizie", cat: "tools", t: "Set șurubelnițe de precizie",
    why: "Pentru telefoane și laptopuri: pentalobe, tri-wing, Torx T2–T6.",
    spec: "60+ biți · mâner magnetic · S2", en: "precision screwdriver set phone repair", ro: "set surubelnite precizie" },
  { slug: "microscop-usb-ecran", cat: "measure", t: "Microscop USB cu ecran",
    why: "Vezi pistele rupte și lipiturile reci fără să-ți forțezi ochii.",
    spec: "ecran 7\" · mărire până la 1200×", en: "digital microscope lcd soldering", ro: "microscop digital ecran" },
  { slug: "incarcator-gan-65w", cat: "power", t: "Încărcător GaN 65 W, 3 porturi",
    why: "Încarcă laptopul și telefonul din aceeași priză. GaN înseamnă mai mic și mai rece.",
    spec: "USB-C PD 65 W · 2×C + 1×A", en: "gan charger 65w usb c", ro: "incarcator gan 65w" },
  { slug: "power-bank-20000", cat: "power", t: "Power bank 20 000 mAh cu PD",
    why: "Capacitate reală bună și încărcare rapidă. Verifică să aibă PD de minim 20 W.",
    spec: "20 000 mAh · PD 22.5 W · USB-C intrare/ieșire", en: "power bank 20000mah pd", ro: "baterie externa 20000mah" },
  { slug: "lampa-lupa-led", cat: "tools", t: "Lampă cu lupă și LED",
    why: "Lumină uniformă pe banc. Lupa ajută la componente mici fără microscop.",
    spec: "lupă 5 dioptrii · LED reglabil", en: "magnifying lamp led workbench", ro: "lampa cu lupa led" },
  { slug: "casti-tws-anc", cat: "audio", t: "Căști TWS cu ANC",
    why: "Anularea zgomotului face diferența în autobuz. Alege modele cu codec AAC.",
    spec: "ANC · Bluetooth 5.3 · AAC", en: "tws earbuds anc", ro: "casti wireless anc" },
];

export const normalizeCountry = c => {
  const up = String(c || "").toUpperCase();
  return up in COUNTRIES ? up : "XX";
};

// Sursa de trafic din link (?src=ig): doar litere, cifre, - și _, ca să nu ajungă gunoi în URL-uri.
export const cleanSource = s => (/^[a-z0-9_-]{1,24}$/i.test(String(s || "")) ? String(s).toLowerCase() : "");

export const productBySlug = slug => PRODUCTS.find(p => p.slug === slug);

// Magazinele care livrează produsul în țara dată, cel recomandat primul.
export function offersFor(p, c) {
  return STORES
    .filter(s => s.ships(c) && (!s.only || s.only.includes(p.cat)))
    .map(s => ({ s, score: s.prio[c] || 0 }))
    .sort((a, b) => b.score - a.score);
}

// Linkul final spre magazin, cu ID-ul de afiliat dacă e configurat în env.
// src = de unde vine vizitatorul (ig, tiktok, fb…); ajunge ca sub-ID în rețelele care îl acceptă.
// Fără configurare întoarce linkul simplu, ca site-ul să meargă și înainte de aprobarea în programe.
export function affiliateUrl(store, p, c, env = {}, src = "") {
  const plain = store.url(p, c);
  if (store.id === "amz") {
    const tag = env[`AMAZON_TAG_${c}`] || env.AMAZON_TAG;
    return tag ? `${plain}&tag=${enc(tag)}` : plain;
  }
  if (store.id === "ebay") {
    const camp = env.EBAY_CAMPAIGN_ID;
    return camp
      ? `${plain}&mkcid=1&mkrid=${EBAY_ROTATION[c]}&campid=${enc(camp)}&toolid=10001&mkevt=1${src ? `&customid=${enc(src)}` : ""}`
      : plain;
  }
  const tpl = env[`AFF_TEMPLATE_${store.id.toUpperCase()}`];
  return tpl && tpl.includes("{url}")
    ? tpl.replace("{url}", enc(plain)).replace("{src}", enc(src || "site"))
    : plain;
}
