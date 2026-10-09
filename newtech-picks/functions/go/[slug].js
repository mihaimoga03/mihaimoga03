// Cloudflare Pages Function: /go/<produs>?c=RO&s=emag&src=ig → redirect spre magazin cu ID de afiliat.
import { resolve, BOT } from "../../lib/redirect.js";

export function onRequest({ request, params, env }) {
  const url = new URL(request.url);
  const q = url.searchParams;
  const hit = resolve(
    { p: params.slug, c: q.get("c"), s: q.get("s"), src: q.get("src") },
    { country: request.cf?.country || request.headers.get("cf-ipcountry"), referer: request.headers.get("referer") },
    env,
  );
  if (!hit) return Response.redirect(new URL("/", url).toString(), 302);
  // Click-ul apare în Cloudflare → Workers & Pages → proiect → Functions → Real-time logs
  if (!BOT.test(request.headers.get("user-agent") || "")) console.log(JSON.stringify({ click: hit.row }));
  return new Response(null, {
    status: 302,
    headers: { Location: hit.url, "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}
