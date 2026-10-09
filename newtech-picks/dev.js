// Server local care imită Vercel: fișiere statice, /api/*, rescrierea /go/:slug.
// Pornire: node dev.js  (opțional COUNTRY=DE ca să simulezi țara după IP)
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css" };
const root = new URL(".", import.meta.url).pathname;

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  req.query = Object.fromEntries(url.searchParams);
  if (process.env.COUNTRY) req.headers["x-vercel-ip-country"] = process.env.COUNTRY;
  let path = url.pathname;
  const go = path.match(/^\/go\/([^/]+)$/);
  if (go) { req.query.p = go[1]; path = "/api/go"; }
  if (path.startsWith("/api/")) {
    const mod = await import(join(root, `${path}.js`)).catch(() => null);
    if (mod) return mod.default(req, res);
  }
  const file = normalize(join(root, path === "/" ? "index.html" : path));
  if (!file.startsWith(root) || file.includes("/api/") || file.includes("/test/")) { res.statusCode = 404; return res.end(); }
  try {
    const body = await readFile(file);
    res.setHeader("Content-Type", TYPES[extname(file)] || "application/octet-stream");
    res.end(body);
  } catch { res.statusCode = 404; res.end("404"); }
}).listen(process.env.PORT || 3000, () => console.log(`http://localhost:${process.env.PORT || 3000}`));
