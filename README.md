English | [简体中文](README.zh-CN.md)

# Just another LoL ping like DSH tool

A desktop ping-wheel overlay for Windows 11, in the visual style of the League
of Legends ping wheel. Hold a modifier key and a mouse button, drag toward one
of eight labelled sectors, and release. The wheel closes, a short burst confirms
the choice, and the ping is appended to a local log file.

**lolping is not an in-game tool.** It does not read or write League of Legends
memory, does not inject into or communicate with the game process, does not use
the Riot API, and the lolping process itself opens no network connections: no
sockets, HTTP, DNS or telemetry. It is an ordinary desktop overlay: it draws a
translucent wheel at the mouse cursor and records the ping the user picked in a
local JSONL file. The one network-adjacent action is deliberate and
user-triggered: in DSH mode, committing **On My Way** hands a search URL to the
default browser, so the request is made by that browser, not by lolping. The
optional DSH bundle also only reads local intent files.

The project ships no third-party artwork or audio. Slice icons are original
vector `QPainterPath` geometry generated in `src/lolping/assets.py`, and the
sound cues are synthesised in `src/lolping/sounds.py`, so the repository
contains no Riot Games assets and no binary media files.

- Version: **0.4.0**
- Platform: **Windows 11** (64-bit)
- Runtime: **Python 3.14**, **PyQt5 5.15.11**, **pynput 1.8.2**
- No other runtime dependencies; lolping itself makes no network connections
  (DSH-mode searches open the default browser, which does)
## Download

**Windows v0.4.0** - `lolping-0.4.0-win64.zip`, 36.7 MB, SHA-256
`dd80f3b4e669a3e117e112f7b4f5850829f5c2f6c27283a0797c0defb7e66d3a`.
Unzip it into an empty folder and run `lolping\lolping.exe`; the `_internal`
folder must stay next to it. The executable is unsigned, so Windows SmartScreen
may ask for confirmation.

- [Download lolping-0.4.0-win64.zip](release/lolping-0.4.0-win64.zip)



## Features

- **Jarvis data-instrument theme** (the only skin in v0.4.0): three rotating
  observation windows over baked Hong Kong contour, landmark and isotherm bands,
  arc-set landmark names with latitude/longitude micro-labels, PCB-style traces,
  a telemetry band outside the outer ring and a real frosted-glass backdrop
  captured from the desktop.
- Eight-sector radial menu, opened at the mouse cursor by a hold-and-drag gesture
  (default: hold **Alt + left mouse button**). A click without dragging sends the
  centre (basic) ping; releasing in the dead zone, pressing **Esc** or clicking
  another mouse button cancels.
- Default sectors, clockwise from 3 o'clock: On My Way, All-In, Assist Me, Need
  Vision, Enemy Missing, Enemy Vision, Danger, Push. All eight are renameable and
  each slice has a vector icon with an optional custom PNG.
- Commit choreography: rings shrink around the chosen slice, ring content fades
  while the shape holds, the sector name pops and a mark burst plays at the centre.
- Four synthesised sound cues - open, hover tick, commit chime and cancel sweep.
  Sound is off by default; volume starts at 50%.
- **DSH mode** (Settings -> DSH mode): slices without an injected action are
  dimmed and cannot be selected. Injected slices are **Enemy Missing** (region
  capture) and **On My Way** (screen search); the search slice shows the
  640x360 capture frame and the 320x180 OCR frame while it is hovered.
- **Intent pipeline**: every injected commit appends one JSON line to
  `%APPDATA%\lolping-desktop\intents.jsonl`; a capture also saves a 640x360 PNG
  under `regions/`.
- **On My Way text search**: captures the centre 320x180 region, runs the offline
  Windows OCR (no network), centre-weights the recognised lines, scores usability
  (0-100) and opens a text search in the default browser (>=60 text; 25-60 text
  plus the screenshot on the clipboard; <25 is the image-search path reserved for
  the next milestone).
- **Settings window**: night mode, **Apply** without closing, and a live 280x280
  wheel preview over a live frosted capture of the desktop. The preview loops the
  wake/select/exit choreography and pauses while the desktop wheel is on screen.
- Configurable trigger (Ctrl/Alt/Shift/Win plus left/right/middle/X1/X2), wheel
  radius, dead zone, Jarvis backdrop opacity, icon size/labels, mark duration,
  sound, pause hotkey and start with Windows.
- Translucent, frameless, always-on-top overlay that does not steal focus from
  the window underneath; one overlay per monitor, positioned under the cursor;
  single instance.
- Tray menu (Settings, ping history, config folder, pause/resume, quit), local
  JSONL logs and an optional latency probe; tolerant configuration loading.
- **DSH bundle skeleton** in `plugin/lolping-intents`: exposes the intent log as
  the `lolping_intents` tool and tails it, so the agent can read captures.

## Quick start

```powershell
git clone https://github.com/RealSenioume/SDfno3_1206
cd SDfno3_1206

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:PYTHONPATH = "src"   # run from the source tree without installing it
python -m lolping
```

Already have the files? Skip the first two lines and `cd` into the folder that
contains `src`, `requirements.txt` and `pyproject.toml`.

lolping starts in the system tray. Hold **Alt**, press and hold the **left
mouse button**, drag away from the cursor position, and release over the sector
you want. Press **Esc**, click the right mouse button, or release within the
dead zone to cancel. **Ctrl+Shift+Q** pauses or resumes pinging; quit from the tray menu.

