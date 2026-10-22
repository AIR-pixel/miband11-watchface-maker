# miband11-watchface-maker

<div align="center">

[![Release](https://img.shields.io/github/v/release/AIR-pixel/miband11-watchface-maker?label=release&color=2ea44f)](https://github.com/AIR-pixel/miband11-watchface-maker/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![Android](https://img.shields.io/badge/android-7.0%2B-3ddc84?logo=android)](https://github.com/AIR-pixel/miband11-watchface-maker/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows%20%C2%B7%20Android-lightgrey)](https://github.com/AIR-pixel/miband11-watchface-maker)

**English** · [简体中文](./README.md)

</div>

Turn **video / GIF / still images** into an installable **animated watch face** (`.face`) for the
**Xiaomi Smart Band 11** (212×520, Vela OS) — in one click. Everything besides the wallpaper is
configurable too: **always-on display (AOD), on-screen time & date, tap actions, multiple wallpapers**.

Three independent implementations are provided — **Windows**, **Android** and **Web** — sharing the
same algorithms and producing the same output format.

> ⚠️ This is an **unofficial third-party tool**, not affiliated with Xiaomi in any way.
> Installing the generated watch face requires third-party tooling. See
> [Disclaimer](#disclaimer).

---

## At a glance

| | |
|---|---|
| **Target device** | Xiaomi Smart Band 11 · 212×520 display · Vela OS (`DeviceType=466`) |
| **Output** | `.face` (installable watch face) |
| **Input** | Video (mp4/mov/mkv/webm/avi) · GIF · still images (png/jpg/bmp/webp) |
| **Three implementations** | Windows (Python + tkinter) · Android (Kotlin UI + Java core) · Web (plain JS) |
| **Windows requirements** | Python 3.8+ · Pillow · `ffmpeg` (video only) |
| **Android requirements** | None |
| **Web requirements** | None — open it in a browser, nothing to install |
| **Official tooling** | **Not required on either platform** — no Vela IDE, no official binaries; `.face` is assembled in pure code |
| **Size budget** | Rule of thumb ≤ 3.5 MB, estimated live as you change parameters |

---

## Contents

- [What problem does it solve](#what-problem-does-it-solve)
- [Download](#download)
- [Screenshots](#screenshots)
- [Features](#features)
- [Configuration](#configuration)
- [Feature details](#feature-details)
- [Usage](#usage)
- [Three rules for controlling size](#three-rules-for-controlling-size)
- [Installing on the band](#installing-on-the-band)
- [How cross-platform parity is guaranteed](#how-cross-platform-parity-is-guaranteed)
- [On AI assistance](#on-ai-assistance)
- [Project notes](#project-notes)
- [Disclaimer](#disclaimer)
- [License](#license)
- [Project layout](#project-layout) (collapsed)

---

## What problem does it solve

Animated watch faces on the Band 11 **require Vela Lua (Lua + LVGL)** — the official
"photo watch face" only accepts still images. And the official toolchain means installing
Vela IDE, hand-writing Lua, tuning LVGL, then running the official compiler to package. Not a low bar.

This project collapses that pipeline into a single UI flow:

```
Import video/GIF/image  →  Select crop region  →  Tune compression/fps/duration  →  Build .face
```

Three things that matter:

1. **Crop by selection** — any source snaps to 212:520 with no letterboxing.
2. **Size is controllable** — watch faces have a size budget (rule of thumb ≤ 3.5 MB).
   This tool lets you dial it in per setting, and shows a **live size estimate** as you
   change parameters instead of making you guess-and-rebuild.
3. **Neither build needs the official compiler** — it is an
   x86 Windows binary that cannot run on Android. The Android version **assembles the
   `.face` byte by byte in pure code**, removing that dependency entirely.

---

## Download

| Platform | Download | Notes |
|---|---|---|
| **Web** | <https://miband-watchface.app.workbuddy.host/> | Runs in the browser, zero install. Handy on phones, tablets, or a borrowed PC |
| **Android** | [watchface-tool-android-v2.2.1.apk](../../releases/latest/download/watchface-tool-android-v2.2.1.apk) | Install directly. Android 7.0+ (minSdk 24) |
| **Windows** | [watchface-tool-pc-v2.2.1.zip](../../releases/latest/download/watchface-tool-pc-v2.2.1.zip) | Source package — install Python deps yourself (`pip install -r requirements.txt`) |

> Android may warn about "unknown sources" during install; allow it in settings.

### Web version

Live: <https://miband-watchface.app.workbuddy.host/> ·
Source: [miband11-watchface-web](https://github.com/AIR-pixel/miband11-watchface-web) (separate repo, dependency-free vanilla JS)

The same container format reimplemented for the browser: GIF decoding, palette quantization, PNG
encoding (zlib via `CompressionStream`), Lua generation and `.face` packing all happen client-side —
**nothing is uploaded**. Accepts **GIF and video** (mp4/webm/mov, frames are extracted on the main
thread when you hit generate), plus multiple wallpapers, AOD and on-screen time/date.

The web version does not do JPEG frames (browser `canvas.toBlob` always uses 4:2:0 chroma
subsampling, below the desktop build's 4:4:4); every other parameter matches the desktop version.

---

## Screenshots

<table>
<tr>
<td align="center"><b>Windows · Tab ① Animated wallpaper</b><br>
<sub>Crop selection + compression / fps / frame cap + live size estimate</sub><br>
<img src="docs/images/win-1-wallpaper.png" width="280" alt="Windows tab 1"></td>
<td align="center"><b>Windows · Tab ② Features</b><br>
<sub>AOD preview · home-screen time &amp; date · tap actions · wallpapers</sub><br>
<img src="docs/images/win-2-function.png" width="280" alt="Windows tab 2"></td>
</tr>
<tr>
<td align="center"><b>Android · Light</b><br>
<sub>Material 3, colors follow the system</sub><br>
<img src="docs/images/android-light.png" width="280" alt="Android light"></td>
<td align="center"><b>Android · Dark</b><br>
<sub>Android 12+ derives colors from the wallpaper; older versions fall back to baseline blue</sub><br>
<img src="docs/images/android-dark.png" width="280" alt="Android dark"></td>
</tr>
</table>

> The two Android images are **offline renderings reconstructed from the dp values and color
> parameters in the source**, not device screenshots (no Android device was available during
> development). Layout and colors were computed and cross-checked item by item against
> `MainActivity.kt` / `Palette.kt`. The two Windows images are real screenshots.

---

## Features

| Feature | Notes |
|---|---|
| **Multiple input formats** | Video, GIF, still images (see [At a glance](#at-a-glance)) |
| **Crop by selection** | Drag to pick the region; aspect locked to 212:520. Corner drag, mouse-wheel zoom, pinch-to-zoom |
| **Trim range** | Set start second and duration to use only part of the source |
| **Selectable fps** | 6 / 8 / 12 / 16 / 20 / 24 / 30 FPS, or inherit the source frame rate |
| **Frame cap** | The primary lever on size. Two behaviors when exceeded (see below) |
| **6 color depths / 2 encodings** | See [Configuration](#configuration) |
| **Speed-up mode** | When the frame cap hits, keep the fps and drop the playback duration instead (complete + smooth, at the cost of playing faster) |
| **Live size estimate** | Every parameter change updates "N frames · ≈ X MB · plays Y s"; over budget is flagged red |
| **Overlay time & date** | The generated Lua subscribes to system time and draws it; **position, size, color and format are all adjustable** |
| **Always-on display (AOD)** | Generates an `AOD/` sub-project. Without it the band **freezes on the last animation frame** |
| **Tap actions** | Short tap: cycle wallpaper / toggle time-date / pause animation |
| **Multiple wallpapers** | Bundle several animated wallpapers, cycled by tap |
| **Custom face name / ID** | ID can be randomized to avoid colliding with store faces |
| **Command line** | The Windows build has a pure CLI for scripting / batch generation |

### When you hit the frame cap: smoothness × duration — pick one

This is the trade-off most easily missed and most often hit. Once a frame cap is set,
**sampling frames and playback pacing are two decoupled things**:

| Mode | Sampling | Playback | Result |
|---|---|---|---|
| **Default** (keep duration, drop fps) | N frames spread over the whole clip | The reduced fps | Complete content, unchanged duration, **visibly choppy** |
| **Speed-up** (keep fps, compress duration) | N frames spread over the whole clip | The fps you asked for | **Smooth**, complete content, but plays at X× speed |

Both **sample the exact same frames and cost exactly the same bytes** — the only difference is a
single `period` value in the generated `main.lua`. So "smallest size + smooth" *is* achievable;
the price is compressed duration.

Measured: an 8 s / 24 fps clip capped at 46 frames → default plays 8.0 s (5.75 fps, choppy);
speed-up plays 1.9 s (24 fps, smooth, 4.17×).

---

## Configuration

### Color depth and encoding (measured per frame, 212×520)

| Setting | Internal name | Per frame | Use when |
|---|---|---|---|
| True color RGB | `high` | 146.8 KB | Almost never (far too large) |
| Balanced P256 | `balanced` | 66.7 KB | Source is extremely colorful |
| Small P128 | `small` | 53.0 KB | Quality first |
| Extreme P64 | `tiny` | **41.5 KB** | **Recommended starting point** |
| Tiny P32 | `micro` | 31.6 KB | Size is tight |
| Micro P16 | `nano` | **20.4 KB** | Maximum compression, visible color loss |
| JPEG q90 | `--fmt jpg` | 41.4 KB | Same size as P64 but lossy — prefer PNG |
| JPEG q85 | | 32.7 KB | Upper edge of the sweet spot |
| JPEG q80 | | **27.5 KB** | **Default**, 34% smaller than P64 PNG |
| JPEG q70 | | 21.4 KB | Size first |
| JPEG q60 | | 17.7 KB | Extreme, visible noise |

**PNG and JPEG are not substitutes — they are two different kinds of loss.**

| | Pros | Cons |
|---|---|---|
| **P64 PNG** | Lossless, clean flat areas, no noise | Only 64 colors → **banding** in gradients / skin tones |
| **JPEG q80** | Smooth gradients with no banding, 0.66× the size of P64 | Lossy, **mosquito noise / blocking** at edges |

Rule of thumb: **JPEG q80 for photos, real people, heavy gradients**;
**PNG P64 for flat anime art and clean color blocks**.

> The P-series is a **lossless palette** (quantize to N colors, then store as lossless PNG);
> the cost is banding in gradients. For finer data (per-channel PSNR, reproducible scripts)
> see [`docs/体积与画质实测.md`](./docs/%E4%BD%93%E7%A7%AF%E4%B8%8E%E7%94%BB%E8%B4%A8%E5%AE%9E%E6%B5%8B.md).

<details>
<summary><b>Two counter-intuitive details about JPEG</b></summary>

**1. The sweet spot is q80–q85.** At q90 and above, JPEG is *larger* than P64 PNG
(41.4 vs 41.5 KB) — and P64 is lossless, so just use PNG there.

**2. The Windows build disables JPEG chroma subsampling (forces 4:4:4).** Pillow's default 4:2:0
cuts chroma down to 106×260, causing visible color bleed at colored edges — the main reason
"JPEG looks mushy". Measured cost of disabling it: only +19% size, but +2.5 dB chroma PSNR.
Best value trade in the whole pipeline.

**The Android build cannot do this**: `Bitmap.compress` is fixed at 4:2:0, so JPEG exported
from Android has a lower quality ceiling than the Windows build.

</details>

### Frame rate and frame cap

- **Frame rate**: 24 FPS is the smoothness threshold (measured: 33 FPS stutters, 24 FPS is fine,
  16 FPS is safer). The default is **12 FPS with a 96-frame cap** so that an 8-second clip
  doesn't immediately produce a 7 MB+ face.
- **Frame cap**: default 96. Behavior when exceeded is controlled by the speed-up switch
  (see the previous section).

### Other settings

| Setting | Default | Notes |
|---|---|---|
| Trim start | 0 s | Which second of the source to start from |
| Trim duration | whole clip | Leave empty to run to the end |
| Face name | MyWatchface | Shown in the face picker |
| Face ID | random | 10-digit number; random avoids colliding with store faces |
| Size budget | 3.5 MB | Only used to flag the estimate red; it never blocks generation |

---

## Feature details

Four groups of settings on tab 2. **Everything on the home screen is driven by Lua** (the
`.fprj` contains only a single fully transparent mount point), so time / date / tap actions
modify the generated `main.lua`. **The AOD screen does not support Lua** and can only use the
fprj widget layer.

### Always-on display (AOD)

Without AOD, the band **freezes on the last animation frame** when the screen goes off — ugly and
wasteful. Adding it fixes that.

The output is a **sibling sub-project**; it is not compiled separately but included when the main
project is packaged:

```
MyFace.fprj + images/ + app/lua/
AOD/
├── AOD.fprj          ← both the directory and file name are fixed; the compiler hardcodes this path
└── images/
```

The AOD screen **cannot run Lua** (measured: writing a `Shape=34` mount point into `AOD.fprj`
does not get its lua into the package — the output only grows by 88 bytes). So the AOD clock uses
`Shape=32` digit bitmaps bound to `Value_Src` **system data sources**.

<details>
<summary><b>Data source ID table</b></summary>

| Source | ID | Source | ID |
|---|---|---|---|
| Hour | `0811` | Month | `1012` |
| Minute | `1011` | Day | `1812` |
| Second | `1811` | Weekday | `2012` |
| Battery | `0841` | Heart rate | `0822` |

IDs are the hex literals with `0x` and leading zeros stripped; taken from the `xiaomi_band_10`
column of Mi-Create's `sources.json`, which is the `DeviceType=466` this tool targets. The compiler
just stores the number without validating it; the system resolves it at runtime.

</details>

Default "time + date" costs ≈ **+155 KB**. Four things to know:

- **No full-screen black background by default.** On AMOLED, black pixels emit no light and the
  screen is already black — this saves 431 KB. You can opt into a "pure black backdrop" if you
  want the safety margin (that costs +431 KB).
- **Digit size is literally money**: 46×64 hour/minute digits (11 images) ≈ 127 KB;
  20×28 date digits ≈ 24 KB.
- **One shared BitmapList is only counted once** even when several widgets reference it — so two
  `Shape=32` widgets (hour and minute) pay for one set of bitmaps.
- **Glyphs come from an embedded font** (generated by `tools/gen_aod_font.py`, shared by both
  platforms) rather than a system font — so Windows and Android produce **pixel-identical**
  AOD digits.

<details>
<summary><b>AOD size cost (measured per item)</b></summary>

| Item | Cost |
|---|---|
| Empty AOD screen | +88 B |
| Each `Shape=30` image | `width × height × 4 + 60` B |
| Each `Shape=32` digit group | `img_w × img_h × 4 × count` (de-duplicated when widgets share a `BitmapList`) |

One counter-intuitive measurement: adding a `Shape=30` icon to the **home screen** gets composited
into a full-screen bitmap (+431 KB each), but the **AOD screen** does not (it is charged by actual
image size). So "icons are cheap on AOD" and "icons are expensive on the home screen" are both true.

</details>

### Home-screen time / date

| Item | Notes |
|---|---|
| Toggle | Time and date are switched independently |
| Position | 3×3 anchor grid (top-left / top-center / … / bottom-right) + X/Y pixel offset |
| Font size | 8–200 |
| Color | Color picker, or enter `#RRGGBB` directly |
| Format | System `strftime`: `%H:%M`, `%Y/%m/%d`, `%p %I:%M`, etc. |

This runs through Lua's `lvgl.Label` + `lvgl.ALIGN` and **costs no extra size** (the font lives on
the device). Positioning is pixel-level, far more flexible than the fprj widget layer.

### Tap actions

| Option | Behavior |
|---|---|
| None | Short tap does nothing |
| Cycle wallpaper | Rotate through multiple wallpapers (auto-degrades to "None" with only one) |
| Show / hide time & date | Toggle the info layer |
| Pause / resume animation | Freeze the frame (a battery-saving trick) |

Implemented with `root:add_flag(lvgl.FLAG.CLICKABLE)` + `onevent(lvgl.EVENT.SHORT_CLICKED)`;
child widget events bubble to the root via `FLAG.EVENT_BUBBLE`.

> **Launching system apps (weather / alarm / heart rate) is impossible on this generation**,
> so that option does not exist. Measured: at `DeviceType=466` the compiler **completely ignores**
> the semantics of `btn[...]` widget names — renaming a widget to `btn[weather]` / `btn[alarm]` /
> `btn[hrm]` produced **byte-identical** outputs across five builds. That capability belongs to the
> Band 8 Pro / Redmi Watch generations. The Lua side has no launch API either. **Both paths are dead.**

### Multiple wallpapers

Wallpaper 1 is the source you picked on tab 1; the rest are added here. They **reuse the
compression / fps / duration settings from tab 1**, with the frame cap applied per wallpaper.
Naming: wallpaper 1 is `face_01.png…`, wallpaper 2 is `w2_01.png…`, and so on.

> **Each wallpaper costs its own size.** Two 12 fps wallpapers ≈ double the size —
> the estimate line accounts for it.

### Battery-saving hooks

<details>
<summary>Why both <code>pageOnPause</code> and <code>ScreenStateChangedCB</code></summary>

```lua
function ScreenStateChangedCB(pre, now, reason)
    if pre ~= "ON" and now == "ON" then resumeActive()
    elseif pre == "ON" and now ~= "ON" then pauseAll() end
end
```

When entering AOD the watch face page is **not actually switched away**, so `pageOnPause` very
likely never fires. Relying on it alone leaves the animation running under the always-on display
and destroys battery life. Hence both hooks.

</details>

---

## Usage

### Windows

**1. Set up**

```bash
pip install -r watchface-tool/requirements.txt   # Pillow + tkinterdnd2
```

- Processing **video** requires `ffmpeg` (GIF / images do not); add it to PATH.
- Packaging is pure Python — **no official tooling needed**.
  bring your own (see [NOTICE](./NOTICE)).

**2. Launch**

```bash
cd watchface-tool
python main.py
```

**3. Flow**

The UI has **two tabs**, with "Generate .face" pinned at the bottom:

| Tab | Contents |
|---|---|
| **① Animated wallpaper** | 1. Source · 2. Parameters |
| **② Features** | A. AOD · B. Wallpapers (multiple) · C. Home-screen elements · D. Tap actions |
| **Bottom (pinned)** | Generate button · progress bar · status line |

**Tab ①**: drag in a source (or click "Select source") → **select the crop region** on the left
(drag to move, drag corners to resize, scroll to zoom) → tune compression, encoding, JPEG quality,
fps, trim range, frame cap and speed-up on the right → check the estimate line (turns red over
budget) → hit **Generate .face** at the bottom.

**Tab ②**, four groups (all optional — skip them for a plain animated wallpaper):
**A. Always-on display** — toggle, backdrop (none / pure black / custom image), content
(none / time / time+date), time Y, date Y, color, with a **live preview** and size estimate below;
**B. Wallpapers** (multiple, cycled by tap) — list plus "Add wallpaper…" / "Remove selected";
**C. Home-screen elements** — independent "show time" / "show date" toggles, each with a 3×3 anchor +
±X/±Y offset, font size, strftime format and color (with a swatch palette);
**D. Tap actions** — "Short tap" dropdown: none / cycle wallpaper / show·hide time-date / pause·resume.

Finally click "Generate .face" at the bottom. Output goes to `watchface_out/` next to the source.

### Android

**1. Install** — download
[watchface-tool-android-v2.2.1.apk](../../releases/latest/download/watchface-tool-android-v2.2.1.apk)
(Android 7.0+).

**2. Flow** — likewise two tabs plus a pinned generate button.

| Tab | Controls |
|---|---|
| **① Animated wallpaper** | Pick source · crop region (drag / corner / pinch, with "Reset crop" and "Fill screen") · multiple wallpapers (≤8, reusing the same settings, cropping fixed to "full height, centered") · compression 6 levels · fps 7 levels · encoding 2 kinds · frame cap 7 levels · JPEG quality 5 levels (greyed out unless JPEG) · start/duration · speed-up switch · estimate line "N wallpapers / N frames total · ≈ X MB (incl. 431 KB fixed overhead)" |
| **② Features** | Home time / date (independent toggles, 9 alignments, X/Y offset, font size, preset swatches, strftime format) · tap the face (cycle wallpaper / toggle time-date / pause) · AOD (toggle, backdrop, content, time & date row Y, color, **with a live preview** and size estimate) |
| **Bottom (pinned)** | Generate button · progress bar · status |

Output goes to `Android/data/face.tool/files/faces/`.

> The Generate button sits **outside** the scroll area, pinned to the bottom, so it stays reachable
> at any screen size or font scale — the older layout stacked everything into one screen and pushed
> the button off-screen on small devices. The crop preview and AOD preview absorb spare height via
> "baseline height + weight": when there is room, parameters lay out at natural height with no gaps;
> when there isn't, the preview falls back to its baseline height and the page scrolls.
>
> Neither build needs the official compiler; each has its own pure-code packer (Java / Python).

**3. Building from source** (no Android Studio, no Gradle)

```bash
cd watchface-android
bash fetch_kotlinc.sh    # first run: fetch a minimal Kotlin CLI (~62 MB, into .kotlinc/, gitignored)
# Requires: Android SDK build-tools (aapt2/d8/zipalign/apksigner) + JDK 17+
bash build.sh
```

Pipeline: `aapt2 link → javac(Java) → kotlinc(Kotlin) → R8 → inject classes.dex → zipalign →
apksigner`. Output: `watchface-tool.apk`.

<details>
<summary><b>Three things about the build chain</b></summary>

**The UI is Kotlin; the core algorithms are Java** (zero Android dependencies, runs on a desktop
JVM too). The two are compiled together in a hand-rolled chain — no Gradle needed.

**R8 is required, not optional.** Kotlin drags in kotlin-stdlib, which would take the APK from
49 KB to 2.1 MB. The script runs **R8 (full mode)** by default, tree-shaking all 1108 `kotlin/*`
classes — the result measures **the same size as a pure-Java build**.
`NOR8=1 bash build.sh` skips compression for a slower build (~10 s → ~50 s).
R8 comes from the SDK's own `cmdline-tools/*/lib/r8.jar`; nothing extra to download.

**Pitfalls already handled in the script:**

1. `d8.bat` / `apksigner.bat` / R8 locate the JDK via **`JAVA_HOME`** (the `java` on PATH may be a
   different version) — the script exports `JAVA_HOME=...` explicitly.
2. Under Git Bash, Windows paths must be in `/c/...` form, and `javac` needs `--release 8` to emit
   bytecode usable by minSdk 24.
3. **Git Bash does not convert paths when the classpath is joined with `;`** — Java cannot read
   `/c/...`, and the symptom is
   `ClassNotFoundException: org.jetbrains.kotlin.cli.jvm.K2JVMCompiler` (looks like a corrupt jar).
   The script always converts with `cygpath -w` to `C:\...`.
4. kotlinc's `-no-stdlib` only disables *auto-locating* stdlib from kotlin-home — it does **not**
   mean you don't need stdlib. You still have to put `kotlin-stdlib.jar` on `-classpath`,
   otherwise you get pages of `cannot access built-in declaration 'kotlin.String'`.

</details>

### Command line

The Windows build supports headless generation:

```bash
cd watchface-tool
python main.py --cli \
  --src clip.gif --level tiny --fps 12 --max-frames 96 \
  --fmt jpg --jpg-quality 80 \
  --clip-start 0 --clip-dur 4 \
  --name MyFace
```

<details>
<summary><b>Option reference</b> (click to expand)</summary>

**Core options**

| Option | Notes |
|---|---|
| `--src` | Source path (required) |
| `--level` | `high` / `balanced` / `small` / `tiny` / `micro` / `nano`; default `balanced` |
| `--fps` | Target frame rate; omit to use the source frame rate |
| `--clip-start` / `--clip-dur` | Start time / trim duration (seconds); omit duration to run to the end |
| `--max-frames` | Total frame cap; default 96 |
| `--fmt` | `png` / `jpg`; default `png` |
| `--jpg-quality` | JPEG quality; default 80 (only with `--fmt jpg`) |
| `--speedup` | Keep fps, compress duration; default is keep duration and drop fps |
| `--crop` | Crop box `x0,y0,x1,y1`; omit for centered default |
| `--name` / `--id` | Face name / ID |
| `--out` | Output directory |
| `--no-time` | Do not overlay the time |

**Feature options**

| Option | Notes |
|---|---|
| `--date` | Also overlay the date (default is time only) |
| `--time-fmt` / `--date-fmt` | strftime format; default `%H:%M` / `%m/%d` |
| `--time-pos` / `--date-pos` | LVGL alignment name (`TOP_MID`, `CENTER`, `BOTTOM_RIGHT`, …); default `TOP_MID` |
| `--time-ofs` / `--date-ofs` | Pixel offset `dx,dy`; default `0,30` / `0,86` |
| `--time-size` / `--date-size` | Font size; default 48 / 16 |
| `--time-color` / `--date-color` | Color `RRGGBB`; default `FFFFFF` / `EEEEEE` |
| `--tap` | `none` / `cycle` (cycle wallpaper) / `info` (toggle info) / `anim` (pause) |
| `--wall <path>` | Extra wallpaper; repeatable |
| `--aod` | Generate the always-on sub-project |
| `--aod-content` | `none` / `time` (default) / `both` |
| `--aod-bg` | `none` (default, free) / `black` / `custom` |
| `--aod-bg-image` | Image path when `--aod-bg custom` |
| `--aod-time-y` / `--aod-date-y` | Y coordinate of the AOD time / date row; default 200 / 300 |
| `--aod-color` | AOD digit color `#RRGGBB` (glyphs come from the embedded font in `tools/gen_aod_font.py`) |

</details>

Example: two wallpapers + AOD + tap to cycle

```bash
python main.py --cli \
  --src w1.gif --wall w2.gif \
  --level tiny --fps 8 --max-frames 48 \
  --date --date-fmt "%Y/%m/%d" --tap cycle \
  --aod --aod-content both \
  --name MyFace
```

---

## Three rules for controlling size

1. **Frame count is the main lever; color depth is only secondary.**
   P256 → P64 cuts just 38% per frame, whereas dropping 24 → 8 FPS cuts the **frame count** —
   and therefore the size — by 67%. An 8-second clip at 24 FPS is 192 frames, which is 7.8 MB
   even at P64. Cut duration or fps first; don't keep squeezing color depth.

2. **There is a fixed 431 KB overhead in every `.face`** (a trailing 212×520 RGBA8888 bitmap used
   as the picker preview). With few frames it can outweigh all the frame data, so don't expect to
   shrink an already-tiny face much further.

3. **To go smaller, tune in this order:**
   **trim duration → fps → frame cap → color depth → encoding (JPEG)**.

Finer measurements (per-channel PSNR, reproducible scripts) are in
[`docs/体积与画质实测.md`](./docs/%E4%BD%93%E7%A7%AF%E4%B8%8E%E7%94%BB%E8%B4%A8%E5%AE%9E%E6%B5%8B.md).

---

## Installing on the band

The generated `.face` needs a **third-party watch face tool** (paired with a modified Mi Fitness)
or the official Mi Fitness face channel to be installed on the Xiaomi Smart Band 11.

**This project only generates `.face`. It is not part of the installation chain and provides no
support for it.** Make sure your installation method matches your device and firmware version.

---

## How cross-platform parity is guaranteed

The `main.lua` generator, the AOD layout and descriptor blocks, and the `.face` assembler each
**have two implementations** (Python, and Java/Kotlin). That kind of "line-by-line port" is the
easiest thing in the world to fool yourself about — looks identical, bytes differ.

So the repo ships a **cross-language differential regression**:
`python tools/diff_face.py` (~40 s, needs only a JDK + Pillow). It runs both implementations over
the same case tables and compares them **byte for byte**:

| Stage | What is compared | Cases |
|---|---|---|
| `lua` | The full generated `main.lua` | 12 |
| `aod` | AOD widget table + every descriptor record | 12 |
| `asm` | **Every byte of the whole `.face`** (including AOD and alignment edges) | 21 |
| `font` | **Every pixel of the AOD digit bitmaps** | 26 |

Comparing all bytes rather than "key fields" is deliberate: the four bugs this regression has
caught (tail alignment only half-applied, relative vs. absolute offsets mixed up, a branch that had
never been executed, and an `append` indented one level too far emitting a phantom widget)
**all** lived in places where the key fields looked perfectly fine.
See bugs 4/5/6 in [`docs/项目经验.md`](./docs/%E9%A1%B9%E7%9B%AE%E7%BB%8F%E9%AA%8C.md).

### Parity with the official compiler (re-runnable)

The diff above proves the two implementations agree with *each other*. Proving they agree with the
official compiler is also scripted:

```bash
python tools/roundtrip_face.py sample1.face sample2.face ...
```

It unpacks an existing `.face` back into packer inputs and repacks it, requiring a **byte-for-byte**
match with the original. Against 5 samples produced by the official compiler (single wallpaper /
AOD time / AOD time+date / three wallpapers / JPEG frames) the result is `5/5 identical`.

A more direct check was also run locally: the same parameters through "official compiler" and
"pure-code packer", then `cmp` on the two `.face` files — all 5 were zero-diff. That step needs the
compiler binary (not in the repo, and no longer a runtime dependency), so it stays a one-off
measurement; the re-runnable part is `tools/roundtrip_face.py`.

---

## On AI assistance

**This project was developed with heavy AI assistance.** That is stated plainly here, not hidden.

- **Code / docs / reverse engineering**: largely generated and iterated by AI (Claude, DeepSeek and
  other models) under human direction. The human defines requirements, judges approaches, verifies
  results, and corrects course when the AI drifts.
- **Measured data**: every number in `docs/` was **produced by actually running the code**, not
  estimated by AI. Size/quality (`tools/bench_quality.py`), format structure
  (`tools/verify_face.py`), and **whether the two implementations are equivalent**
  (`tools/diff_face.py`) all have reproducible scripts. Only the AOD per-item cost figures come
  from a one-off controlled experiment whose script was not published.

**What that means:**

- ✅ Actual behavior is **whatever the measurements say**, not whatever the docs say.
  Where docs and code disagree, the docs are wrong.
- ⚠️ Code that has not been thoroughly reviewed by a human may contain hidden defects.
  Verified to work in the scenarios tested, but **no guarantee of covering every input combination**.
- ⚠️ Evaluate for yourself before using it in anything involving security, privacy, or legal compliance.

If you care about whether AI-written code can be trusted — this project's stance is:
**let reproducible measurements do the talking**. Raw data backs every key claim, and everything
that could be turned into a script was. Feel free to re-run it and prove it wrong.

---

## Project notes

Pitfalls, technical findings and methodology from development are collected in
[`docs/项目经验.md`](./docs/%E9%A1%B9%E7%9B%AE%E7%BB%8F%E9%AA%8C.md), including:

- The full reverse-engineering process for the `.face` format and the breakthroughs that mattered
- The three levers of size optimization, and why intuition is wrong (color depth is not the main one)
- Root-cause analysis of a real bug: the resize handle "not following the finger"
  (mixing incremental and constant values)
- Locating the root cause of the JPEG quality problem (chroma subsampling)
- Building an Android APK without Gradle, and the two pitfalls you cannot avoid
- Retrospective: where AI collaboration helped and where it tends to go wrong

---

## Disclaimer

**Please read this section in full before use.**

1. **Unofficial tool.** This is a personally developed third-party tool with **no relationship
   whatsoever** to Xiaomi Inc. or any of its affiliates. It is not authorized, sponsored,
   endorsed, or supported by them. "Xiaomi", "Mi Band", "Vela" and related marks are trademarks
   of their respective owners.

2. **Use at your own risk.** The `.face` files this tool generates, and your act of installing
   them on a device, are **entirely at your own risk**. The author accepts no responsibility for:
   device damage or bricking, data loss, voided warranty; display glitches, black screen, stutter,
   abnormal battery drain; any problem caused by third-party installation tools; or account
   suspension or restriction.

3. **No installation support.** This tool only generates `.face`. Installing it on the band
   requires third-party tooling, which is out of scope; the author provides no guidance or support
   for it.

4. **Compliance is your responsibility.** You bear full responsibility for the watch faces you
   generate and distribute. Do not use copyrighted video, images, music, or character likenesses
   without authorization, and do not publicly distribute such output. Turning anime, film, TV or
   game assets into a shared watch face **constitutes infringement** in many cases.

5. **Third-party components.** This project neither depends on nor distributes any official
   tooling binary (early versions required the official compiler; pure-code packing replaced it).
   Runtime dependencies are Pillow / tkinter / ffmpeg and friends — see [NOTICE](./NOTICE).

6. **No warranty.** This software is provided "as is", without warranty of any kind, express or
   implied, including but not limited to warranties of merchantability or fitness for a particular
   purpose. See [LICENSE](./LICENSE).

7. **AI-generated content.** This project was developed with heavy AI assistance
   (see [On AI assistance](#on-ai-assistance)). Code and documentation may contain errors
   introduced by AI. **Review it yourself before relying on it in critical scenarios.**

8. **Rights reserved.** The author reserves the right to modify, stop maintaining, or delete this
   project at any time, without owing users anything.

> **In one line**: this is a toy tool for your own tinkering. Have fun, but don't come looking for
> the author if something goes wrong.

---

## License

The project's own source code is released under the **MIT License** — see [LICENSE](./LICENSE).

Third-party components, references, and trademark attributions are in [NOTICE](./NOTICE).

> Note: MIT covers only the source contained in this repository. Third-party runtime dependencies
> (Pillow, ffmpeg, ...) and trademark ownership are unaffected by this project — see [NOTICE](./NOTICE).

---

<details>
<summary><b>Project layout</b> (click to expand)</summary>

```
miband11-watchface-maker/
├── README.md                  This document (Chinese)
├── README_EN.md               English version
├── LICENSE                    MIT
├── NOTICE                     Third-party sources and compliance notes
├── docs/
│   ├── face格式规范.md          .face binary format (reverse-engineered, full field tables)
│   ├── 体积与画质实测.md        All measured data
│   ├── 项目经验.md             Pitfalls, findings, methodology
│   └── images/                Screenshots used by the READMEs
│       ├── win-1-wallpaper.png    Windows tab 1 (real screenshot)
│       ├── win-2-function.png     Windows tab 2 (real screenshot)
│       ├── android-light.png      Android light (reconstructed from source dp/colors)
│       └── android-dark.png       Android dark (same)
├── tools/
│   ├── verify_face.py         .face structure checker (read-only, understands AOD layout)
│   ├── bench_quality.py       Size / quality measurement script
│   ├── lint_lua.py            Syntax check for generated main.lua (all parameter combinations)
│   ├── diff_face.py           **Cross-language differential regression**: Python ↔ JVM, byte-exact
│   ├── gen_aod_font.py        Generates the shared embedded AOD font
│   └── diff/                  Case tables, JVM driver, and Python reference implementation
├── watchface-tool/            Windows build (Python + tkinter)
│   ├── main.py                Entry point (GUI / --cli)
│   ├── gui/
│   │   ├── window.py          Main window (two tabs: wallpaper / features)
│   │   ├── crop_canvas.py     Crop preview canvas (hand-drawn on tk.Canvas)
│   │   └── scroll_frame.py    Scrollable container (tab 2)
│   └── watchface_tool/
│       ├── constants.py       Constants, format definitions, data source ID table
│       ├── extract.py         Video / GIF / image → frame sequence + frame planning
│       ├── crop.py            Snap the selection to 212:520
│       ├── quantize.py        Compression and encoding (PNG / JPEG)
│       ├── lua.py             Generates main.lua (animation + time/date + taps + battery hooks)
│       ├── aod.py             Generates the AOD sub-project (digit bitmaps + source binding)
│       ├── aod_font.py        Embedded AOD font (generated by tools/gen_aod_font.py)
│       ├── facebin.py         .face pack/unpack core (pure code, no third-party deps)
│       ├── build.py           Collect project files → pack → write out
│       └── pipeline.py        Orchestration
└── watchface-android/         Android build (Kotlin UI + Java core)
    ├── build.sh               Gradle-free build script (javac + kotlinc + R8)
    ├── fetch_kotlinc.sh       Fetches a minimal Kotlin CLI
    ├── r8-rules.pro           R8 keep rules
    ├── app/
    │   ├── AndroidManifest.xml
    │   └── src/face/tool/
    │       ├── MainActivity.kt    Main UI (two tabs, Kotlin)
    │       ├── CropView.kt        Crop widget (Kotlin)
    │       ├── AodPreviewView.kt  AOD screen preview (Kotlin)
    │       ├── AodRenderer.java   Renders the AOD layout into bitmaps
    │       └── FaceGenerator.java Orchestration (Java)
    ├── core/face/             Core algorithms, zero Android dependencies (Java)
    │   ├── FaceBuilder.java   Assembles .face (incl. AOD; byte-identical to the Python version)
    │   ├── Quantizer.java     Palette quantization (median cut + Floyd-Steinberg)
    │   ├── PngEncoder.java    PNG encoding (incl. paletted)
    │   ├── AodGen.java        Pure AOD logic (layout / descriptor records / size estimate)
    │   ├── AodFont.java       Embedded AOD font (generated by tools/gen_aod_font.py)
    │   └── LuaGen.java        Generates main.lua
    └── test/face/             Self-tests for the core algorithms
```

</details>
