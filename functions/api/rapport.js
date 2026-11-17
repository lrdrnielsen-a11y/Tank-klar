// Sender gårsdagens tal som én besked til din private ntfy-kanal. Kaldes af cron-job.org: /api/rapport?noegle=…
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
  if (!env.STAT || !env.NTFY_RAPPORT) return new Response("STAT eller NTFY_RAPPORT mangler", { status: 503 });
  const t = await tal(env.STAT), g = t.pr_dag[1];
  const besked = `${g.brugere} brugere (${g.nye} nye) · ${g.hjemmeskaerm} fra hjemmeskærmen · ${g.installationer} nye installationer\n` +
    `${g.iphone} iPhone · ${g.android} Android · ${g.computer} computer\nSeneste 7 dage: ${t.uge_brugere} brugere`;
  const r = await fetch("https://ntfy.sh/", { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "TankKlar/1.0 (+https://tankklar.dk)" },
    body: JSON.stringify({ topic: env.NTFY_RAPPORT, title: `Tank klar i går (${g.dato})`, message: besked, tags: ["bar_chart"] }) });
  if (r.ok) return new Response("Sendt", { status: 200 });
  const svar = (await r.text().catch(() => "")).slice(0, 300);
  return new Response(`ntfy afviste beskeden (HTTP ${r.status}): ${svar}`, { status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
