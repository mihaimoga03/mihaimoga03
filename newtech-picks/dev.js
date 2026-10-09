// Server local care imită Cloudflare Pages: fișiere din public/ și funcțiile din functions/.
// Pornire: node dev.js  (opțional COUNTRY=DE ca să simulezi țara după IP)
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import * as go from "./functions/go/[slug].js";
import * as geo from "./functions/api/geo.js";

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".png": "image/png" };
const pub = new URL("./public/", import.meta.url).pathname;
const env = { ...process.env };

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const headers = { ...req.headers };
  if (process.env.COUNTRY) headers["cf-ipcountry"] = process.env.COUNTRY;
  const request = new Request(url, { headers });
  const m = url.pathname.match(/^\/go\/([^/]+)$/);
  let out = null;
  if (m) out = go.onRequest({ request, params: { slug: m[1] }, env });
  else if (url.pathname === "/api/geo") out = geo.onRequest({ request });
  if (out) {
    res.writeHead(out.status, Object.fromEntries(out.headers));
    return res.end(Buffer.from(await out.arrayBuffer()));
  }
  const file = normalize(join(pub, url.pathname === "/" ? "index.html" : url.pathname));
  if (!file.startsWith(pub)) { res.statusCode = 404; return res.end(); }
  try {
    const body = await readFile(file);
    res.setHeader("Content-Type", TYPES[extname(file)] || "application/octet-stream");
    res.end(body);
  } catch { res.statusCode = 404; res.end("404"); }
}).listen(process.env.PORT || 3000, () => console.log(`http://localhost:${process.env.PORT || 3000}`));
