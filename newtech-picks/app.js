import { COUNTRIES, CATS, PRODUCTS, offersFor, normalizeCountry } from "./catalog.js";

const KEY = "ntp-country";
let country = "RO", cat = "all", picked = false;

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
    const rows = o.length ? o.map((x, i) => `
      <a class="offer${i === 0 && x.score > 0 ? " best" : ""}" href="/go/${p.slug}?c=${country}&s=${x.s.id}" target="_blank" rel="sponsored noopener">
        <span><span class="s">${esc(x.s.name)}</span><br><span class="m">${esc(x.s.net)}</span></span>
        <span class="go">Vezi oferta →</span>
      </a>`).join("") : '<span class="none">Niciun magazin nu livrează aici.</span>';
    return `<article class="card">
      <span class="cat">${esc(CATS[p.cat])}</span>
      <h2>${esc(p.t)}</h2>
      <p class="why">${esc(p.why)}</p>
      <div class="spec">${esc(p.spec)}</div>
      <div class="offers">${rows}</div>
    </article>`;
  }).join("");
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

  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch {}
  if (saved && COUNTRIES[saved]) return setCountry(saved, "alegerea ta anterioară");

  setCountry(fromTimezone(), "după fusul orar");
  const ip = await fromIp();
  if (ip && ip !== country && !picked) setCountry(ip, "după conexiune");
}

init();
