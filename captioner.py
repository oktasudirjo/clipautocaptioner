#!/usr/bin/env python3
"""
auto-captioner CLI
-------------------
Transcribes a local video with faster-whisper and burns styled captions
into it using ffmpeg. See gui.py for a graphical version.

Usage:
    python captioner.py input.mp4 -o output.mp4 -c config.yaml
"""

import argparse
import sys
from pathlib import Path

import core


def main():
    parser = argparse.ArgumentParser(description="Auto-caption a local video file.")
    parser.add_argument("input", help="Path to the input video file")
    parser.add_argument("-o", "--output", help="Path to the output video file",
                         default=None)
    parser.add_argument("-c", "--config", help="Path to the style/config YAML file",
                         default=str(Path(__file__).parent / "config.yaml"))
    parser.add_argument("--srt-out", help="Also save an .srt copy alongside the output",
                         action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Input file not found: {input_path}")

    cfg = core.load_config(args.config)
    output_path = args.output or str(input_path.with_name(input_path.stem + "_captioned.mp4"))

    try:
        core.run_pipeline(str(input_path), output_path, cfg,
                           save_srt=args.srt_out, progress_cb=print)
    except Exception as e:
        sys.exit(f"Error: {e}")

    print(f"\nDone. Captioned video saved to: {output_path}")


if __name__ == "__main__":
    main()
