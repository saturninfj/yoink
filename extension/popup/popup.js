// yoink popup: list downloads, submit new URL.

const $ = (sel) => document.querySelector(sel);
const list = $("#downloads");
const urlInput = $("#url-input");
const addForm = $("#add-form");
const hostDot = $("#host-dot");
const hostLabel = $("#host-label");
const refreshBtn = $("#refresh");

function rpc(method, params = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: "rpc", method, params },
      (resp) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (!resp || !resp.ok) {
          reject(new Error(resp?.error || "rpc failed"));
          return;
        }
        resolve(resp.result);
      }
    );
  });
}

async function pingHost() {
  hostDot.className = "dot unknown";
  hostLabel.textContent = "checking host…";
  try {
    await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "ping_host" }, (resp) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!resp || !resp.ok) return reject(new Error(resp?.error || "no host"));
        resolve();
      });
    });
    hostDot.className = "dot ok";
    hostLabel.textContent = "host connected";
  } catch (err) {
    hostDot.className = "dot err";
    hostLabel.textContent = `host offline: ${err.message}`;
  }
}

function formatBytes(n) {
  if (n == null) return "?";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MiB`;
  return `${(n / 1024 ** 3).toFixed(2)} GiB`;
}

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec) return "";
  if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`;
  if (bytesPerSec < 1024 ** 2) return `${(bytesPerSec / 1024).toFixed(1)} KiB/s`;
  return `${(bytesPerSec / 1024 ** 2).toFixed(1)} MiB/s`;
}

function renderDownload(dl) {
  const total = dl.total_size || dl.total;
  const downloaded = dl.downloaded_size ?? dl.downloaded ?? 0;
  const pct = total ? Math.min(100, (downloaded / total) * 100) : 0;

  const name = (dl.output_path || dl.output || "download").split(/[\\/]/).pop();

  const li = document.createElement("li");
  li.className = `status-${dl.status}`;
  li.dataset.id = dl.id;

  const nameEl = document.createElement("div");
  nameEl.className = "dl-name";
  nameEl.textContent = name;
  nameEl.title = dl.url || "";
  li.appendChild(nameEl);

  const bar = document.createElement("div");
  bar.className = "dl-bar";
  const fill = document.createElement("div");
  fill.style.width = `${pct}%`;
  bar.appendChild(fill);
  li.appendChild(bar);

  const meta = document.createElement("div");
  meta.className = "dl-meta";

  const left = document.createElement("span");
  left.textContent = `${formatBytes(downloaded)} / ${formatBytes(total)}`;
  meta.appendChild(left);

  const right = document.createElement("span");
  const pill = document.createElement("span");
  pill.className = "status-pill";
  pill.textContent = dl.status;
  right.appendChild(pill);
  meta.appendChild(right);

  li.appendChild(meta);
  return li;
}

function renderDownloads(dls) {
  list.innerHTML = "";
  if (!dls || !dls.length) {
    const empty = document.createElement("li");
    empty.style.color = "var(--muted)";
    empty.style.textAlign = "center";
    empty.textContent = "no downloads yet";
    list.appendChild(empty);
    return;
  }
  for (const dl of dls) {
    list.appendChild(renderDownload(dl));
  }
}

async function refreshDownloads() {
  try {
    const result = await rpc("download.list", { limit: 20 });
    renderDownloads(result.downloads || []);
  } catch (err) {
    console.warn("[yoink] list failed:", err);
  }
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  urlInput.value = "";
  try {
    await rpc("download.start", { url });
    refreshBtn.click();
  } catch (err) {
    alert(`yoink failed: ${err.message}`);
  }
});

refreshBtn.addEventListener("click", refreshDownloads);

// Live progress updates from background.
chrome.runtime.onMessage.addListener((msg) => {
  if (!msg) return;
  if (msg.type === "download.progress" || msg.type === "download.complete") {
    refreshDownloads();
  }
});

// Wire options link.
$("#open-options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

pingHost();
refreshDownloads();
