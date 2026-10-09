import { COUNTRIES, CATS, PRODUCTS, offersFor, normalizeCountry, cleanSource } from "./catalog.js";

const KEY = "ntp-country";
let country = "RO", cat = "all", picked = false;

// De unde a venit vizitatorul (?src=ig sau ?utm_source=instagram); se păstrează cât e deschis tab-ul.
const SRC = (() => {
  const q = new URLSearchParams(location.search);
  let s = cleanSource(q.get("src") || q.get("utm_source"));
  try {
    if (s) sessionStorage.setItem("ntp-src", s);
    else s = sessionStorage.getItem("ntp-src") || "";
  } catch {}
  return s;
})();

// Browserul din Instagram/Facebook/TikTok nu știe de contul clientului din eMag sau Amazon,
// așa că îl scoatem în browserul telefonului (sau în aplicația magazinului), unde e deja logat.
const UA = navigator.userAgent || "";
const IN_APP = /Instagram|FBAN|FBAV|FB_IAB|TikTok|musical_ly|BytedanceWebview|Snapchat|Pinterest/i.test(UA);
const ANDROID = /Android/i.test(UA);
const IOS = /iPhone|iPad|iPod/i.test(UA);
const APP_NAME = /Instagram/i.test(UA) ? "Instagram" : /TikTok|musical_ly|Bytedance/i.test(UA) ? "TikTok" : "Facebook";

// Pe Android, intent:// deschide adresa în Chrome; Chrome trimite apoi spre aplicația magazinului dacă e instalată.
const external = href => {
  const u = new URL(href, location.href);
  return ANDROID
    ? `intent://${u.host}${u.pathname}${u.search}${u.hash}#Intent;scheme=https;package=com.android.chrome;S.browser_fallback_url=${encodeURIComponent(u.href)};end`
    : IOS ? `x-safari-${u.href}` : u.href;
};

function inAppBanner() {
  if (!IN_APP || !(ANDROID || IOS)) return;
  const el = document.getElementById("inapp");
  el.hidden = false;
  el.innerHTML = `<b>Ești în browserul din ${APP_NAME}.</b> Aici nu ești logat în contul tău de eMag sau Amazon.
    <a class="btn" href="${esc(external(location.href))}">Deschide în ${ANDROID ? "Chrome" : "Safari"}</a>
    <span class="hint">Dacă nu merge: apasă ⋯ sus în dreapta → „Deschide în browser”.</span>`;
}

const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

function fromTimezone() {
  let tz = "";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch {}
  for (const [c, v] of Object.entries(COUNTRIES)) if (v.tz.includes(tz)) return c;
  return "XX";
}

async function fromIp() {
  try {
    const r = await fetch("/api/geo", { signal: AbortSignal.timeout(1500) });
    const { country: c } = await r.json();
    return c ? normalizeCountry(c) : null;
  } catch { return null; }
}

function render() {
  const grid = document.getElementById("grid");
  const list = PRODUCTS.filter(p => cat === "all" || p.cat === cat);
  if (!list.length) { grid.innerHTML = '<p class="empty">Nu sunt produse în această categorie.</p>'; return; }
  grid.innerHTML = list.map(p => {
    const o = offersFor(p, country);
    const rows = o.length ? o.map((x, i) => {
      const go = `/go/${p.slug}?c=${country}&s=${x.s.id}${SRC ? `&src=${SRC}` : ""}`;
      const href = IN_APP && ANDROID ? external(go) : go;
      return `
      <a class="offer${i === 0 && x.score > 0 ? " best" : ""}" href="${esc(href)}" target="_blank" rel="sponsored noopener">
        <span><span class="s">${esc(x.s.name)}</span><br><span class="m">${esc(x.s.net)}</span></span>
        <span class="go">Vezi oferta →</span>
      </a>`;
    }).join("") : '<span class="none">Niciun magazin nu livrează aici.</span>';
    return `<article class="card" id="${p.slug}">
      <span class="cat">${esc(CATS[p.cat])}</span>
      <h2>${esc(p.t)}</h2>
      <p class="why">${esc(p.why)}</p>
      <div class="spec">${esc(p.spec)}</div>
      <div class="offers">${rows}</div>
      <button type="button" class="share" data-slug="${p.slug}" data-t="${esc(p.t)}">Trimite produsul</button>
    </article>`;
  }).join("");
}

// Link direct spre un produs: /#statie-lipit-aer-cald (pentru postări, story-uri, link în bio)
function focusFromHash() {
  const slug = decodeURIComponent(location.hash.slice(1));
  if (!slug || !PRODUCTS.some(p => p.slug === slug)) return;
  if (cat !== "all") {
    cat = "all";
    document.querySelectorAll("#filters button").forEach(x => x.setAttribute("aria-pressed", x.dataset.k === "all"));
    render();
  }
  const el = document.getElementById(slug);
  if (!el) return;
  el.classList.add("hl");
  el.scrollIntoView({ block: "start" });
}

async function share(btn) {
  const url = `${location.origin}/#${btn.dataset.slug}`;
  try {
    if (navigator.share) return await navigator.share({ title: btn.dataset.t, url });
    await navigator.clipboard.writeText(url);
    btn.textContent = "Link copiat";
  } catch {}
}

function setCountry(c, how) {
  country = c;
  document.getElementById("country").value = c;
  document.getElementById("detect").innerHTML = how
    ? `Detectat: <b>${esc(COUNTRIES[c].n)}</b> (${how}). Schimbă manual ca să vezi alte magazine.`
    : "";
  render();
}

async function init() {
  inAppBanner();
  const sel = document.getElementById("country");
  sel.innerHTML = Object.entries(COUNTRIES).map(([c, v]) => `<option value="${c}">${esc(v.n)}</option>`).join("");
  sel.addEventListener("change", () => {
    picked = true;
    try { localStorage.setItem(KEY, sel.value); } catch {}
    setCountry(sel.value, "");
  });

  const f = document.getElementById("filters");
  f.innerHTML = [["all", "Toate"], ...Object.entries(CATS)]
    .map(([k, v]) => `<button type="button" data-k="${k}" aria-pressed="${k === cat}">${esc(v)}</button>`).join("");
  f.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    cat = b.dataset.k;
    f.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x.dataset.k === cat));
    render();
  });

  document.getElementById("grid").addEventListener("click", e => {
    const b = e.target.closest(".share");
    if (b) share(b);
  });
  window.addEventListener("hashchange", focusFromHash);

  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch {}
  if (saved && COUNTRIES[saved]) { setCountry(saved, "alegerea ta anterioară"); return focusFromHash(); }

  setCountry(fromTimezone(), "după fusul orar");
  focusFromHash();
  const ip = await fromIp();
  if (ip && ip !== country && !picked) setCountry(ip, "după conexiune");
}

init();
