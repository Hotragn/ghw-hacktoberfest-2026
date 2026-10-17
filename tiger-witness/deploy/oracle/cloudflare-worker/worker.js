// Cloudflare Worker ingress for chat webhooks (Workers Free: 100K requests/day, Queues 10K ops/day).
// Origin is the Hugging Face Space (https://<user>-witness.hf.space) or any other Witness deployment.
// Why: Telegram/WhatsApp get a stable, always-on endpoint that acks in milliseconds even while the Space is
// asleep or rebuilding. The edge validates the Telegram secret; the origin re-verifies everything
// (X-Telegram-Bot-Api-Secret-Token, X-Hub-Signature-256 over the exact body) and dedupes on dedupe_key,
// so redelivery from the queue or the provider is idempotent.
//
// Two modes:
//   * WEBHOOK_QUEUE bound (recommended): POST is enqueued and acked 200 at once; the queue consumer forwards
//     to the origin and retries with backoff (15s, 30s, ... 5 min) while the Space wakes. Free-plan retention 24h.
//   * no queue: forwarded synchronously (8s timeout); on failure 503 so the provider retries, and a wake-up ping.
// A cron trigger (every 10 min) GETs ORIGIN/health so the Space stays warm (no cold start on the first message)
// and never reaches the free tier's 48h-inactivity sleep. One tiny GET per 10 min: 144 requests/day.
// Provider signatures are verified HERE (cheap rejection, nothing unauthenticated reaches the Space or the queue)
// AND again at the origin. Each check gets (req, env, rawBody) and fails closed when its secret is unset.
export const ROUTES = {
  "/channels/telegram/webhook": async (req, env) =>
    ctEq(req.headers.get("X-Telegram-Bot-Api-Secret-Token"), env.TELEGRAM_WEBHOOK_SECRET),
  "/channels/whatsapp/webhook": async (req, env, raw) => {
    const h = req.headers.get("X-Hub-Signature-256") || "";
    if (!env.WHATSAPP_APP_SECRET || !h.startsWith("sha256=")) return false;
    return ctEq(h.slice(7), await hmacHex(env.WHATSAPP_APP_SECRET, raw));
  },
  "/channels/imessage/webhook": async (req, env) =>   // BlueBubbles relay shared secret (?token=)
    ctEq(new URL(req.url).searchParams.get("token"), env.IMESSAGE_WEBHOOK_SECRET),
};

const MAX_BODY = 1_000_000;
const enc = new TextEncoder();

export function ctEq(a, b) {
  if (!a || !b) return false;
  const x = enc.encode(a), y = enc.encode(b);
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x[i % x.length] ^ y[i % y.length]);
  return d === 0;
}

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function hmacHex(secret, data) {
  const k = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", k, typeof data === "string" ? enc.encode(data) : data));
}

// Worker -> Space HMAC (see witness/edge.py): fresh ts + nonce on EVERY attempt, so queue retries are not replays.
export async function edgeHeaders(env, method, pathQs, body, now = Date.now()) {
  if (!env.WITNESS_EDGE_SECRET) return {};
  const ts = String(Math.floor(now / 1000));
  const nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
  const bodyHash = hex(await crypto.subtle.digest("SHA-256", body || new Uint8Array()));
  const sig = await hmacHex(env.WITNESS_EDGE_SECRET, `${ts}.${nonce}.${method.toUpperCase()}.${pathQs}.${bodyHash}`);
  return { "x-witness-edge-ts": ts, "x-witness-edge-nonce": nonce, "x-witness-edge-sig": sig };
}

const DROP = new Set(["host", "content-length", "connection", "cf-connecting-ip", "cf-ray", "cf-visitor",
  "cf-ipcountry", "x-forwarded-proto", "x-real-ip"]);

export function forwardHeaders(headers) {
  const out = {};
  for (const [k, v] of headers) if (!DROP.has(k.toLowerCase())) out[k.toLowerCase()] = v;
  return out;
}

