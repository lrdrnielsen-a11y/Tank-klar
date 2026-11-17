// Modtager én anonym melding pr. telefon pr. dag (og når appen installeres).
// Der gemmes kun et tilfældigt nummer, om appen er installeret, og enhedstypen. Det slettes automatisk efter 40 dage.
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

export async function onRequestPost({ request, env }) {
  if (!env.STAT) return new Response(null, { status: 204 });
  let d; try { d = await request.json(); } catch { return new Response(null, { status: 400 }); }
  const id = String(d.id || "");
  if (!/^[a-z0-9]{10,40}$/.test(id)) return new Response(null, { status: 400 });
  const enhed = ["iPhone", "Android", "Computer"].includes(d.enhed) ? d.enhed : "Andet";
  const dato = danskDato(), ttl = 40 * 86400;
  if (d.type === "install") {
    await env.STAT.put(`i:${dato}:${id}`, "", { expirationTtl: ttl, metadata: { e: enhed } });
  } else {
    await env.STAT.put(`d:${dato}:${id}`, "", { expirationTtl: ttl, metadata: { i: d.installeret ? 1 : 0, n: d.ny ? 1 : 0, e: enhed } });
  }
  return new Response(null, { status: 204 });
}
