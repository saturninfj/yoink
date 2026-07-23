# Browser extension — yoink

Manifest V3 extension for Chrome / Brave / Edge / Chromium that bridges downloads
to the yoink native host.

## Dev install (unpacked)

1. **Install the native host manifest** (Chrome reads this to find the host):

   ```bash
   cd ~/Projects/yoink
   uv run yoink install-browser-host \
     --browser chrome \
     --extension-id <your-extension-id>
   ```

   For dev (before you know the extension ID), omit `--extension-id`:

   ```bash
   uv run yoink install-browser-host --browser chrome
   ```

2. **Load the extension**:
   - Open `chrome://extensions`
   - Enable **Developer mode** (top-right)
   - **Load unpacked** → select `~/Projects/yoink/extension/`
   - Note the generated extension ID (e.g. `abcdefghijklmnopqrstuvwxyz`)

3. **Re-install host with the real ID** (recommended for security):

   ```bash
   uv run yoink install-browser-host --browser chrome \
     --extension-id abcdefghijklmnopqrstuvwxyz
   ```

4. **Test**:
   - Click the yoink icon in the toolbar
   - Status dot should be green ("host connected")
   - Paste a URL, click "yoink it"

## Manifest V3 quirks

- The service worker (background.js) is **not persistent** — Chrome kills it after
  ~30s of inactivity. We reconnect to the native host lazily on first RPC.
- Interception of `chrome.downloads.onCreated` requires the `downloads`
  permission and is **off by default** (toggle in settings).
- Native messaging host path must be absolute and the wrapper must be executable.

## Firefox

The extension uses standard WebExtension APIs (no Chrome-specific calls beyond
`connectNative`/`runtime.sendMessage` which Firefox also supports). To install:

1. `uv run yoink install-browser-host --browser firefox --extension-id yoink@saturninfj`
2. Load `about:debugging` → This Firefox → Load Temporary Add-on → select
   `extension/manifest.json`

## Uninstall

```bash
uv run yoink uninstall-browser-host --browser chrome
```

This removes only the manifest; the host wrapper at `~/.yoink/yoink-host.sh`
is left in place.