export function originUrl(env, path, search = "") {
  return env.ORIGIN.replace(/\/$/, "") + path + search;
}

// 2xx done; 4xx is the origin rejecting the payload (bad signature, unknown chat): retrying won't help,
// except 408/425/429. 5xx and network errors (Space asleep/building -> 502/503) are retried.
export function shouldRetry(status) {
  if (status >= 200 && status < 300) return false;
  if (status === 408 || status === 425 || status === 429) return true;
  return status >= 500 || status === 0;
}

export function retryDelay(attempts) {
  return Math.min(300, 15 * 2 ** Math.max(0, attempts - 1));
}

function b64(buf) {
  let s = "";
  const a = new Uint8Array(buf);
  for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000));
  return btoa(s);
}

function unb64(s) {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

async function forward(env, msg, timeoutMs, fetchImpl = fetch) {
  try {
    const body = unb64(msg.body);
    const headers = { ...msg.headers, ...(await edgeHeaders(env, "POST", msg.path + msg.search, body)) };
    const r = await fetchImpl(originUrl(env, msg.path, msg.search), {
      method: "POST", headers, body, signal: AbortSignal.timeout(timeoutMs),
    });
    return r.status;
  } catch (e) {
    return 0;
  }
}

function wake(env, fetchImpl = fetch) {
  return fetchImpl(originUrl(env, "/health"), { signal: AbortSignal.timeout(25000) }).catch(() => {});
}

export default {
  async fetch(req, env, ctx, fetchImpl = fetch) {
    const url = new URL(req.url);
    const check = ROUTES[url.pathname];
    if (!check) return new Response("not found", { status: 404 });
    if (req.method !== "POST" && req.method !== "GET") return new Response("method not allowed", { status: 405 });
    if (Number(req.headers.get("content-length") || 0) > MAX_BODY) return new Response("too large", { status: 413 });
    const raw = req.method === "POST" ? await req.arrayBuffer() : new ArrayBuffer(0);
    if (raw.byteLength > MAX_BODY) return new Response("too large", { status: 413 });
    if (req.method === "POST" && !(await check(req, env, raw))) return new Response("unauthorized", { status: 401 });

    if (req.method === "GET") {   // WhatsApp hub.challenge verification must be answered by the origin
      if (url.pathname !== "/channels/whatsapp/webhook") return new Response("not found", { status: 404 });
      try {
        const headers = { ...forwardHeaders(req.headers), ...(await edgeHeaders(env, "GET", url.pathname + url.search, raw)) };
        const r = await fetchImpl(originUrl(env, url.pathname, url.search),
          { method: "GET", headers, signal: AbortSignal.timeout(25000) });
        return new Response(r.body, { status: r.status, headers: r.headers });
      } catch (e) {
        return new Response("origin unavailable", { status: 503 });
      }
    }

    const msg = { path: url.pathname, search: url.search, headers: forwardHeaders(req.headers),
      body: b64(raw), received_at: Date.now() };
    if (env.WEBHOOK_QUEUE) {
      await env.WEBHOOK_QUEUE.send(msg);
      return new Response("ok", { status: 200 });
    }
    const status = await forward(env, msg, 8000, fetchImpl);
    if (shouldRetry(status)) {
      ctx.waitUntil(wake(env, fetchImpl));
      return new Response("origin unavailable", { status: 503 });
    }
    return new Response("ok", { status: 200 });
  },

  async queue(batch, env, ctx, fetchImpl = fetch) {
    for (const m of batch.messages) {
      const status = await forward(env, m.body, 25000, fetchImpl);
      if (shouldRetry(status)) m.retry({ delaySeconds: retryDelay(m.attempts) });
      else m.ack();
    }
  },

  async scheduled(event, env, ctx, fetchImpl = fetch) {
    ctx.waitUntil(wake(env, fetchImpl));
  },
};
