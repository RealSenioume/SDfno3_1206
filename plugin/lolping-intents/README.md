# lolping-intents (DSH bundle)

Bridges LoLPing's ping intents into DSH. LoLPing writes
`%APPDATA%\lolping-desktop\intents.jsonl` on every committed slice that has an
injected action (DSH mode). This bundle:

- registers the **`lolping_intents`** tool (read the last N intents, including
  `region` and `screenshot` for `capture_region` intents);
- optionally watches the log (`watch: true`) and logs new intents
  (`[lolping-intents] Enemy Missing · capture_region · score 88`).

It is read-only: no game interaction, no input injection.

## Files

| File | Purpose |
| --- | --- |
| `package.json` | bundle manifest (`dsh.bundle.patch`, exports, locale, icon) |
| `cordis.patch.yml` | inserts the `lolping-intents` Host row |
| `index.js` | `apply(ctx, config)`: tool registration + optional watcher |
| `lib/intents.js` | pure log parsing (`readIntents`, `pollNew`, `summary`) |
| `locale/*.json` | Plugin Manager title / description (en, zh) |
| `test/intents.test.mjs` | Node unit tests for the parsing helpers |

## Install

The supported path is DSH's bundle installer (it writes the profile's
manifest/patch and runs pnpm for you):

1. In DSH: **Settings → Plugins → install bundle**, target this directory
   (absolute path `plugin/lolping-intents` inside the lolping repo).
2. Or ask a DSH agent session to call `plugin_manager` with
   `action: install_bundle` and this directory as `target`.

Do **not** hand-edit the profile's `package.json` / `cordis.patch.yml`.

## Verify

1. The plugin row appears as **LoLPing intents** with this icon.
2. Ask the agent: *"read my latest LoLPing intents"* → it should call
   `lolping_intents` and return the JSONL entries.
3. Turn on DSH mode in lolping, commit **Enemy Missing**, then ask the agent to
   read the latest intent: it should see the `capture_region` record and the
   screenshot path.

## Limits (skeleton stage)

- No automatic agent turn yet: the watcher only logs. A follow-up can call
  `agent.followup(createUserMessage(...))` with the screenshot so DSH reacts
  without being asked.
- No result write-back: intents are one-way (lolping → DSH). A result log is
  planned so lolping can show "DSH handled it".
- Model vision support was verified M0-style (the current model consumes
  images); the tool only exposes the path, the agent reads it with its normal
  image-capable tools.

## Development

```powershell
# Node tests (Node >= 20; DSH ships one under resources/runtime)
node plugin/lolping-intents/test/intents.test.mjs
```