A packaged executable can be built from source as described in
`docs/07-build-and-release.md`.

## Sending a ping

1. Hold **Alt** and press the **left mouse button**. The wheel appears where the
   cursor is.
2. Drag away from the centre. The sector under the cursor is emphasised, its
   icon grows and its name is shown in the centre.
3. Release the mouse button to commit. A burst is drawn at the wheel centre and
   one line is written to `pings.jsonl`.
4. To cancel, release the button within the dead zone (34 px by default), press
   **Esc**, or click the right mouse button while the wheel is open.

| Sector | Clock position | Default label | Default icon |
| --- | --- | --- | --- |
| 0 | 3 o'clock | On My Way | `on_my_way` |
| 1 | 4:30 | All-In | `all_in` |
| 2 | 6 o'clock | Assist Me | `assist` |
| 3 | 7:30 | Need Vision | `vision` |
| 4 | 9 o'clock | Enemy Missing | `missing` |
| 5 | 10:30 | Enemy Vision | `enemy_vision` |
| 6 | 12 o'clock | Danger | `danger` |
| 7 | 1:30 | Push | `push` |

The icon ids `danger` and `generic` are also available and can be assigned to
any slice in Settings. A custom PNG can replace a slice's icon; see
`docs/05-user-manual.md`.

## Command line

```text
python -m lolping [--config PATH] [--latency-probe] [--debug] [--self-test]
```

| Flag | Meaning |
| --- | --- |
| `--config PATH` | Use `PATH` instead of `%APPDATA%\lolping-desktop\config.json`. |
| `--latency-probe` | Record one line per gesture in `latency.jsonl` (`frame_ms`, `commit_ms`). Intended for measurements, not normal use. |
| `--debug` | Enable verbose diagnostic logging. |
| `--self-test` | Run the built-in headless self-test and exit; useful after installation. |

## Files

All user data lives in `%APPDATA%\lolping-desktop\`:

| File | Contents |
| --- | --- |
| `config.json` | Settings written by the Settings dialog. Created on first save; loaded tolerantly. |
| `pings.jsonl` | One JSON object per committed ping: `ts`, `sector`, `name`, `x`, `y`. |
| `intents.jsonl` | One JSON object per injected commit in DSH mode: sector, action, region, screenshot path, OCR text/score/mode. |
| `regions/` | PNG captures written by injected actions (`region-*.png`, `search-*.png`). |
| `latency.jsonl` | Written only with `--latency-probe`: `ts`, `frame_ms`, `commit_ms`. |
| `lolping.log` | Rolling diagnostic log; attach it when reporting a problem. |

## Documentation

| Document | Purpose |
| --- | --- |
| `docs/00-interfaces.md` | Frozen module interface contract (internal). |
| `docs/01-proposal.md` | Problem, objectives, scope, technology choice, risks, plan. |
| `docs/02-requirements.md` | User stories, functional and non-functional requirements, use cases. |
| `docs/03-design.md` | Design rationale and module descriptions (maintainers). |
| `docs/04-test-plan.md` | Test strategy, matrix, test cases, measurement protocols. |
| `docs/05-user-manual.md` | Installation, gesture, settings reference, troubleshooting. |
| `docs/06-report-outline.md` | Outline and evidence plan for the final report. |
| `docs/07-build-and-release.md` | Packaging and release steps. |
| `docs/08-report-draft.md` | Full report draft, with measurement placeholders marked TBD. |
| `docs/10-dsh-plugin.md` | DSH bundle skeleton, install/verify steps and limits. |
| `docs/09-roadmap.md` | Living roadmap: now / next / later, including the DSH plugin and multi-user research (Chinese: `docs/09-roadmap.zh-CN.md`). |

## Limitations

- **Exclusive fullscreen.** Windows desktop overlays cannot normally be shown
  over an application that holds the display in exclusive fullscreen mode.
  Run the game in borderless or windowed mode if the wheel must be visible.
- **Elevated windows.** Under Windows User Interface Privilege Isolation, a
  normal-privilege lolping cannot draw over, or receive input from, windows
  running as administrator. Run lolping at the same or a higher integrity level
  when this is required.
- **Global input hooks.** Some security software restricts global mouse and
  keyboard hooks. lolping supervises and restarts a dead listener, but the
  application may need to be allow-listed.
- **Trigger conflicts.** Alt + left mouse button is used by some applications
  for their own shortcuts. The trigger is configurable; change it in Settings.
- **Sound overlap.** The Windows `winsound` API plays one asynchronous sound at
  a time, so a newer cue interrupts the previous one. For short cues this is a
  deliberate trade-off, not a defect.
- **Image search.** On My Way currently opens a text search; the screenshot /
  image-search tiers (M2) are not shipped yet.
- **DSH bundle.** `plugin/lolping-intents` is a skeleton: it exposes the intent
  log as a tool, but does not start an agent turn or write results back yet;
  install it through the DSH bundle installer.
- **Scope.** Windows only, fixed eight sectors in v0.4.0, no game awareness, no
  team or room features, no cross-platform support.

## License

MIT License. See the `LICENSE` file in the repository root.

## Riot Games disclaimer

This lolping is not endorsed by Riot Games and does not reflect the views or
opinions of Riot Games or anyone officially involved in producing or managing
League of Legends. League of Legends and Riot Games are trademarks or
registered trademarks of Riot Games, Inc.
