# Auto-Captioner

Auto-captions any local video file: transcribes speech with `faster-whisper`
(runs fully offline, CPU-friendly) and burns styled captions into the video
with `ffmpeg`.

## Setup

```bash
pip install -r requirements.txt
```

You also need `ffmpeg` installed and on your PATH (with `libass` support,
which most standard builds include).

## Usage

```bash
python captioner.py input.mp4 -o output.mp4 -c config.yaml
```

- `input.mp4` — any local video file
- `-o` — output path (default: `<input>_captioned.mp4`)
- `-c` — path to your style config (default: `config.yaml` next to the script)
- `--srt-out` — also save a plain `.srt` file alongside the output

## Styling

All caption styling lives in `config.yaml`:

| Setting | What it controls |
|---|---|
| `mode` | `word` (karaoke-style, one/few words at a time) or `sentence` (full lines) |
| `words_per_group` | how many words shown per caption in word mode |
| `font_name`, `font_size`, `bold`, `italic` | text appearance |
| `text_color`, `outline_color`, `outline_width`, `shadow` | colors (hex) |
| `highlight_color` | color of the word currently being spoken (word mode, karaoke effect); set to `null` to disable |
| `alignment`, `position_from_bottom_pct` | caption placement |
| `whisper_model` | `tiny` / `base` / `small` / `medium` / `large-v3` — bigger = slower, more accurate |
| `device`, `compute_type` | `cpu`/`cuda`, `int8` recommended for CPU |

Copy `config.yaml` and tweak values, or point `-c` at multiple presets
(e.g. `config_bold.yaml`, `config_subtle.yaml`) for different looks.

## Notes

- `font_name` must be a font actually installed on the machine running
  ffmpeg — otherwise it silently falls back to a default font.
- Word-level timestamps come from Whisper's own alignment; for noisy audio,
  a bigger `whisper_model` usually helps accuracy more than anything else.
- VAD filtering is disabled by default to avoid dropping quiet/short words.

## GUI

Prefer a graphical interface? Run:

```bash
python gui.py
```

(Requires `tkinter`, which ships with most Python installs — on Linux you
may need `sudo apt install python3-tk` if it's missing.)

The GUI has three tabs — **File** (input/output/save-srt, plus load/save
config presets), **Caption Style** (mode, font, colors, outline, position),
and **Transcription** (Whisper model, device, language) — and exposes every
setting from `config.yaml` with live color swatches instead of hex codes.
It runs the same `core.py` pipeline as the CLI, so a config saved from the
GUI works with `captioner.py` and vice versa. Transcription/rendering runs
in a background thread with a live progress log, so the window stays
responsive.
