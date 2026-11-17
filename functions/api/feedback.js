// Sender feedback videre til en ntfy-kanal, hvis navn kun står som hemmelighed hos Cloudflare.
export async function onRequestPost({ request, env }) {
  const emne = env.NTFY_FEEDBACK;
  if (!emne) return new Response("Feedback er ikke sat op", { status: 503 });
  let d; try { d = await request.json(); } catch { return new Response(null, { status: 400 }); }
  const tekst = String(d.tekst || "").slice(0, 1500), humør = String(d.humør || "").slice(0, 30), info = String(d.info || "").slice(0, 200);
  if (!tekst && !humør) return new Response(null, { status: 400 });
  const r = await fetch("https://ntfy.sh/", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic: emne, title: `Feedback: ${humør || "Ny besked"}`, message: `${tekst || "(ingen tekst)"}\n\n${info}`, tags: ["speech_balloon"] }) });
  return new Response(null, { status: r.ok ? 204 : 502 });
}
