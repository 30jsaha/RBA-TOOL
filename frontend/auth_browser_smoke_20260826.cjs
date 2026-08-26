const fs = require('fs');

const BASE_URL = 'http://localhost:5175';
const BACKEND_URL = 'http://localhost:5000';
const DEBUG_PORT = 9225;
const CREDS = JSON.parse(fs.readFileSync('E:/rba-tool/UAT/RBA-TOOL/backend/reports/auth_browser_user_20260826.json', 'utf8'));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
  return res.json();
}

async function connectBrowser() {
  const version = await getJson(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });

  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();

  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result || {});
      return;
    }

    const key = `${message.sessionId || 'browser'}:${message.method || ''}`;
    const handlers = listeners.get(key) || [];
    for (const handler of handlers) handler(message.params || {});
  });

  const send = (method, params = {}, sessionId) => {
    const id = nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  };

  const on = (method, sessionId, handler) => {
    const key = `${sessionId || 'browser'}:${method}`;
    const handlers = listeners.get(key) || [];
    handlers.push(handler);
    listeners.set(key, handlers);
    return () => {
      const next = (listeners.get(key) || []).filter((fn) => fn !== handler);
      listeners.set(key, next);
    };
  };

  return { ws, send, on };
}

async function createPage(browser, url) {
  const { targetId } = await browser.send('Target.createTarget', { url });
  const attached = await browser.send('Target.attachToTarget', { targetId, flatten: true });
  const sessionId = attached.sessionId;
  await browser.send('Page.enable', {}, sessionId);
  await browser.send('Runtime.enable', {}, sessionId);
  await browser.send('Network.enable', {}, sessionId);
  return { targetId, sessionId };
}

async function waitForLoad(browser, sessionId, timeoutMs = 15000) {
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        off();
        reject(new Error('Timed out waiting for load event'));
      }, timeoutMs);
      const off = browser.on('Page.loadEventFired', sessionId, () => {
        clearTimeout(timer);
        off();
        resolve();
      });
    });
  } catch {
    await sleep(2000);
  }
}

async function evaluate(browser, sessionId, expression) {
  const result = await browser.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  return result?.result?.value;
}

async function waitForPath(browser, sessionId, expectedPath, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const path = await evaluate(browser, sessionId, 'window.location.pathname');
    if (path === expectedPath) return path;
    await sleep(500);
  }
  const actual = await evaluate(browser, sessionId, 'window.location.pathname');
  throw new Error(`Timed out waiting for path ${expectedPath}; saw ${actual}`);
}

async function login(browser, sessionId) {
  const email = JSON.stringify(CREDS.email);
  const password = JSON.stringify(CREDS.password);
  const loginResult = await evaluate(
    browser,
    sessionId,
    `(() => {
      return fetch('${BACKEND_URL}/api/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: ${email}, password: ${password} }),
      })
        .then(async (res) => ({ status: res.status, body: await res.json() }))
        .catch((error) => ({ status: 0, error: String(error) }));
    })()`
  );

  if (!loginResult || loginResult.status !== 200 || !loginResult.body?.access) {
    throw new Error(`Browser login failed: ${JSON.stringify(loginResult)}`);
  }

  await evaluate(browser, sessionId, `window.location.assign('/common-dashboard')`);
  await waitForPath(browser, sessionId, '/common-dashboard', 20000);
}

async function invalidateRefreshCookie(browser, sessionId) {
  await evaluate(browser, sessionId, `(() => {
    const match = document.cookie.split(';').map((part) => part.trim()).find((part) => part.startsWith('rba_refresh_csrf='));
    const csrf = match ? decodeURIComponent(match.split('=').slice(1).join('=')) : '';
    return fetch('${BACKEND_URL}/api/auth/logout', {
      method: 'POST',
      credentials: 'include',
      headers: csrf ? { 'X-CSRF-TOKEN': csrf } : {},
    }).then((res) => res.status).catch((error) => ({ error: String(error) }));
  })()`);
}

