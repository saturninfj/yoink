const DEFAULTS = {
  interceptDownloads: false,
  connections: 8,
  outputDir: "",
};

const els = {
  intercept: document.getElementById("interceptDownloads"),
  connections: document.getElementById("connections"),
  outputDir: document.getElementById("outputDir"),
  save: document.getElementById("save"),
  saved: document.getElementById("saved"),
};

async function load() {
  const cur = await chrome.storage.local.get(DEFAULTS);
  els.intercept.checked = cur.interceptDownloads;
  els.connections.value = cur.connections;
  els.outputDir.value = cur.outputDir || "";
}

els.save.addEventListener("click", async () => {
  await chrome.storage.local.set({
    interceptDownloads: els.intercept.checked,
    connections: Number(els.connections.value) || 8,
    outputDir: els.outputDir.value.trim(),
  });
  els.saved.classList.add("show");
  setTimeout(() => els.saved.classList.remove("show"), 1500);
});

load();
