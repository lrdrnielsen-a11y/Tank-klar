// Feedback gemmes i dit private lager (STAT) og kan læses på statistiksiden.
// Bagefter forsøges en notifikation – men feedbacken går aldrig tabt, hvis den fejler.
export async function onRequestPost({ request, env }) {
  let d; try { d = await request.json(); } catch { return new Response(null, { status: 400 }); }
  const tekst = String(d.tekst || "").slice(0, 1000), humør = String(d.humør || "").slice(0, 30), info = String(d.info || "").slice(0, 200);
  if (!tekst && !humør) return new Response(null, { status: 400 });
  if (!env.STAT) return new Response("Feedback er ikke sat op", { status: 503 });
  const nu = new Date().toISOString();
  await env.STAT.put(`fb:${nu}:${Math.random().toString(36).slice(2, 8)}`, "", { expirationTtl: 180 * 86400, metadata: { t: tekst, h: humør, i: info } });
  await underret(env, `Feedback: ${humør || "Ny besked"}`, `${tekst || "(ingen tekst)"}\n\n${info}`).catch(() => {});
  return new Response(null, { status: 204 });
}
async function underret(env, titel, besked) {
  if (env.TELEGRAM_TOKEN && env.TELEGRAM_CHAT) {
    return fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT, text: `${titel}\n\n${besked}` }) });
  }
  if (env.NTFY_FEEDBACK) {
    return fetch("https://ntfy.sh/", { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "TankKlar/1.0 (+https://tankklar.dk)" },
      body: JSON.stringify({ topic: env.NTFY_FEEDBACK, title: titel, message: besked, tags: ["speech_balloon"] }) });
  }
}
