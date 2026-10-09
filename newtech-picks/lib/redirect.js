// Logica din spatele /go/<produs>: alege magazinul și construiește linkul de afiliat.
import { productBySlug, offersFor, affiliateUrl, normalizeCountry, cleanSource } from "../public/catalog.js";

export const BOT = /bot|crawl|spider|slurp|preview|facebookexternalhit|headless/i;

// query: { p, c, s, src } · visitor: { country, referer } · env: ID-urile de afiliat
export function resolve(query, visitor = {}, env = {}) {
  const p = productBySlug(String(query.p || ""));
  if (!p) return null;
  const country = normalizeCountry(query.c || visitor.country);
  const offers = offersFor(p, country);
  if (!offers.length) return null;
  const chosen = offers.find(o => o.s.id === query.s)?.s || offers[0].s;
  const src = cleanSource(query.src);
  return {
    url: affiliateUrl(chosen, p, country, env, src),
    row: {
      product: p.slug,
      store: chosen.id,
      country,
      country_source: query.c ? "ales" : visitor.country ? "ip" : "necunoscut",
      src: src || null,
      referrer: String(visitor.referer || "").slice(0, 300) || null,
    },
  };
}
