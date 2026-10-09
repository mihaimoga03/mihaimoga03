import { test } from "node:test";
import assert from "node:assert/strict";
import { PRODUCTS, STORES, offersFor, affiliateUrl, productBySlug, cleanSource } from "../public/catalog.js";
import { resolve } from "../lib/redirect.js";
import { onRequest as go } from "../functions/go/[slug].js";
import { onRequest as geo } from "../functions/api/geo.js";

const p = productBySlug("multimetru-true-rms");
const store = id => STORES.find(s => s.id === id);

test("sluguri unice", () => {
  assert.equal(new Set(PRODUCTS.map(x => x.slug)).size, PRODUCTS.length);
});

test("în România eMag e recomandat, Amazon lipsește", () => {
  const ids = offersFor(p, "RO").map(o => o.s.id);
  assert.equal(ids[0], "emag");
  assert.ok(!ids.includes("amz"));
});

test("în Germania Amazon e recomandat, eMag lipsește", () => {
  const ids = offersFor(p, "DE").map(o => o.s.id);
  assert.equal(ids[0], "amz");
  assert.ok(!ids.includes("emag"));
});

test("PC Garage apare doar la categoriile lui", () => {
  assert.ok(!offersFor(p, "RO").some(o => o.s.id === "pcg"));
  assert.ok(offersFor(productBySlug("incarcator-gan-65w"), "RO").some(o => o.s.id === "pcg"));
});

test("fără configurare, linkul e cel simplu", () => {
  assert.equal(affiliateUrl(store("amz"), p, "DE"), "https://www.amazon.de/s?k=true%20rms%20digital%20multimeter");
});

test("Amazon primește tag-ul țării, apoi pe cel general", () => {
  const env = { AMAZON_TAG: "gen-21", AMAZON_TAG_DE: "de-21" };
  assert.match(affiliateUrl(store("amz"), p, "DE", env), /&tag=de-21$/);
  assert.match(affiliateUrl(store("amz"), p, "GB", env), /&tag=gen-21$/);
});

test("eBay primește campid și rotația site-ului", () => {
  const u = affiliateUrl(store("ebay"), p, "GB", { EBAY_CAMPAIGN_ID: "533" });
  assert.match(u, /^https:\/\/www\.ebay\.co\.uk\/.*mkrid=710-53481-19255-0&campid=533/);
});

test("șablonul de deep link codează adresa magazinului", () => {
  const u = affiliateUrl(store("emag"), p, "RO", { AFF_TEMPLATE_EMAG: "https://aff.example/c?to={url}" });
  assert.equal(u, "https://aff.example/c?to=" + encodeURIComponent("https://www.emag.ro/search/multimetru%20digital%20true%20rms"));
});

test("/go: țara aleasă bate IP-ul, magazinul cerut e respectat", () => {
  const hit = resolve({ p: p.slug, c: "ro", s: "ali" }, { country: "DE" }, {});
  assert.equal(hit.row.country, "RO");
  assert.equal(hit.row.country_source, "ales");
  assert.equal(hit.row.store, "ali");
});

test("/go: fără țară folosește IP-ul și recomandatul; magazin nelivrabil e ignorat", () => {
  const hit = resolve({ p: p.slug, s: "emag" }, { country: "US" }, {});
  assert.equal(hit.row.country, "US");
  assert.equal(hit.row.country_source, "ip");
  assert.equal(hit.row.store, "amz");
});

test("/go: produs necunoscut → null", () => {
  assert.equal(resolve({ p: "nu-exista" }, {}, {}), null);
});

test("sursa de trafic: curățată și trimisă ca sub-ID", () => {
  assert.equal(cleanSource("IG"), "ig");
  assert.equal(cleanSource("<script>"), "");
  const env = { AFF_TEMPLATE_EMAG: "https://aff.example/c?to={url}&sub={src}", EBAY_CAMPAIGN_ID: "5" };
  assert.match(affiliateUrl(store("emag"), p, "RO", env, "ig"), /&sub=ig$/);
  assert.match(affiliateUrl(store("emag"), p, "RO", env), /&sub=site$/);
  assert.match(affiliateUrl(store("ebay"), p, "DE", env, "tiktok"), /&customid=tiktok$/);
  assert.equal(resolve({ p: p.slug, src: "fb" }, {}, {}).row.src, "fb");
});

test("funcția /go pe Cloudflare: țara din cf, redirect 302", () => {
  const request = new Request("https://x.pages.dev/go/multimetru-true-rms?src=ig", { headers: { "user-agent": "Mozilla" } });
  request.cf = { country: "GB" };
  const r = go({ request, params: { slug: "multimetru-true-rms" }, env: { AMAZON_TAG_GB: "uk-21" } });
  assert.equal(r.status, 302);
  assert.equal(r.headers.get("location"), "https://www.amazon.co.uk/s?k=true%20rms%20digital%20multimeter&tag=uk-21");
});

test("funcția /go: produs inexistent → prima pagină", () => {
  const r = go({ request: new Request("https://x.pages.dev/go/nimic"), params: { slug: "nimic" }, env: {} });
  assert.equal(r.status, 302);
  assert.equal(r.headers.get("location"), "https://x.pages.dev/");
});

test("funcția /api/geo întoarce țara din header", async () => {
  const r = geo({ request: new Request("https://x/api/geo", { headers: { "cf-ipcountry": "RO" } }) });
  assert.deepEqual(await r.json(), { country: "RO" });
});
