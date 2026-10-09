// /go/<produs>?c=RO&s=emag — alege magazinul, adaugă ID-ul de afiliat, înregistrează click-ul și redirecționează.
import { productBySlug, offersFor, affiliateUrl, normalizeCountry } from "../catalog.js";

const BOT = /bot|crawl|spider|slurp|preview|facebookexternalhit|headless/i;

export async function logClick(row, env = process.env, fetchImpl = fetch) {
  if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_KEY) return false;
  try {
    const r = await fetchImpl(`${env.SUPABASE_URL}/rest/v1/clicks`, {
      method: "POST",
      headers: {
        apikey: env.SUPABASE_SERVICE_KEY,
        Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(row),
      signal: AbortSignal.timeout(800),
    });
    return r.ok;
  } catch {
    return false; // logarea nu are voie să blocheze vizitatorul
  }
}

export function resolve(query, headers, env = process.env) {
  const p = productBySlug(String(query.p || ""));
  if (!p) return null;
  const geo = headers["x-vercel-ip-country"];
  const country = normalizeCountry(query.c || geo);
  const offers = offersFor(p, country);
  if (!offers.length) return null;
  const chosen = offers.find(o => o.s.id === query.s)?.s || offers[0].s;
  return {
    url: affiliateUrl(chosen, p, country, env),
    row: {
      product: p.slug,
      store: chosen.id,
      country,
      country_source: query.c ? "ales" : geo ? "ip" : "necunoscut",
      referrer: String(headers.referer || "").slice(0, 300) || null,
    },
  };
}

export default async function handler(req, res) {
  const hit = resolve(req.query || {}, req.headers || {});
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Robots-Tag", "noindex, nofollow");
  if (!hit) {
    res.statusCode = 302;
    res.setHeader("Location", "/");
    return res.end();
  }
  if (!BOT.test(req.headers["user-agent"] || "")) await logClick(hit.row);
  res.statusCode = 302;
  res.setHeader("Location", hit.url);
  res.end();
}
