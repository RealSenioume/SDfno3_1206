# DSH bundle: lolping-intents

**Status:** skeleton (v0.1.0), first working version delivered with lolping v0.4.0.
**Location:** `plugin/lolping-intents/`.

## Why

lolping is a desktop ping wheel. In DSH mode, slices with an injected action
write one JSON line to `%APPDATA%\lolping-desktop\intents.jsonl` (plus a PNG for
`capture_region`). This bundle is the DSH side of that bridge: it lets the agent
read those intents and act on the captured region.

The boundary is deliberate:

- lolping never talks to the game and never injects input;
- the bundle is read-only: it watches/reads a file and registers one tool;
- either side can crash without taking the other down.

```
lolping (PyQt5)                         DSH (Harness profile)
  commit slice                              lolping-intents bundle
    -> hide overlay, wait                     - tool: lolping_intents
    -> grab 640x360 PNG                       - watcher: logs new lines
    -> append intents.jsonl  ------------->   - agent reads screenshot
```

## Package layout

| File | Purpose |
| --- | --- |
| `package.json` | bundle manifest: `type: module`, `exports` (`.`, locale, icon), `files`, `dsh.bundle.patch` |
| `cordis.patch.yml` | inserts the `lolping-intents` Host row with `config: {watch: true}` |
| `index.js` | `export const name`, `inject = ['tools']`, `apply(ctx, config)`; registers `lolping_intents`, optional watcher |
| `lib/intents.js` | pure Node helpers: `intentsPath`, `parseIntents`, `readIntents`, `pollNew`, `summary` |
| `locale/en.json`, `locale/zh.json` | Plugin Manager title/description |
| `icon.svg` | original ring+crosshair icon |
| `test/intents.test.mjs` | Node tests for the log helpers |

## Tool contract

`lolping_intents({limit})` returns:

```json
{
  "path": "C:/Users/x/AppData/Roaming/lolping-desktop/intents.jsonl",
  "count": 1,
  "intents": [
    {
      "ts": "2026-11-25T16:20:29.956+08:00",
      "sector": 4,
      "name": "Enemy Missing",
      "action": "capture_region",
      "x": 826, "y": 237,
      "region": [506, 57, 640, 360],
      "screenshot": "C:/Users/x/AppData/Roaming/lolping-desktop/regions/region-*.png",
      "text": "", "score": 0, "mode": "image"
    }
  ]
}
```

The screenshot path is what the agent needs for vision; the tool itself does not
read pixels, so the model's own image tools stay in charge.

## Install

Use DSH's bundle installer — do **not** hand-edit the profile's `package.json`
or `cordis.patch.yml`:

1. DSH **Settings → Plugins → install bundle**, target the absolute path of
   `plugin/lolping-intents`;
2. or ask a DSH agent session to call `plugin_manager` with
   `action: install_bundle` and that directory as `target`.

The installer writes the profile manifest/patch and pnpm links the package.
After installation the row appears as **LoLPing intents**.

## Verify

1. Plugin row shows the title/icon above;
2. Ask the agent: *"read my latest LoLPing intents"* → it calls
   `lolping_intents` and returns the JSONL entries;
3. In lolping: DSH mode → commit **Enemy Missing** → ask again: the new
   `capture_region` record and its PNG path are present;
4. Watcher: with `watch: true`, new commits log
   `[lolping-intents] Enemy Missing · capture_region · score 0` in the Host log.

## Config

| Key | Default | Meaning |
| --- | --- | --- |
| `intentsPath` | `%APPDATA%\lolping-desktop\intents.jsonl` | override for tests or a custom app-data dir |
| `watch` | `true` | tail the log and log new intents (stays quiet when the file is absent) |

## Development

```powershell
# Node >= 20; DSH ships one under resources/runtime
node plugin/lolping-intents/test/intents.test.mjs
```

Python-side static checks: `tests/test_dsh_plugin.py` (manifest, patch, locale,
icon, `node --check` when Node is available).

## Limits and next steps

- **No automatic agent turn**: the watcher only logs. Next step: on a
  `capture_region` intent, call `agent.followup(createUserMessage(...))` with
  the screenshot so DSH reacts without being asked.
- **No result write-back**: intents are one-way. Add `results.jsonl` so lolping
  can show "DSH handled it".
- `window_title` is still empty in intents; region size is fixed 640×360
  (decide 320×180).
- Multi-user collaboration remains future work; the file bridge is
  single-machine by design.
