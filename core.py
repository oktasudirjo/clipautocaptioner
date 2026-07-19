"""
core.py — shared logic for auto-captioner (used by both captioner.py CLI and gui.py)
"""

import subprocess
import shutil
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "whisper_model": "small",
    "language": None,
    "device": "cpu",
    "compute_type": "int8",
    "mode": "word",
    "words_per_group": 1,
    "font_name": "Arial Black",
    "font_size": 64,
    "bold": True,
    "italic": False,
    "text_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 3,
    "shadow": 1,
    "highlight_color": "#FFD400",
    "alignment": "center",
    "position_from_bottom_pct": 12,
    "hard_subs": True,
}


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path, "r") as f:
        cfg = yaml.safe_load(f) or {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def save_config(cfg: dict, path: str):
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


# --------------------------------------------------------------------------
# Color helpers
# --------------------------------------------------------------------------

def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """Convert '#RRGGBB' to ASS's '&HAABBGGRR&' format."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&"


def seconds_to_ass_timestamp(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


# --------------------------------------------------------------------------
# Transcription
# --------------------------------------------------------------------------

def transcribe(video_path: str, cfg: dict, progress_cb=None):
    """Run faster-whisper and return a flat list of word dicts:
    [{"word": str, "start": float, "end": float}, ...]
    progress_cb(str) is called with status updates if provided.
    """
    from faster_whisper import WhisperModel

    device = cfg.get("device", "cpu")
    compute_type = cfg.get("compute_type", "int8")
    model_name = cfg.get("whisper_model", "small")

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    try:
        log(f"Loading Whisper model '{model_name}' on {device} ...")
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as e:
        if device != "cpu":
            log(f"Failed to load model on {device} ({e}); falling back to CPU.")
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
        else:
            raise

    language = cfg.get("language") or None

    log("Transcribing audio ...")
    segments, info = model.transcribe(
        video_path,
        language=language,
        word_timestamps=True,
        vad_filter=False,  # avoid dropping quiet/short speech
    )

    words = []
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            text = w.word.strip()
            if not text:
                continue
            words.append({"word": text, "start": w.start, "end": w.end})

    # Fix any overlapping timestamps caused by model quirks
    for i in range(1, len(words)):
        if words[i]["start"] < words[i - 1]["end"]:
            words[i]["start"] = words[i - 1]["end"]
        if words[i]["end"] <= words[i]["start"]:
            words[i]["end"] = words[i]["start"] + 0.05

    log(f"Transcribed {len(words)} words.")
    return words


# --------------------------------------------------------------------------
# ASS subtitle generation
# --------------------------------------------------------------------------

def build_ass(words: list, cfg: dict, video_width: int, video_height: int) -> str:
    font_name = cfg.get("font_name", "Arial Black")
    font_size = int(cfg.get("font_size", 64))
    bold = -1 if cfg.get("bold", True) else 0
    italic = -1 if cfg.get("italic", False) else 0

    text_color = hex_to_ass_color(cfg.get("text_color", "#FFFFFF"))
    outline_color = hex_to_ass_color(cfg.get("outline_color", "#000000"))
    outline_width = cfg.get("outline_width", 3)
    shadow = cfg.get("shadow", 1)

    highlight_hex = cfg.get("highlight_color")
    highlight_color = hex_to_ass_color(highlight_hex) if highlight_hex else text_color

    alignment_map = {"left": 1, "center": 2, "right": 3}
    alignment = alignment_map.get(cfg.get("alignment", "center"), 2)

    margin_v = int(video_height * (cfg.get("position_from_bottom_pct", 12) / 100))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_name},{font_size},{text_color},{highlight_color},{outline_color},&H00000000,{bold},{italic},0,0,100,100,0,0,1,{outline_width},{shadow},{alignment},20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    mode = cfg.get("mode", "word")
    group_size = max(1, int(cfg.get("words_per_group", 1)))

    if mode == "sentence":
        groups, current = [], []
        for i, w in enumerate(words):
            current.append(w)
            gap_next = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 999
            if len(current) >= 10 or gap_next > 0.6 or i == len(words) - 1:
                groups.append(current)
                current = []
    else:
        groups = [words[i:i + group_size] for i in range(0, len(words), group_size)]

    for group in groups:
        if not group:
            continue
        start = seconds_to_ass_timestamp(group[0]["start"])
        end = seconds_to_ass_timestamp(group[-1]["end"])

        if mode == "word" and highlight_hex and len(group) > 1:
            parts = []
            for w in group:
                dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
                parts.append(f"{{\\k{dur_cs}}}{w['word']}")
            text = " ".join(parts)
        else:
            text = " ".join(w["word"] for w in group)

        lines.append(f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{text}")

    return header + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Video helpers
# --------------------------------------------------------------------------

def get_video_dimensions(video_path: str):
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"ffprobe couldn't read video info from '{video_path}'.\n\n"
            f"--- ffprobe output ---\n{result.stderr.strip()}"
        )
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def burn_subtitles(video_path: str, ass_path: str, output_path: str):
    # Make sure the output directory actually exists — ffmpeg fails silently
    # (non-descriptive exit code) if it doesn't.
    out_dir = Path(output_path).parent
    if str(out_dir) not in ("", "."):
        out_dir.mkdir(parents=True, exist_ok=True)

    # ffmpeg's ass filter requires colons to be escaped with a DOUBLE backslash
    # (a single backslash is not enough and causes it to misparse a Windows
    # drive letter like "C:" as filename="C" + a second positional option).
    escaped = ass_path.replace("\\", "/").replace(":", "\\\\:")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"ass={escaped}",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-25:])
        raise RuntimeError(
            f"ffmpeg failed (exit code {result.returncode}).\n\n"
            f"--- ffmpeg output (last lines) ---\n{stderr_tail}"
        )


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# --------------------------------------------------------------------------
# End-to-end pipeline (shared by CLI and GUI)
# --------------------------------------------------------------------------

def run_pipeline(input_path: str, output_path: str, cfg: dict,
                  save_srt: bool = False, progress_cb=None):
    """Full pipeline: transcribe -> build ASS -> burn into video.
    progress_cb(str) receives human-readable status updates.
    Returns the output_path on success.
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg/ffprobe not found on PATH. Install ffmpeg and try again.")

    input_path = str(input_path)
    ipath = Path(input_path)

    log("Reading video info ...")
    width, height = get_video_dimensions(input_path)
    log(f"Video is {width}x{height}")

    words = transcribe(input_path, cfg, progress_cb=progress_cb)
    if not words:
        raise RuntimeError("No speech detected in this video — nothing to caption.")

    log("Building styled subtitle track ...")
    ass_content = build_ass(words, cfg, width, height)
    ass_path = str(ipath.with_suffix(".ass"))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    if save_srt:
        srt_path = str(ipath.with_suffix(".srt"))
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, w in enumerate(words, 1):
                f.write(f"{i}\n")
                f.write(f"{seconds_to_ass_timestamp(w['start']).replace('.', ',')} --> "
                        f"{seconds_to_ass_timestamp(w['end']).replace('.', ',')}\n")
                f.write(f"{w['word']}\n\n")
        log(f"Saved plain .srt to {srt_path}")

    log(f"Burning captions into video -> {output_path}")
    burn_subtitles(input_path, ass_path, output_path)
    log("Done.")

    return output_path