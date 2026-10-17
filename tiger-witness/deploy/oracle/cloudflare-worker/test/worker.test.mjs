// node --test deploy/oracle/cloudflare-worker/test
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { shouldRetry, retryDelay, forwardHeaders, originUrl, ctEq, hmacHex, edgeHeaders } from "../worker.js";

const env = { ORIGIN: "https://me-witness.hf.space/", TELEGRAM_WEBHOOK_SECRET: "s3cret" };
const ctx = () => { const p = []; return { waitUntil: (x) => p.push(x), p }; };
const tg = (secret, body = '{"update_id":1}') => new Request("https://edge.example/channels/telegram/webhook?x=1",
  { method: "POST", body, headers: { "X-Telegram-Bot-Api-Secret-Token": secret, "content-type": "application/json" } });

test("retry policy", () => {
  assert.equal(shouldRetry(200), false); assert.equal(shouldRetry(401), false);
  assert.equal(shouldRetry(0), true); assert.equal(shouldRetry(503), true); assert.equal(shouldRetry(429), true);
  assert.deepEqual([1, 2, 3, 6, 10].map(retryDelay), [15, 30, 60, 300, 300]);
});

test("headers and url", () => {
  const h = forwardHeaders(new Headers({ Host: "x", "X-Hub-Signature-256": "sha256=ab", "CF-Ray": "1" }));
  assert.deepEqual(h, { "x-hub-signature-256": "sha256=ab" });
  assert.equal(originUrl(env, "/a", "?b"), "https://me-witness.hf.space/a?b");
});

test("unknown path 404, bad telegram secret 401", async () => {
  assert.equal((await worker.fetch(new Request("https://e/x"), env, ctx())).status, 404);
  assert.equal((await worker.fetch(tg("nope"), env, ctx())).status, 401);
});

test("queue mode acks at once and consumer forwards exact bytes", async () => {
  const sent = [];
  const qenv = { ...env, WEBHOOK_QUEUE: { send: async (m) => sent.push(m) } };
  const r = await worker.fetch(tg("s3cret", "héllo"), qenv, ctx(), () => { throw new Error("no sync fetch"); });
  assert.equal(r.status, 200);
  assert.equal(sent.length, 1);
  const calls = [];
  const states = [];
  const mk = (attempts) => ({ body: sent[0], attempts, ack: () => states.push("ack"), retry: (o) => states.push(o) });
  let status = 503;
  const f = async (url, init) => { calls.push([url, new TextDecoder().decode(init.body), init.headers]); return new Response("", { status }); };
  await worker.queue({ messages: [mk(1)] }, qenv, ctx(), f);
  status = 200;
  await worker.queue({ messages: [mk(2)] }, qenv, ctx(), f);
  assert.deepEqual(states, [{ delaySeconds: 15 }, "ack"]);
  assert.equal(calls[0][0], "https://me-witness.hf.space/channels/telegram/webhook?x=1");
  assert.equal(calls[0][1], "héllo");
  assert.equal(calls[0][2]["x-telegram-bot-api-secret-token"], "s3cret");
});

test("sync mode: 503 + wake ping when origin down, 200 when up", async () => {
  const c = ctx();
  const down = await worker.fetch(tg("s3cret"), env, c, async () => { throw new Error("asleep"); });
  assert.equal(down.status, 503);
  assert.equal(c.p.length, 1);
  const up = await worker.fetch(tg("s3cret"), env, ctx(), async () => new Response("", { status: 200 }));
  assert.equal(up.status, 200);
});

test("whatsapp GET verification passes through", async () => {
  const r = await worker.fetch(new Request("https://e/channels/whatsapp/webhook?hub.challenge=42"), env, ctx(),
    async (u) => new Response(u.endsWith("hub.challenge=42") ? "42" : "x", { status: 200 }));
  assert.equal(await r.text(), "42");
});

test("cron pings healthz", async () => {
  const urls = []; const c = ctx();
  await worker.scheduled({}, env, c, async (u) => { urls.push(u); return new Response("{}"); });
  await Promise.all(c.p);
  assert.deepEqual(urls, ["https://me-witness.hf.space/health"]);
});

test("constant-time compare", () => {
  assert.equal(ctEq("abc", "abc"), true); assert.equal(ctEq("abc", "abd"), false);
  assert.equal(ctEq("abc", "abcd"), false); assert.equal(ctEq("", ""), false); assert.equal(ctEq(null, "x"), false);
});

test("whatsapp X-Hub-Signature-256 verified at the edge", async () => {
  const wenv = { ...env, WHATSAPP_APP_SECRET: "app-secret" };
  const body = '{"entry":[]}';
  const good = "sha256=" + await hmacHex("app-secret", body);
  const mk = (sig) => new Request("https://e/channels/whatsapp/webhook", { method: "POST", body,
    headers: { "X-Hub-Signature-256": sig } });
  const ok = async () => new Response("", { status: 200 });
  assert.equal((await worker.fetch(mk(good), wenv, ctx(), ok)).status, 200);
  assert.equal((await worker.fetch(mk("sha256=00"), wenv, ctx(), ok)).status, 401);
  assert.equal((await worker.fetch(mk(good), env, ctx(), ok)).status, 401);   // secret unset: fail closed
});

test("bluebubbles shared secret verified at the edge", async () => {
  const ienv = { ...env, IMESSAGE_WEBHOOK_SECRET: "bb" };
  const mk = (t) => new Request(`https://e/channels/imessage/webhook?token=${t}`, { method: "POST", body: "{}" });
  const ok = async () => new Response("", { status: 200 });
  assert.equal((await worker.fetch(mk("bb"), ienv, ctx(), ok)).status, 200);
  assert.equal((await worker.fetch(mk("no"), ienv, ctx(), ok)).status, 401);
});

test("forwards carry a fresh edge HMAC per attempt; oversize rejected", async () => {
  const senv = { ...env, WITNESS_EDGE_SECRET: "edge" };
  const seen = [];
  const f = async (u, init) => { seen.push(init.headers); return new Response("", { status: 200 }); };
  await worker.fetch(tg("s3cret"), senv, ctx(), f);
  await worker.fetch(tg("s3cret"), senv, ctx(), f);
  assert.match(seen[0]["x-witness-edge-sig"], /^[0-9a-f]{64}$/);
  assert.notEqual(seen[0]["x-witness-edge-nonce"], seen[1]["x-witness-edge-nonce"]);
  const big = new Request("https://e/channels/telegram/webhook", { method: "POST", body: "x".repeat(1_000_001),
    headers: { "X-Telegram-Bot-Api-Secret-Token": "s3cret" } });
  assert.equal((await worker.fetch(big, senv, ctx(), f)).status, 413);
  assert.deepEqual(await edgeHeaders({}, "POST", "/x", new Uint8Array()), {});
});
