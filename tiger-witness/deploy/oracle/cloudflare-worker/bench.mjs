// node bench.mjs : in-process p50/p95 of the Worker's webhook ack path (edge verify + enqueue), excluding network.
import worker, { hmacHex } from "./worker.js";
const env = { ORIGIN: "https://x.hf.space", TELEGRAM_WEBHOOK_SECRET: "t", WHATSAPP_APP_SECRET: "w", WITNESS_EDGE_SECRET: "e",
  WEBHOOK_QUEUE: { send: async () => {} } };
const ctx = { waitUntil() {} };
const body = JSON.stringify({ entry: [{ changes: [{ value: { messages: [{ from: "1", type: "text", text: { body: "hi" } }] } }] }] });
const sig = "sha256=" + await hmacHex("w", body);
async function run(name, mk, n = 2000) {
  const xs = [];
  for (let i = 0; i < n; i++) { const r = mk(); const t = performance.now(); await worker.fetch(r, env, ctx); xs.push(performance.now() - t); }
  xs.sort((a, b) => a - b);
  console.log(JSON.stringify({ path: name, p50_ms: +xs[n / 2 | 0].toFixed(3), p95_ms: +xs[Math.floor(n * 0.95)].toFixed(3), n }));
}
await run("telegram_ack(queue)", () => new Request("https://e/channels/telegram/webhook", { method: "POST", body: '{"update_id":1}',
  headers: { "X-Telegram-Bot-Api-Secret-Token": "t" } }));
await run("whatsapp_hmac_ack(queue)", () => new Request("https://e/channels/whatsapp/webhook", { method: "POST", body,
  headers: { "X-Hub-Signature-256": sig } }));
