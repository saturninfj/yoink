// yoink background service worker
// Bridges between browser and the native messaging host.

const HOST_NAME = "com.yoink.host";

// Persistent port to native host (reconnected lazily).
let port = null;
let nextRequestId = 1;
const pendingRequests = new Map();

function ensureConnected() {
  if (port) return port;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (err) {
    console.error("[yoink] connectNative failed:", err);
    return null;
  }
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener((p) => {
    const err = chrome.runtime.lastError;
    console.warn("[yoink] host disconnected:", err?.message || "unknown");
    port = null;
    // Reject all pending requests.
    for (const [id, reject] of pendingRequests.values()) {
      reject(new Error(err?.message || "host disconnected"));
      pendingRequests.delete(id);
    }
  });
  return port;
}

function onHostMessage(msg) {
  if (!msg) return;
  // JSON-RPC response (has id and either result or error)
  if (msg.id !== undefined) {
    const entry = pendingRequests.get(msg.id);
    if (!entry) return;
    pendingRequests.delete(msg.id);
    if (msg.error) {
      entry[1](new Error(msg.error.message || "rpc error"));
    } else {
      entry[0](msg.result);
    }
    return;
  }
  // Notification (method + params, no id)
  if (msg.method) {
    handleNotification(msg.method, msg.params || {});
  }
}

function handleNotification(method, params) {
  if (method === "download.progress") {
    chrome.storage.local.set({ [`dl_progress_${params.download_id}`]: params });
    chrome.runtime
      .sendMessage({ type: "download.progress", payload: params })
      .catch(() => {/* popup closed; ignore */});
  } else if (method === "download.complete") {
    chrome.storage.local.set({ [`dl_complete_${params.download_id}`]: params });
    chrome.runtime
      .sendMessage({ type: "download.complete", payload: params })
      .catch(() => {/* popup closed; ignore */});
    // Browser notification on completion.
    const status = params.status;
    const title = status === "completed" ? "yoink: download complete" : `yoink: ${status}`;
    chrome.notifications.create(`yoink_${params.download_id}`, {
      type: "basic",
      iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
      title,
      message: `Download #${params.download_id} ${status}.`,
      priority: 1,
    });
  }
}

function rpc(method, params = {}) {
  return new Promise((resolve, reject) => {
    const p = ensureConnected();
    if (!p) {
      reject(new Error("cannot connect to native host"));
      return;
    }
    const id = nextRequestId++;
    pendingRequests.set(id, [resolve, reject]);
    p.postMessage({ jsonrpc: "2.0", method, params, id });
  });
}

// ----- Interception (toggleable, default OFF) -----

async function shouldIntercept() {
  const { interceptDownloads = false } = await chrome.storage.local.get(
    "interceptDownloads"
  );
  return interceptDownloads;
}

chrome.downloads.onCreated.addListener(async (item) => {
  if (!(await shouldIntercept())) return;
  const url = item.finalUrl || item.url;
  if (!url || /^(blob|data|file|about):/i.test(url)) return;

  // Cancel the browser download; we'll route through yoink.
  chrome.downloads.cancel(item.id, () => {
    // Also erase from the browser's list to avoid clutter.
    chrome.downloads.erase({ id: item.id });
  });

  try {
    const result = await rpc("download.start", {
      url,
      filename: item.filename ? item.filename.split(/[\\/]/).pop() : undefined,
      referer: item.referrer || undefined,
    });
    console.log("[yoink] intercepted →", result);
  } catch (err) {
    console.error("[yoink] intercept failed:", err.message);
    chrome.notifications.create({
      type: "basic",
      iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
      title: "yoink: intercept failed",
      message: `${url.slice(0, 80)} → ${err.message}`,
      priority: 2,
    });
  }
});

// ----- Message router from popup / options -----

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "rpc") {
    rpc(msg.method, msg.params || {})
      .then((result) => sendResponse({ ok: true, result }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }
  if (msg.type === "ping_host") {
    rpc("ping")
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
});

// Connect on startup so the host is warm.
chrome.runtime.onStartup.addListener(() => {
  ensureConnected();
});
chrome.runtime.onInstalled.addListener(() => {
  ensureConnected();
});
