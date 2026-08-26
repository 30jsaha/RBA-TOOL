const DEBUG_PORT = 9225;
const BASE_URL = 'http://localhost:5175';

async function getJson(url) {
  const res = await fetch(url);
  return res.json();
}

async function main() {
  const version = await getJson(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  let id = 1;
  const pending = new Map();
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message));
      else resolve(msg.result || {});
    }
  });
  const send = (method, params = {}, sessionId) => {
    const payload = { id: id++, method, params };
    if (sessionId) payload.sessionId = sessionId;
    ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => pending.set(payload.id, { resolve, reject }));
  };

  const { targetId } = await send('Target.createTarget', { url: BASE_URL });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  await send('Page.enable', {}, sessionId);
  await send('Runtime.enable', {}, sessionId);
  await send('Page.navigate', { url: BASE_URL }, sessionId);
  await new Promise((r) => setTimeout(r, 3000));
  const result = await send('Runtime.evaluate', {
    expression: `(() => fetch('http://localhost:5000/api/health', { credentials: 'include' }).then(async r => ({ ok: r.ok, status: r.status, text: await r.text() })).catch(e => ({ error: String(e) })))()`,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  console.log(JSON.stringify(result.result.value, null, 2));
  ws.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