function attachNetworkCapture(browser, sessionId, capture) {
  const requestUrls = new Map();

  browser.on('Network.requestWillBeSent', sessionId, (params) => {
    requestUrls.set(params.requestId, params.request.url);
  });

  browser.on('Network.requestWillBeSentExtraInfo', sessionId, (params) => {
    const url = requestUrls.get(params.requestId) || '';
    if (!url.includes('/api/auth/refresh') && !url.includes('/api/auth/me')) return;
    capture.push({
      type: 'request-extra',
      url,
      hasCookieHeader: Boolean(params.headers?.Cookie),
      hasAuthorizationHeader: Boolean(params.headers?.Authorization),
    });
  });

  browser.on('Network.responseReceived', sessionId, (params) => {
    const url = params.response?.url || '';
    if (!url.includes('/api/auth/refresh') && !url.includes('/api/auth/me')) return;
    capture.push({
      type: 'response',
      url,
      status: params.response?.status,
    });
  });
}

async function run() {
  const browser = await connectBrowser();
  const results = {};
  const networkCapture = [];

  try {
    const page = await createPage(browser, `${BASE_URL}/`);
    attachNetworkCapture(browser, page.sessionId, networkCapture);
    await waitForLoad(browser, page.sessionId);

    await login(browser, page.sessionId);
    results.login = await evaluate(browser, page.sessionId, 'window.location.pathname');
    results.storage = await evaluate(browser, page.sessionId, '({ localKeys: Object.keys(localStorage), sessionKeys: Object.keys(sessionStorage) })');

    await browser.send('Page.reload', { ignoreCache: true }, page.sessionId);
    await waitForLoad(browser, page.sessionId);
    results.browserRefresh = await waitForPath(browser, page.sessionId, '/common-dashboard', 20000);

    const gstPage = await createPage(browser, `${BASE_URL}/gst`);
    attachNetworkCapture(browser, gstPage.sessionId, networkCapture);
    await waitForLoad(browser, gstPage.sessionId);
    results.newTabProtectedRoute = await waitForPath(browser, gstPage.sessionId, '/gst', 20000);

    const uploadPage = await createPage(browser, `${BASE_URL}/upload-sheets`);
    attachNetworkCapture(browser, uploadPage.sessionId, networkCapture);
    await waitForLoad(browser, uploadPage.sessionId);
    results.directProtectedUrl = await waitForPath(browser, uploadPage.sessionId, '/upload-sheets', 20000);

    const reopenPage = await createPage(browser, `${BASE_URL}/common-dashboard`);
    attachNetworkCapture(browser, reopenPage.sessionId, networkCapture);
    await waitForLoad(browser, reopenPage.sessionId);
    results.closeReopen = await waitForPath(browser, reopenPage.sessionId, '/common-dashboard', 20000);

    await invalidateRefreshCookie(browser, page.sessionId);
    const invalidRefreshPage = await createPage(browser, `${BASE_URL}/common-dashboard`);
    attachNetworkCapture(browser, invalidRefreshPage.sessionId, networkCapture);
    await waitForLoad(browser, invalidRefreshPage.sessionId);
    results.invalidRefresh = await waitForPath(browser, invalidRefreshPage.sessionId, '/', 20000);

    await login(browser, page.sessionId);
    await evaluate(browser, page.sessionId, `(() => {
      document.querySelector('.logout-btn')?.click();
      return true;
    })()`);
    results.logout = await waitForPath(browser, page.sessionId, '/', 20000);

    const afterLogoutPage = await createPage(browser, `${BASE_URL}/gst`);
    attachNetworkCapture(browser, afterLogoutPage.sessionId, networkCapture);
    await waitForLoad(browser, afterLogoutPage.sessionId);
    results.newTabAfterLogout = await waitForPath(browser, afterLogoutPage.sessionId, '/', 20000);

    results.network = networkCapture;

    fs.writeFileSync('E:/rba-tool/UAT/RBA-TOOL/backend/reports/auth_browser_checks_20260826.json', JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally {
    try { browser.ws.close(); } catch {}
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
