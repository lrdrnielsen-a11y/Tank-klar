// Privat side med tallene. Virker kun med den hemmelige nøgle: /api/statistik?noegle=…
function danskDato(d = new Date()) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Copenhagen" }).format(d); // ÅÅÅÅ-MM-DD
}
function dageTilbage(n, fra = new Date()) {
  const ud = [];
  for (let i = 0; i < n; i++) ud.push(danskDato(new Date(fra.getTime() - i * 864e5)));
  return ud;
}
async function listAlle(kv, prefix) {
  const nøgler = []; let cursor;
  do {
    const r = await kv.list({ prefix, cursor });
    nøgler.push(...r.keys); cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return nøgler;
}
async function tal(kv, nu = new Date()) {
  const dage = dageTilbage(14, nu), pr_dag = [];
  const uge = new Set(), ugeInst = new Set();
  for (const [i, d] of dage.entries()) {
    const brug = await listAlle(kv, `d:${d}:`), inst = await listAlle(kv, `i:${d}:`);
    const m = brug.map(k => k.metadata || {});
    pr_dag.push({
      dato: d, brugere: brug.length, nye: m.filter(x => x.n).length,
      hjemmeskaerm: m.filter(x => x.i).length,
      iphone: m.filter(x => x.e === "iPhone").length, android: m.filter(x => x.e === "Android").length,
      computer: m.filter(x => x.e === "Computer").length, installationer: inst.length,
    });
    if (i < 7) { brug.forEach(k => uge.add(k.name.split(":")[2])); inst.forEach(k => ugeInst.add(k.name.split(":")[2])); }
  }
  return { pr_dag, uge_brugere: uge.size, uge_installationer: ugeInst.size };
}
function nøgleOk(request, env) {
  const n = new URL(request.url).searchParams.get("noegle");
  return Boolean(env.STAT_NOEGLE) && n === env.STAT_NOEGLE;
}

export async function onRequestGet({ request, env }) {
  if (!nøgleOk(request, env)) return new Response("Ikke adgang", { status: 403 });
  if (!env.STAT) return new Response("Lageret STAT er ikke koblet til", { status: 503 });
  const t = await tal(env.STAT);
  const fb = (await listAlle(env.STAT, "fb:")).sort((a, b) => b.name.localeCompare(a.name)).slice(0, 30);
  const esc = x => String(x || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fbHtml = fb.length ? fb.map(k => { const m = k.metadata || {}; const tid = new Date(k.name.split(":").slice(1, 4).join(":")).toLocaleString("da-DK", { timeZone: "Europe/Copenhagen", dateStyle: "medium", timeStyle: "short" });
    return `<div class="fb"><div class="fb-top"><b>${esc(m.h) || "Besked"}</b><span>${esc(tid)}</span></div><p>${esc(m.t) || "<i>(ingen tekst)</i>"}</p><small>${esc(m.i)}</small></div>`; }).join("")
    : `<p style="color:#5B6270">Ingen feedback endnu.</p>`;
  const rækker = t.pr_dag.map(d => `<tr><td>${d.dato}</td><td><b>${d.brugere}</b></td><td>${d.nye}</td><td>${d.hjemmeskaerm}</td><td>${d.installationer}</td><td>${d.iphone} / ${d.android} / ${d.computer}</td></tr>`).join("");
  const html = `<!doctype html><html lang="da"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Tank klar – statistik</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:0 auto;padding:24px 16px;color:#0C0F14}
h1{font-size:28px;margin:0 0 4px}.kort{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}.kort div{background:#F4F5F7;border-radius:16px;padding:14px 18px;flex:1;min-width:150px}
.kort b{display:block;font-size:30px}.fb{background:#F4F5F7;border-radius:14px;padding:12px 16px;margin:10px 0}.fb-top{display:flex;justify-content:space-between;gap:10px}.fb-top span,.fb small{color:#5B6270;font-size:13px}.fb p{margin:6px 0}table{width:100%;border-collapse:collapse;font-size:15px}td,th{text-align:left;padding:8px 6px;border-bottom:1px solid #E3E6EB}th{color:#5B6270;font-weight:600}
@media(prefers-color-scheme:dark){body{background:#0B0D11;color:#F2F3F5}.kort div,.fb{background:#15181E}td,th{border-color:#262B33}}</style></head><body>
<h1>Tank klar – statistik</h1><p style="color:#5B6270;margin:0">Kun synlig med din nøgle. Anonyme tal – ét tilfældigt nummer pr. telefon.</p>
<div class="kort"><div>Brugere i dag<b>${t.pr_dag[0].brugere}</b></div><div>Brugere i går<b>${t.pr_dag[1].brugere}</b></div><div>Seneste 7 dage<b>${t.uge_brugere}</b></div><div>Installationer, 7 dage<b>${t.uge_installationer}</b></div></div>
<table><tr><th>Dato</th><th>Brugere</th><th>Nye</th><th>Fra hjemmeskærm</th><th>Installeret</th><th>iPhone / Android / PC</th></tr>${rækker}</table>
<p style="color:#5B6270;font-size:13px">Installationer tælles kun på Android og computer – iPhone giver ikke besked, når appen lægges på hjemmeskærmen.</p>
<h2 style="margin-top:32px">Feedback</h2>${fbHtml}</body></html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}
