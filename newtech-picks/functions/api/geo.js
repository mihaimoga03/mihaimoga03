// Țara vizitatorului după IP, pusă de Cloudflare pe fiecare cerere.
export function onRequest({ request }) {
  const country = request.cf?.country || request.headers.get("cf-ipcountry") || null;
  return Response.json({ country }, { headers: { "Cache-Control": "private, no-store" } });
}
