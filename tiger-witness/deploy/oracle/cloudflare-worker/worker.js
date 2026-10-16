// Optional Cloudflare Worker ingress for chat webhooks (free plan: 100K requests/day).
// Why: gives Telegram/WhatsApp a stable, always-on HTTPS endpoint even while the Oracle VM reboots, and keeps the
// VM's IP out of provider dashboards. It validates the provider's secret at the edge, then forwards verbatim.
// If the origin is down it returns 503 so Telegram/WhatsApp retry later (both retry with backoff; the API's
// dedupe_key makes retries idempotent).
const ROUTES = {
  "/channels/telegram/webhook": (req, env) =>
    req.headers.get("X-Telegram-Bot-Api-Secret-Token") === env.TELEGRAM_WEBHOOK_SECRET,
  "/channels/whatsapp/webhook": () => true,   // origin verifies X-Hub-Signature-256 with WHATSAPP_APP_SECRET
  "/channels/imessage/webhook": () => true,   // origin verifies IMESSAGE_WEBHOOK_SECRET
};

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const check = ROUTES[url.pathname];
    if (!check) return new Response("not found", { status: 404 });
    if (req.method === "POST" && !check(req, env)) return new Response("unauthorized", { status: 401 });
    const target = env.ORIGIN.replace(/\/$/, "") + url.pathname + url.search;
    try {
      const r = await fetch(target, {
        method: req.method,
        headers: req.headers,
        body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
        signal: AbortSignal.timeout(8000),
      });
      return new Response(r.body, { status: r.status, headers: r.headers });
    } catch (e) {
      return new Response("origin unavailable", { status: 503 });
    }
  },
};
