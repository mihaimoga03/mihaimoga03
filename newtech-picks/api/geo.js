// Țara vizitatorului, după IP, din header-ul pus de Vercel. Pagina o folosește ca valoare implicită.
export default function handler(req, res) {
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify({ country: req.headers["x-vercel-ip-country"] || null }));
}
