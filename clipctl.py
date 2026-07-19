#!/usr/bin/env python3
"""
clipctl.py  a monolithic cli multimedia toolbox on top of ffmpeg.

Modes (picked from the main menu):
  1. Clip & join videos   numbered videos (1.mp4, 2.mkv ...) -> trim each -> concat
  2. Video -> GIF         one clip -> GIF (2 pass palette)
  3. Compress video       shrink to a target size (1 or 2 passes)
  4. Audio track          mute a video, or replace its audio with music
  5. Grab frame           save a frame at a timestamp as an image
  6. Clip & join audio    numbered audio (1.mp3, 2.wav ...) -> trim each -> concat
  7. Convert images       png / jpg / webp / bmp / tiff / gif / avif / ...
  8. Convert format       video<->video, video->audio, audio<->audio

Shared rules:
  - trim ranges use HH:MM:SS*HH:MM:SS
  - clip/join files must be named 1.<ext>, 2.<ext>, ... ascending
  - everything the tool creates lands in ./clipctl_output/

Targets Linux x86_64, Linux aarch64, Windows x86_64, Windows arm64.
Requires ffmpeg + ffprobe on PATH.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def find_tool(name: str) -> Optional[str]:
    """shutil.which handles .exe on Windows via PATHEXT, but be explicit."""
    p = shutil.which(name)
    if p:
        return p
    if platform.system() == "Windows":
        return shutil.which(name + ".exe")
    return None


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")

if not FFMPEG or not FFPROBE:
    print("ERROR: ffmpeg and ffprobe must be installed and on PATH.", file=sys.stderr)
    print("  Linux:   apt/dnf/pacman install ffmpeg", file=sys.stderr)
    print("  Windows: winget install ffmpeg   (or download from ffmpeg.org)", file=sys.stderr)
    sys.exit(1)


def log_failure(label: str, cmd: list[str], stderr_text: str = "") -> None:
    """Append a failed command (plus captured stderr, if any) to
    clipctl_output/errors.log so failures can be reported with real
    diagnostics instead of just "ffmpeg failed"."""
    try:
        outdir = Path.cwd() / OUTPUT_DIR_NAME
        outdir.mkdir(exist_ok=True)
        with open(outdir / "errors.log", "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] FAILED: {label}\n")
            f.write("  cmd: " + shlex.join(cmd) + "\n")
            if stderr_text:
                f.write("  stderr (tail):\n")
                for ln in stderr_text.strip().splitlines()[-30:]:
                    f.write("    " + ln + "\n")
        print(f"  (saved diagnostics to {OUTPUT_DIR_NAME}/errors.log)")
    except OSError:
        pass


def _run_logged(label: str, cmd: list[str]) -> bool:
    """Run an ffmpeg command whose stderr streams live to the console;
    on failure, persist the exact command to the error log."""
    r = subprocess.run(cmd)
    if r.returncode != 0:
        log_failure(label, cmd)
    return r.returncode == 0


# constants

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".ts", ".mpg", ".mpeg", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma"}

# extension 
AUDIO_CODEC_MAP: dict[str, tuple[str, Optional[int]]] = {
    ".mp3":  ("libmp3lame", 192_000),
    ".wav":  ("pcm_s16le", None),
    ".ogg":  ("libvorbis", 192_000),
    ".flac": ("flac", None),
    ".m4a":  ("aac", 192_000),
    ".aac":  ("aac", 192_000),
    ".opus": ("libopus", 128_000),
    ".wma":  ("wmav2", 192_000),
}

VIDEO_TARGETS = [".mp4", ".mkv", ".mov", ".avi", ".webm"]
AUDIO_TARGETS = [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus"]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
              ".gif", ".avif", ".tga", ".ppm", ".heic", ".heif"}

# image ext 
IMAGE_ENCODER_MAP: dict[str, str] = {
    ".png":  "png",   ".jpg": "mjpeg", ".jpeg": "mjpeg", ".webp": "libwebp",
    ".bmp":  "bmp",   ".tiff": "tiff", ".tif":  "tiff",  ".gif":  "gif",
    ".avif": "libaom-av1", ".tga": "targa", ".ppm": "ppm",
}
# image formats with an alpha channel, converting an alpha source to anything
# NOT in here needs the transparency flattened onto a background first
IMAGE_ALPHA_CAPABLE = {".png", ".webp", ".tiff", ".tif", ".gif", ".avif", ".tga"}
# pixel format to force per flatten target (rgb targets vs jpeg's yuv)
FLATTEN_PIXFMT = {".jpg": "yuvj420p", ".jpeg": "yuvj420p", ".bmp": "rgb24", ".ppm": "rgb24"}

# which codecs can be stream copied into which container and still be
# playable by normal players (ffmpeg will mux more, e.g. pcm
# into mp4 as 'ipcm', but nothing can play the result)
CONTAINER_VCODECS: dict[str, set[str]] = {
    ".mp4":  {"h264", "hevc", "av1"},
    ".m4v":  {"h264", "hevc", "av1"},
    ".mov":  {"h264", "hevc", "av1", "prores", "mjpeg"},
    ".mkv":  {"h264", "hevc", "av1", "vp8", "vp9", "mpeg4", "mpeg2video", "mjpeg"},
    ".webm": {"vp8", "vp9", "av1"},
    ".avi":  {"mpeg4", "mjpeg", "h264", "msmpeg4v3"},
}
CONTAINER_ACODECS: dict[str, set[str]] = {
    ".mp4":  {"aac", "mp3", "ac3", "eac3"},
    ".m4v":  {"aac", "mp3", "ac3"},
    ".mov":  {"aac", "mp3", "ac3", "alac", "pcm_s16le", "pcm_s16be"},
    ".mkv":  {"aac", "mp3", "ac3", "eac3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "dts"},
    ".webm": {"opus", "vorbis"},
    ".avi":  {"mp3", "ac3", "pcm_s16le"},
}

# containers the clipctl can output, mapped to the codec family it encodes
# parts in (so trim + concat copy stays valid)
CLIPPER_CONTAINERS: dict[str, str] = {
    ".mp4":  "h264",
    ".mkv":  "h264",
    ".mov":  "h264",
    ".webm": "vp9",
}

# everything the tool creates lands here (inside the working directory)
OUTPUT_DIR_NAME = "clipctl_output"


# time parsing and formatting

_TIME_RE = re.compile(r"^\s*(\d{1,4}):(\d{2}):(\d{2})\s*$")
_RANGE_RE = re.compile(r"^\s*(\d{1,4}:\d{2}:\d{2})\s*\*\s*(\d{1,4}:\d{2}:\d{2})\s*$")


def parse_time(s: str) -> Optional[int]:
    m = _TIME_RE.match(s)
    if not m:
        return None
    h, mi, se = (int(x) for x in m.groups())
    if mi >= 60 or se >= 60:
        return None
    return h * 3600 + mi * 60 + se


def parse_range(s: str) -> Optional[tuple[int, int]]:
    m = _RANGE_RE.match(s)
    if not m:
        return None
    a, b = parse_time(m.group(1)), parse_time(m.group(2))
    if a is None or b is None or b <= a:
        return None
    return a, b


def fmt_time(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# probing

def probe(path: Path) -> Optional[dict]:
    """Return info about the first video/audio streams + container, or None."""
    cmd = [
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None

    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic", 0) != 1), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    info: dict = {
        "duration": duration,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "vcodec": None, "vbitrate": None, "width": None, "height": None, "fps": 30.0,
        "acodec": None, "abitrate": None, "sample_rate": None, "channels": None,
    }

    if audio is not None:
        info["acodec"] = audio.get("codec_name")
        info["abitrate"] = int(audio["bit_rate"]) if audio.get("bit_rate") else None
        info["sample_rate"] = int(audio["sample_rate"]) if audio.get("sample_rate") else None
        info["channels"] = int(audio["channels"]) if audio.get("channels") else None

    if video is not None:
        info["vcodec"] = video.get("codec_name", "unknown")
        info["pix_fmt"] = video.get("pix_fmt")
        info["width"] = int(video.get("width") or 0)
        info["height"] = int(video.get("height") or 0)
        if video.get("bit_rate"):
            info["vbitrate"] = int(video["bit_rate"])
        elif data.get("format", {}).get("bit_rate"):
            total = int(data["format"]["bit_rate"])
            abr = info["abitrate"] or 128_000
            info["vbitrate"] = max(total - abr, total // 2)
        if video.get("avg_frame_rate") and "/" in video["avg_frame_rate"]:
            num, den = video["avg_frame_rate"].split("/", 1)
            try:
                n, d = float(num), float(den)
                if d:
                    info["fps"] = n / d
            except ValueError:
                pass
    elif data.get("format", {}).get("bit_rate") and info["abitrate"] is None:
        # audio only file where the stream has no bit_rate (common with ogg/flac)
        info["abitrate"] = int(data["format"]["bit_rate"])

    return info


# encoder detection for videous

_ENCODER_SET: Optional[frozenset[str]] = None
# flags column is 6 chars (V/A/S + 5 capability flags), then the encoder name
_ENC_LINE_RE = re.compile(r"^\s*([VAS][A-Za-z.]{5})\s+(\S+)")


def _available_encoders() -> frozenset[str]:
    """Run `ffmpeg -encoders` ONCE per session and cache the parsed names.
    The old version spawned a fresh ffmpeg (and reparsed the full list) for
    every single encoder query up to 7 spawns per session.
    Which is why i am recoding clipper into clipctl with more functions."""
    global _ENCODER_SET
    if _ENCODER_SET is None:
        try:
            out = subprocess.check_output(
                [FFMPEG, "-hide_banner", "-nostdin", "-encoders"],
                text=True, stderr=subprocess.STDOUT, timeout=10,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            out = ""
        names: set[str] = set()
        in_list = False
        for line in out.splitlines():
            if not in_list:
                # legend lines look like encoder lines (" V..... = Video"),
                # so only start collecting after the ------ separator
                if line.strip().startswith("------"):
                    in_list = True
                continue
            m = _ENC_LINE_RE.match(line)
            if m:
                names.add(m.group(2))
        _ENCODER_SET = frozenset(names)
    return _ENCODER_SET


def _ffmpeg_has_encoder(name: str) -> bool:
    return name in _available_encoders()


def _smoke_test(extra_in: list[str], encoder: str, vf: Optional[str]) -> tuple[bool, str]:
    """
    Try to encode one frame with the given encoder. Returns (ok, error_line).
    Uses a realistic size and pins the pixel format: the old 128x128 unfiltered
    test could hit hw encoder minimum resolution limits or let ffmpeg negotiate
    a pixel format (444/rgb) the encoder rejects -> false negative -> CPU fallback.
    """
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error"]
    cmd += extra_in
    cmd += ["-f", "lavfi", "-i", "color=c=black:s=640x360:d=1:r=30"]
    cmd += ["-vf", vf if vf else "format=yuv420p"]
    cmd += ["-frames:v", "1", "-c:v", encoder, "-f", "null", os.devnull]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return True, ""
        lines = [l for l in (r.stderr or "").strip().splitlines() if l.strip()]
        # ffmpeg prints the root cause first, then generic followup noise
        return False, lines[0] if lines else f"exit code {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "test encode timed out"
    except OSError as e:
        return False, str(e)


_ENCODER_CACHE: Optional[tuple[str, list[str], str]] = None


def detect_encoder() -> tuple[str, list[str], str]:
    """
    Return (encoder, hwaccel_args_for_decode, friendly_name). Cached per run.
    hwaccel_args_for_decode go BEFORE -i in the trim command (VAAPI needs this).
    """
    global _ENCODER_CACHE
    if _ENCODER_CACHE is not None:
        return _ENCODER_CACHE

    forced = os.environ.get("CLIPCTL_ENCODER", "").strip()
    if forced:
        hw = ["-vaapi_device", "/dev/dri/renderD128"] if forced == "h264_vaapi" else []
        print(f"  CLIPCTL_ENCODER={forced} set: skipping detection.")
        _ENCODER_CACHE = (forced, hw, f"forced ({forced})")
        return _ENCODER_CACHE

    sysname = platform.system()
    candidates: list[tuple[str, list[str], str, str]] = []

    if _ffmpeg_has_encoder("h264_nvenc"):
        candidates.append(("h264_nvenc", [], "format=yuv420p", "NVIDIA NVENC"))
    if _ffmpeg_has_encoder("h264_qsv"):
        candidates.append(("h264_qsv", [], "format=nv12", "Intel QSV"))
    if sysname == "Windows" and _ffmpeg_has_encoder("h264_amf"):
        candidates.append(("h264_amf", [], "format=yuv420p", "AMD AMF"))
    if sysname == "Linux" and _ffmpeg_has_encoder("h264_vaapi"):
        if Path("/dev/dri/renderD128").exists():
            candidates.append((
                "h264_vaapi",
                ["-vaapi_device", "/dev/dri/renderD128"],
                "format=nv12,hwupload",
                "VAAPI (AMD/Intel on Linux)",
            ))

    failed: list[tuple[str, list[str], str]] = []
    for enc, hw, vf, label in candidates:
        ok, err = _smoke_test(hw, enc, vf)
        if ok:
            _ENCODER_CACHE = (enc, hw, label)
            return _ENCODER_CACHE
        failed.append((enc, hw, label))
        print(f"  ! {label} ({enc}) is available but the test encode failed:")
        print(f"      {err}")

    if failed:
        enc, hw, label = failed[0]
        if confirm(f"  Use {label} anyway? (test can be a false negative) [y/N]: "):
            _ENCODER_CACHE = (enc, hw, f"{label} (forced, untested)")
            return _ENCODER_CACHE
        print("  Tip: you can force an encoder with the CLIPCTL_ENCODER env var,")
        print("       e.g.  CLIPCTL_ENCODER=h264_nvenc python3 clipctl.py")

    _ENCODER_CACHE = ("libx264", [], "CPU (libx264)")
    return _ENCODER_CACHE


# file discovery

def find_numbered_files(directory: Path, exts: set[str]) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for p in directory.iterdir():
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        try:
            n = int(p.stem)
        except ValueError:
            continue
        if n > 0:
            found.append((n, p))
    found.sort(key=lambda x: x[0])
    return found


def find_media_files(directory: Path) -> list[Path]:
    """All video/audio files in the directory, sorted by name."""
    out = [p for p in sorted(directory.iterdir())
           if p.is_file() and p.suffix.lower() in (VIDEO_EXTS | AUDIO_EXTS)]
    return out


def find_images(directory: Path) -> list[Path]:
    """All image files in the directory, sorted by name."""
    return [p for p in sorted(directory.iterdir())
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS]


def kind_of(p: Path) -> str:
    e = p.suffix.lower()
    if e in VIDEO_EXTS:
        return "video"
    if e in AUDIO_EXTS:
        return "audio"
    if e in IMAGE_EXTS:
        return "image"
    return "file"


# prompts

_RES_OPTIONS = {
    "1": ("1080p", 1920, 1080),
    "2": ("1440p", 2560, 1440),
    "3": ("4K",    3840, 2160),
    "4": ("original", None, None),
}


def prompt_resolution() -> tuple[str, Optional[int], Optional[int]]:
    print("\nOutput resolution:")
    print("  1) 1080p")
    print("  2) 1440p")
    print("  3) 4K")
    print("  4) Keep original")
    while True:
        choice = input("Choice [1-4]: ").strip()
        if choice in _RES_OPTIONS:
            return _RES_OPTIONS[choice]
        print("  Invalid. Pick 1, 2, 3 or 4.")


def prompt_clip_range(path: Path, duration: float) -> tuple[int, int]:
    print(f"\n[{path.name}]  duration = {fmt_time(duration)}")
    while True:
        s = input("  Range (HH:MM:SS*HH:MM:SS): ").strip()
        rng = parse_range(s)
        if rng is None:
            print("  Bad format. Example: 00:00:10*00:01:30  (end must be > start)")
            continue
        start, end = rng
        if end > duration + 0.5:
            print(f"  End {fmt_time(end)} is past clip end {fmt_time(duration)}.")
            continue
        return start, end


def resolve_numbered_duplicates(files: list[tuple[int, Path]]) -> list[tuple[int, Path]]:
    """
    1.mp4 and 1.avi both claim slot 1. Instead of listing the same number twice
    (and silently joining both), ask which file owns each contested number.
    """
    by_num: dict[int, list[Path]] = {}
    for n, p in files:
        by_num.setdefault(n, []).append(p)

    resolved: list[tuple[int, Path]] = []
    for n in sorted(by_num):
        paths = sorted(by_num[n], key=lambda p: p.name)
        if len(paths) == 1:
            resolved.append((n, paths[0]))
            continue
        print(f"\n  ! Multiple files are numbered {n}:")
        for i, p in enumerate(paths, start=1):
            print(f"      {i}) {p.name}")
        c = prompt_choice(f"  Which one is clip {n}? [1-{len(paths)}]: ",
                          [str(i) for i in range(1, len(paths) + 1)])
        resolved.append((n, paths[int(c) - 1]))
    return resolved


def pick_numbered(files: list[tuple[int, Path]]) -> list[tuple[int, Path]]:
    """Let the user pick which numbered clips to edit (joined in ascending order)."""
    print("\nWhich clips do you want to edit? (joined in ascending number order)")
    while True:
        s = input("Numbers comma separated, or 'a' for all: ").strip().lower()
        if s == "a":
            return list(files)
        try:
            wanted = sorted({int(x) for x in s.split(",") if x.strip()})
        except ValueError:
            print("  Invalid input. Example: 1,3,4   or just: a")
            continue
        if not wanted:
            print("  Pick at least one clip.")
            continue
        have = {n for n, _ in files}
        missing = [n for n in wanted if n not in have]
        if missing:
            print(f"  Not found: {missing}")
            continue
        chosen = set(wanted)
        return [(n, p) for n, p in files if n in chosen]


def prompt_choice(prompt: str, valid: list[str]) -> str:
    while True:
        c = input(prompt).strip()
        if c in valid:
            return c
        print(f"  Invalid. Options: {', '.join(valid)}")


def confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() == "y"


def select_files(files: list[Path]) -> list[Path]:
    """Generic multi pick over a file list, labelled by kind."""
    print("\nFiles in this directory:")
    for i, p in enumerate(files, start=1):
        print(f"  {i}) [{kind_of(p)}] {p.name}")
    print("  a) all of the above")
    while True:
        s = input("Pick number(s), comma separated, or 'a': ").strip().lower()
        if s == "a":
            return list(files)
        try:
            idx = [int(x) for x in s.split(",") if x.strip()]
        except ValueError:
            print("  Invalid input.")
            continue
        if idx and all(1 <= i <= len(files) for i in idx):
            # preserve listed order drop dupes
            seen: set[int] = set()
            return [files[i - 1] for i in idx if not (i in seen or seen.add(i))]
        print(f"  Numbers must be between 1 and {len(files)}.")


def pick_one_file(files: list[Path], prompt: str = "Pick a file") -> Path:
    """Single-file pick."""
    print("\nFiles in this directory:")
    for i, p in enumerate(files, start=1):
        print(f"  {i}) [{kind_of(p)}] {p.name}")
    valid = [str(i) for i in range(1, len(files) + 1)]
    c = prompt_choice(f"{prompt} [1-{len(files)}]: ", valid)
    return files[int(c) - 1]


def choose_ext(prompt: str, options: list[str], default: Optional[str] = None) -> str:
    """Numbered format chooser. If default is given, empty input accepts it."""
    print(prompt)
    line = "  ".join(f"{i+1}) {e}" for i, e in enumerate(options))
    print("  " + line)
    valid = [str(i + 1) for i in range(len(options))]
    hint = f" [enter = {default}]" if default else ""
    while True:
        c = input(f"Choice [1-{len(options)}]{hint}: ").strip()
        if not c and default:
            return default
        if c in valid:
            return options[int(c) - 1]
        # also accept the extension typed directly (with or without the dot)
        typed = ("." + c.lstrip(".")).lower()
        if typed in options:
            return typed
        print(f"  Invalid. Pick 1-{len(options)}" + (", or enter for default." if default else "."))


# video clipper

def build_scale_filter(encoder: str, src_w: int, src_h: int, tgt_w: int, tgt_h: int) -> Optional[str]:
    """Produce a -vf string. None means no filter needed."""
    needs_resize = (tgt_w, tgt_h) != (src_w, src_h)

    if encoder == "h264_vaapi":
        if needs_resize:
            return (
                f"format=nv12,hwupload,"
                f"scale_vaapi=w={tgt_w}:h={tgt_h}:force_original_aspect_ratio=decrease"
            )
        return "format=nv12,hwupload"

    if not needs_resize:
        return None

    return (
        f"scale={tgt_w}:{tgt_h}:force_original_aspect_ratio=decrease,"
        f"pad={tgt_w}:{tgt_h}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def build_video_trim_cmd(
    src: Path, dst: Path, start: int, end: int,
    tgt_w: int, tgt_h: int,
    encoder: str, hwaccel_pre: list[str], info: dict,
    family: str = "h264",
) -> list[str]:
    duration = end - start

    if family == "vp9":
        # webm parts
        cmd: list[str] = [FFMPEG, "-hide_banner", "-nostdin", "-y",
                          "-ss", str(start), "-i", str(src), "-t", str(duration)]
        needs_resize = (tgt_w, tgt_h) != (info["width"], info["height"])
        if needs_resize:
            cmd += ["-vf", (f"scale={tgt_w}:{tgt_h}:force_original_aspect_ratio=decrease,"
                            f"pad={tgt_w}:{tgt_h}:(ow-iw)/2:(oh-ih)/2:color=black")]
        cmd += ["-c:v", "libvpx-vp9", "-row-mt", "1"]
        if info.get("vbitrate"):
            cmd += ["-b:v", str(info["vbitrate"])]
        else:
            cmd += ["-crf", "32", "-b:v", "0"]
        cmd += ["-r", f"{info['fps']:.5f}"]
        if info.get("has_audio"):
            cmd += ["-c:a", "libopus", "-b:a", "128000", "-ar", "48000", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += [str(dst)]
        return cmd

    # h264 + aac family 
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
    cmd += hwaccel_pre
    cmd += ["-ss", str(start), "-i", str(src), "-t", str(duration)]

    vf = build_scale_filter(encoder, info["width"], info["height"], tgt_w, tgt_h)
    if vf:
        cmd += ["-vf", vf]

    cmd += ["-c:v", encoder]

    if info.get("vbitrate"):
        vb = info["vbitrate"]
        cmd += ["-b:v", str(vb), "-maxrate", str(int(vb * 1.5)), "-bufsize", str(vb * 2)]
    elif encoder == "libx264":
        cmd += ["-crf", "20", "-preset", "medium"]

    cmd += ["-r", f"{info['fps']:.5f}"]

    # aalways normalize to aac 48k stereo so concat copy is safe across parts
    if info.get("has_audio"):
        ab = info.get("abitrate") or 192_000
        cmd += ["-c:a", "aac", "-b:a", str(ab), "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]

    if dst.suffix.lower() == ".mp4":
        cmd += ["-movflags", "+faststart"]

    cmd += [str(dst)]
    return cmd


def concat_copy(parts: list[Path], output: Path) -> bool:
    """Concat with stream copy works because all parts share codec/res/fps."""
    list_file = output.parent / "_clipctl_concat.txt"
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for p in parts:
                safe = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        cmd = [
            FFMPEG, "-hide_banner", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(output),
        ]
        return _run_logged("concat", cmd)
    finally:
        try:
            list_file.unlink()
        except OSError:
            pass


def run_video_clipper(cwd: Path) -> int:
    files = find_numbered_files(cwd, VIDEO_EXTS)
    if not files:
        print("No numbered video files (1.mp4, 2.mkv, …) found in this directory.")
        return 1
    files = resolve_numbered_duplicates(files)

    nums = [n for n, _ in files]
    missing = [i for i in range(1, nums[-1] + 1) if i not in nums]
    if missing:
        print(f"  ! gap warning: missing {missing}")

    print(f"\nFound {len(files)} file(s):")
    for n, p in files:
        print(f"  {n}: {p.name}")

    files = pick_numbered(files)

    print("\nProbing…")
    probed: list[tuple[int, Path, dict]] = []
    for n, p in files:
        info = probe(p)
        if info is None or not info["has_video"] or not info["width"]:
            print(f"  ERROR: could not probe video stream in {p.name}")
            return 1
        probed.append((n, p, info))
        vb = f"{info['vbitrate']/1000:.0f}kbps" if info["vbitrate"] else "?"
        print(f"  {p.name}: {info['width']}x{info['height']}  {info['vcodec']}  "
              f"{fmt_time(info['duration'])}  {vb}  {info['fps']:.2f}fps")

    res_label, tgt_w, tgt_h = prompt_resolution()
    if tgt_w is None:
        first = probed[0][2]
        tgt_w, tgt_h = first["width"], first["height"]
        if any(i["width"] != tgt_w or i["height"] != tgt_h for _, _, i in probed):
            print(f"  ! clips have mixed resolutions; using first clip's "
                  f"{tgt_w}x{tgt_h} for all parts.")

    exts = {p.suffix.lower() for n, p in files}
    derived = next(iter(exts)) if len(exts) == 1 else ".mp4"
    if derived not in CLIPPER_CONTAINERS:
        derived = ".mp4"
    out_ext = choose_ext(
        "\nOutput container:", list(CLIPPER_CONTAINERS.keys()), default=derived)
    family = CLIPPER_CONTAINERS[out_ext]

    # h264 family
    if family == "h264":
        print("\nDetecting encoder…")
        encoder, hwaccel_pre, encoder_label = detect_encoder()
        print(f"  using: {encoder_label}  ({encoder})")
    else:
        encoder, hwaccel_pre, encoder_label = "libvpx-vp9", [], "libvpx-vp9 + libopus"
        print("  note: webm output uses VP9+Opus (CPU encoded, no GPU path = slower).")

    print("\nEnter the trim range for each clip:")
    ranges: list[tuple[int, Path, dict, int, int]] = []
    for n, p, info in probed:
        start, end = prompt_clip_range(p, info["duration"])
        ranges.append((n, p, info, start, end))

    outdir = cwd / OUTPUT_DIR_NAME
    output = outdir / f"output{out_ext}"
    if output.exists():
        print(f"\n  ! {OUTPUT_DIR_NAME}/{output.name} exists and will be overwritten.")

    print("\n=== Summary ===")
    print(f"  resolution: {tgt_w}x{tgt_h}  ({res_label})")
    print(f"  encoder:    {encoder_label}")
    print(f"  output:     {OUTPUT_DIR_NAME}/{output.name}")
    total = 0
    for _, p, _, s, e in ranges:
        d = e - s
        total += d
        print(f"    {p.name}: {fmt_time(s)} → {fmt_time(e)}  ({fmt_time(d)})")
    print(f"  total:      {fmt_time(total)}")

    if not confirm("\nProceed? [y/N]: "):
        print("Aborted.")
        return 0

    outdir.mkdir(exist_ok=True)
    tmp_dir = cwd / ".clipctl_tmp"
    tmp_dir.mkdir(exist_ok=True)
    parts: list[Path] = []
    try:
        for i, (n, p, info, start, end) in enumerate(ranges, start=1):
            part = tmp_dir / f"part_{i:03d}{out_ext}"
            print(f"\n[{i}/{len(ranges)}] trimming {p.name} → {fmt_time(end - start)}")
            cmd = build_video_trim_cmd(p, part, start, end, tgt_w, tgt_h, encoder, hwaccel_pre, info, family)
            r = subprocess.run(cmd)
            if r.returncode != 0:
                log_failure(f"trim {p.name}", cmd)
                print(f"  ERROR: ffmpeg failed on {p.name}")
                return 1
            parts.append(part)

        if len(parts) == 1:
            shutil.move(str(parts[0]), str(output))
            parts.clear()
        else:
            print(f"\nconcatenating → {output.name}")
            if not concat_copy(parts, output):
                print("ERROR: concat step failed.")
                return 1

        print(f"\n✓ done: {output}")
        return 0
    finally:
        for part in parts:
            try:
                part.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


# audio clipper

def audio_codec_for_ext(ext: str) -> tuple[str, Optional[int]]:
    return AUDIO_CODEC_MAP.get(ext, ("libmp3lame", 192_000))


def build_audio_trim_cmd(
    src: Path, dst: Path, start: int, end: int,
    sample_rate: int, info: dict,
) -> list[str]:
    duration = end - start
    codec, default_br = audio_codec_for_ext(dst.suffix.lower())

    cmd: list[str] = [
        FFMPEG, "-hide_banner", "-nostdin", "-y",
        "-ss", str(start), "-i", str(src), "-t", str(duration),
        "-vn",  # kill album art / accidental video streams
        "-c:a", codec, "-ar", str(sample_rate), "-ac", "2",
    ]
    if default_br is not None:
        br = info.get("abitrate") or default_br
        # dont inflate low bitrate sources, dont starve high ones
        cmd += ["-b:a", str(min(max(br, 96_000), 320_000))]
    cmd += [str(dst)]
    return cmd


def run_audio_clipper(cwd: Path) -> int:
    files = find_numbered_files(cwd, AUDIO_EXTS)
    if not files:
        print("No numbered audio files (1.mp3, 2.wav, …) found in this directory.")
        return 1
    files = resolve_numbered_duplicates(files)

    nums = [n for n, _ in files]
    missing = [i for i in range(1, nums[-1] + 1) if i not in nums]
    if missing:
        print(f"  ! gap warning: missing {missing}")

    print(f"\nFound {len(files)} file(s):")
    for n, p in files:
        print(f"  {n}: {p.name}")

    files = pick_numbered(files)

    print("\nProbing…")
    probed: list[tuple[int, Path, dict]] = []
    for n, p in files:
        info = probe(p)
        if info is None or not info["has_audio"]:
            print(f"  ERROR: could not probe audio stream in {p.name}")
            return 1
        probed.append((n, p, info))
        br = f"{info['abitrate']/1000:.0f}kbps" if info["abitrate"] else "?"
        sr = f"{info['sample_rate']}Hz" if info["sample_rate"] else "?"
        print(f"  {p.name}: {info['acodec']}  {fmt_time(info['duration'])}  {br}  {sr}")

    print("\nEnter the trim range for each clip:")
    ranges: list[tuple[int, Path, dict, int, int]] = []
    for n, p, info in probed:
        start, end = prompt_clip_range(p, info["duration"])
        ranges.append((n, p, info, start, end))

    exts = {p.suffix.lower() for _, p, _, _, _ in ranges}
    out_ext = next(iter(exts)) if len(exts) == 1 else ".mp3"
    outdir = cwd / OUTPUT_DIR_NAME
    output = outdir / f"output{out_ext}"
    if output.exists():
        print(f"\n  ! {OUTPUT_DIR_NAME}/{output.name} exists and will be overwritten.")

    # normalize every part to one sample rate so concat copy is safe
    sample_rate = probed[0][2]["sample_rate"] or 44100

    print("\n=== Summary ===")
    print(f"  codec:      {audio_codec_for_ext(out_ext)[0]}  @ {sample_rate}Hz stereo")
    print(f"  output:     {OUTPUT_DIR_NAME}/{output.name}")
    total = 0
    for _, p, _, s, e in ranges:
        d = e - s
        total += d
        print(f"    {p.name}: {fmt_time(s)} → {fmt_time(e)}  ({fmt_time(d)})")
    print(f"  total:      {fmt_time(total)}")

    if not confirm("\nProceed? [y/N]: "):
        print("Aborted.")
        return 0

    outdir.mkdir(exist_ok=True)
    tmp_dir = cwd / ".clipctl_tmp"
    tmp_dir.mkdir(exist_ok=True)
    parts: list[Path] = []
    try:
        for i, (n, p, info, start, end) in enumerate(ranges, start=1):
            part = tmp_dir / f"part_{i:03d}{out_ext}"
            print(f"\n[{i}/{len(ranges)}] trimming {p.name} → {fmt_time(end - start)}")
            cmd = build_audio_trim_cmd(p, part, start, end, sample_rate, info)
            r = subprocess.run(cmd)
            if r.returncode != 0:
                log_failure(f"trim {p.name}", cmd)
                print(f"  ERROR: ffmpeg failed on {p.name}")
                return 1
            parts.append(part)

        if len(parts) == 1:
            shutil.move(str(parts[0]), str(output))
            parts.clear()
        else:
            print(f"\nconcatenating → {output.name}")
            if not concat_copy(parts, output):
                print("ERROR: concat step failed.")
                return 1

        print(f"\n✓ done: {output}")
        return 0
    finally:
        for part in parts:
            try:
                part.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


# converter

def unique_output(outdir: Path, src: Path, target_ext: str) -> Path:
    """Result lives in the output folder; collisions from reruns get _2, _3, …"""
    dst = outdir / f"{src.stem}{target_ext}"
    n = 2
    while dst.exists():
        dst = outdir / f"{src.stem}_{n}{target_ext}"
        n += 1
    return dst


def remux_compatible(info: dict, target_ext: str) -> bool:
    """Only streamcopy codec combos that players actually support in the target."""
    v_ok = info.get("vcodec") in CONTAINER_VCODECS.get(target_ext, set())
    a_ok = (not info.get("has_audio")) or info.get("acodec") in CONTAINER_ACODECS.get(target_ext, set())
    return v_ok and a_ok


def convert_video_to_video(src: Path, dst: Path, info: dict) -> bool:
    """Remux only when the codecs are actually valid in the target, else reencode."""
    target_ext = dst.suffix.lower()

    if remux_compatible(info, target_ext):
        print(f"  {src.name} → {dst.name}: stream copy (remux, no quality loss)…")
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
               "-i", str(src), "-c", "copy"]
        if target_ext == ".mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += [str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            print("  ✓ remuxed")
            return True
        try:
            dst.unlink()
        except OSError:
            pass
        log_failure(f"remux {src.name}", cmd, r.stderr or "")
        print("  remux failed unexpectedly, re-encoding instead…")
    else:
        have = f"{info.get('vcodec')}+{info.get('acodec') or 'no audio'}"
        print(f"  {src.name} → {dst.name}: {have} isn't playable in {target_ext}, re-encoding…")

    if target_ext == ".webm":
        # webm only allows vp8/vp9/av1 + opus/vorbis, no hw h264 
        if not _ffmpeg_has_encoder("libvpx-vp9"):
            print("  ERROR: your ffmpeg build has no libvpx-vp9 encoder (needed for webm).")
            return False
        print("  encoder: libvpx-vp9 + libopus (webm requires these; CPU only, slow)")
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(src),
               "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1"]
        if info.get("has_audio"):
            cmd += ["-c:a", "libopus", "-b:a", "128k"]
        else:
            cmd += ["-an"]
        cmd += [str(dst)]
        return _run_logged(f"webm re-encode {src.name}", cmd)

    encoder, hwaccel_pre, label = detect_encoder()
    print(f"  encoder: {label}")
    # aac isn't valid in avi; mp3 is, ask me how i know xD
    audio_codec = "libmp3lame" if target_ext == ".avi" else "aac"

    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
    cmd += hwaccel_pre
    cmd += ["-i", str(src)]
    if encoder == "h264_vaapi":
        cmd += ["-vf", "format=nv12,hwupload"]
    cmd += ["-c:v", encoder]
    if info.get("vbitrate"):
        vb = info["vbitrate"]
        cmd += ["-b:v", str(vb), "-maxrate", str(int(vb * 1.5)), "-bufsize", str(vb * 2)]
    elif encoder == "libx264":
        cmd += ["-crf", "20", "-preset", "medium"]
    if info.get("has_audio"):
        ab = min(max(info.get("abitrate") or 192_000, 96_000), 320_000)
        cmd += ["-c:a", audio_codec, "-b:a", str(ab)]
    else:
        cmd += ["-an"]
    if target_ext == ".mp4":
        cmd += ["-movflags", "+faststart"]
    cmd += [str(dst)]
    return _run_logged(f"re-encode {src.name}", cmd)


def convert_to_audio(src: Path, dst: Path, info: dict) -> bool:
    """video->audio extraction, or audio->audio transcode."""
    codec, default_br = audio_codec_for_ext(dst.suffix.lower())
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vn", "-c:a", codec]
    if default_br is not None:
        br = info.get("abitrate") or default_br
        cmd += ["-b:a", str(min(max(br, 96_000), 320_000))]
    cmd += [str(dst)]
    return _run_logged(f"audio convert {src.name}", cmd)


def pick_convert_target(source_is_video: bool) -> str:
    if source_is_video:
        print("\nTarget format:")
        print("  video: " + "  ".join(f"{i+1}) {e}" for i, e in enumerate(VIDEO_TARGETS)))
        print("  audio: " + "  ".join(f"{i+1+len(VIDEO_TARGETS)}) {e}" for i, e in enumerate(AUDIO_TARGETS)))
        options = VIDEO_TARGETS + AUDIO_TARGETS
        valid = [str(i + 1) for i in range(len(options))]
        c = prompt_choice(f"Choice [1-{len(options)}]: ", valid)
        return options[int(c) - 1]
    return choose_ext("\nTarget audio format:", AUDIO_TARGETS)


def run_converter(cwd: Path) -> int:
    files = find_media_files(cwd)
    if not files:
        print("No media files found in this directory.")
        return 1

    selected = select_files(files)

    kinds = {kind_of(p) for p in selected}
    if kinds == {"video"}:
        target_ext = pick_convert_target(source_is_video=True)
    elif kinds == {"audio"}:
        target_ext = pick_convert_target(source_is_video=False)
    else:
        # mixed selection only audio targets make sense for everything
        print("\n  ! mixed video+audio selection: only audio target formats are valid.")
        target_ext = pick_convert_target(source_is_video=False)

    outdir = cwd / OUTPUT_DIR_NAME
    print("\n=== Summary ===")
    jobs: list[tuple[Path, Path]] = []
    for src in selected:
        if src.suffix.lower() == target_ext:
            print(f"  skipping {src.name} (already {target_ext})")
            continue
        dst = unique_output(outdir, src, target_ext)
        jobs.append((src, dst))
        print(f"  {src.name} → {OUTPUT_DIR_NAME}/{dst.name}")

    if not jobs:
        print("Nothing to do.")
        return 0

    if not confirm("\nProceed? [y/N]: "):
        print("Aborted.")
        return 0

    outdir.mkdir(exist_ok=True)
    failed: list[str] = []
    for i, (src, dst) in enumerate(jobs, start=1):
        print(f"\n[{i}/{len(jobs)}] converting {src.name}")
        info = probe(src)
        if info is None:
            print(f"  ERROR: could not probe {src.name}")
            failed.append(src.name)
            continue

        target_is_audio = target_ext in AUDIO_EXTS
        if target_is_audio:
            if not info["has_audio"]:
                print(f"  ERROR: {src.name} has no audio stream, skipping.")
                failed.append(src.name)
                continue
            ok = convert_to_audio(src, dst, info)
        else:
            if not info["has_video"]:
                print(f"  ERROR: {src.name} has no video stream, skipping.")
                failed.append(src.name)
                continue
            ok = convert_video_to_video(src, dst, info)

        if ok:
            print(f"  ✓ {dst.name}")
        else:
            print(f"  ERROR: conversion failed for {src.name}")
            failed.append(src.name)
            try:
                dst.unlink()
            except OSError:
                pass

    if failed:
        print(f"\nDone with {len(failed)} failure(s): {', '.join(failed)}")
        return 1
    print("\n✓ all conversions done.")
    return 0


# image converter

def available_image_targets() -> list[str]:
    targets = [".png", ".jpg", ".bmp", ".tiff", ".gif", ".ppm", ".tga"]
    if _ffmpeg_has_encoder("libwebp"):
        targets.insert(2, ".webp")
    if _ffmpeg_has_encoder("libaom-av1"):
        targets.append(".avif")
    return targets


def convert_image(src: Path, dst: Path, info: dict, webp_lossless: bool) -> bool:
    target = dst.suffix.lower()
    encoder = IMAGE_ENCODER_MAP.get(target)
    if encoder is None:
        # never silently write png bytes into a mislabeled .heic/.whatever
        print(f"  ERROR: no encoder mapping for {target}; refusing to write mislabeled bytes.")
        return False
    needs_flatten = target not in IMAGE_ALPHA_CAPABLE

    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if needs_flatten and info.get("width") and info.get("height"):
        # composite over white so transparency doesnt become black in jpg/bmp
        w, h = info["width"], info["height"]
        pf = FLATTEN_PIXFMT.get(target, "rgb24")
        cmd += ["-f", "lavfi", "-i", f"color=white:s={w}x{h}",
                "-i", str(src),
                "-filter_complex", f"[0][1]overlay=shortest=1,format={pf}[o]",
                "-map", "[o]"]
    else:
        cmd += ["-i", str(src)]

    cmd += ["-frames:v", "1", "-c:v", encoder]
    if encoder == "mjpeg":
        cmd += ["-q:v", "2"]
    elif encoder == "libwebp":
        cmd += ["-lossless", "1"] if webp_lossless else ["-quality", "90"]
    elif encoder == "libaom-av1":
        cmd += ["-still-picture", "1", "-crf", "30", "-b:v", "0"]
    cmd += [str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        lines = (r.stderr or "").strip().splitlines()
        if lines:
            print(f"      {lines[-1]}")
        log_failure(f"image convert {src.name}", cmd, r.stderr or "")
    return r.returncode == 0


def run_image_converter(cwd: Path) -> int:
    files = find_images(cwd)
    if not files:
        print("No image files found in this directory.")
        print(f"  (looked for: {', '.join(sorted(IMAGE_EXTS))})")
        return 1

    selected = select_files(files)
    targets = available_image_targets()
    target_ext = choose_ext("\nTarget image format:", targets)

    webp_lossless = False
    if target_ext == ".webp":
        webp_lossless = confirm("  Lossless webp? (bigger, pixel-perfect) [y/N]: ")

    outdir = cwd / OUTPUT_DIR_NAME
    print("\n=== Summary ===")
    jobs: list[tuple[Path, Path]] = []
    for src in selected:
        if src.suffix.lower() == target_ext:
            print(f"  skipping {src.name} (already {target_ext})")
            continue
        dst = unique_output(outdir, src, target_ext)
        jobs.append((src, dst))
        print(f"  {src.name} → {OUTPUT_DIR_NAME}/{dst.name}")

    if not jobs:
        print("Nothing to do.")
        return 0
    if target_ext in {".jpg", ".jpeg", ".bmp", ".ppm"}:
        print("  (transparency will be flattened onto white)")
    if not confirm("\nProceed? [y/N]: "):
        print("Aborted.")
        return 0

    outdir.mkdir(exist_ok=True)
    failed: list[str] = []
    for i, (src, dst) in enumerate(jobs, start=1):
        print(f"\n[{i}/{len(jobs)}] {src.name}")
        info = probe(src)
        if info is None or not info.get("has_video"):
            print(f"  ERROR: could not read {src.name} (unsupported or corrupt?)")
            failed.append(src.name)
            continue
        if convert_image(src, dst, info, webp_lossless):
            print(f"  ✓ {dst.name}")
        else:
            print(f"  ERROR: failed on {src.name}")
            failed.append(src.name)
            try:
                dst.unlink()
            except OSError:
                pass

    if failed:
        print(f"\nDone with {len(failed)} failure(s): {', '.join(failed)}")
        return 1
    print("\n✓ all images converted.")
    return 0


# video to gif

def run_video_to_gif(cwd: Path) -> int:
    files = [p for p in find_media_files(cwd) if kind_of(p) == "video"]
    if not files:
        print("No video files found in this directory.")
        return 1

    src = pick_one_file(files, "Which video")
    info = probe(src)
    if info is None or not info["has_video"]:
        print("ERROR: could not read that video.")
        return 1

    print(f"\n[{src.name}]  duration = {fmt_time(info['duration'])}")
    print("Trim range for the GIF (or press enter for the whole clip):")
    while True:
        s = input("  Range (HH:MM:SS*HH:MM:SS) [enter = whole]: ").strip()
        if not s:
            # keep the fractional tail int() would drop up to 1s off the end
            start, end = 0, (info["duration"] or 1.0)
            break
        rng = parse_range(s)
        if rng is None:
            print("  Bad format. Example: 00:00:03*00:00:08")
            continue
        start, end = rng
        if end > info["duration"] + 0.5:
            print(f"  End past clip end {fmt_time(info['duration'])}.")
            continue
        break

    fps_s = input("  GIF fps [default 15]: ").strip()
    fps = int(fps_s) if fps_s.isdigit() and int(fps_s) > 0 else 15
    w_s = input("  GIF width in px, keeps aspect [default 480]: ").strip()
    width = int(w_s) if w_s.isdigit() and int(w_s) > 0 else 480

    outdir = cwd / OUTPUT_DIR_NAME
    output = unique_output(outdir, src, ".gif")
    dur = end - start
    print("\n=== Summary ===")
    print(f"  source:  {src.name}  ({fmt_time(start)} → {fmt_time(end)}, {fmt_time(dur)})")
    print(f"  gif:     {fps}fps, {width}px wide → {OUTPUT_DIR_NAME}/{output.name}")
    if not confirm("\nProceed? [y/N]: "):
        print("Aborted.")
        return 0

    outdir.mkdir(exist_ok=True)
    tmp_dir = cwd / ".clipctl_tmp"
    tmp_dir.mkdir(exist_ok=True)
    palette = tmp_dir / "_palette.png"
    filt = f"fps={fps},scale={width}:-1:flags=lanczos"
    try:
        print("  [1/2] building color palette…")
        p1 = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
              "-ss", str(start), "-t", str(dur), "-i", str(src),
              "-vf", f"{filt},palettegen=stats_mode=diff", str(palette)]
        if subprocess.run(p1).returncode != 0 or not palette.exists():
            log_failure(f"gif palette {src.name}", p1)
            print("  ERROR: palette step failed.")
            return 1
        print("  [2/2] rendering GIF…")
        p2 = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
              "-ss", str(start), "-t", str(dur), "-i", str(src), "-i", str(palette),
              "-lavfi", f"{filt}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
              str(output)]
        if subprocess.run(p2).returncode != 0:
            log_failure(f"gif render {src.name}", p2)
            print("  ERROR: GIF render failed.")
            return 1
        size_mb = output.stat().st_size / 1_048_576
        print(f"\n✓ done: {output}  ({size_mb:.1f} MB)")
        return 0
    finally:
        try:
            palette.unlink()
        except OSError:
            pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


# compress to target size

def run_compress(cwd: Path) -> int:
    files = [p for p in find_media_files(cwd) if kind_of(p) == "video"]
    if not files:
        print("No video files found in this directory.")
        return 1

    src = pick_one_file(files, "Which video")
    info = probe(src)
    if info is None or not info["has_video"]:
        print("ERROR: could not read that video.")
        return 1
    if info["duration"] <= 0:
        print("ERROR: could not determine duration; can't target a size.")
        return 1

    print("\nTarget size:")
    presets = {"1": 10, "2": 25, "3": 50, "4": 100}
    print("  1) 10 MB    2) 25 MB    3) 50 MB    4) 100 MB    5) custom")
    c = prompt_choice("Choice [1-5]: ", ["1", "2", "3", "4", "5"])
    if c == "5":
        while True:
            mb_s = input("  Target MB: ").strip()
            try:
                target_mb = float(mb_s)
                if target_mb > 0:
                    break
            except ValueError:
                pass
            print("  Enter a positive number.")
    else:
        target_mb = presets[c]

    keep_audio = info["has_audio"]
    audio_kbps = 128 if keep_audio else 0
    # aim slightly under target so container overhead doesnt push us over
    budget_kbits = target_mb * 8 * 1024 * 0.93
    video_kbps = budget_kbits / info["duration"] - audio_kbps
    if video_kbps < 100:
        print(f"  ! {target_mb:.0f} MB over {fmt_time(info['duration'])} is very tight "
              f"({video_kbps:.0f} kbps video). Quality will suffer badly.")
        if not confirm("  Continue anyway? [y/N]: "):
            return 0
        video_kbps = max(video_kbps, 50)

    print("\nEncoding passes:")
    print("  1) Single pass  - faster, uses your GPU encoder if available.")
    print("  2) Two pass     - encodes twice: an analysis pass, then the real one.")
    print("                    Hits the target size more precisely and spreads")
    print("                    bitrate to where the video needs it (better quality")
    print("                    at the same size). Runs on CPU (libx264) for accuracy,")
    print("                    so it's slower — worth it for a tight Discord limit.")
    passes = prompt_choice("Choice [1-2]: ", ["1", "2"])

    outdir = cwd / OUTPUT_DIR_NAME
    output = unique_output(outdir, src, ".mp4")
    vb = f"{int(video_kbps)}k"

    if passes == "2":
        encoder_label = "libx264 (2-pass, CPU)"
    else:
        encoder, hwaccel_pre, encoder_label = detect_encoder()

    print("\n=== Summary ===")
    print(f"  source:   {src.name}  ({fmt_time(info['duration'])})")
    print(f"  target:   ~{target_mb:.0f} MB  →  {int(video_kbps)}k video"
          f"{' + 128k audio' if keep_audio else ' (no audio)'}")
    print(f"  encoder:  {encoder_label}")
    print(f"  output:   {OUTPUT_DIR_NAME}/{output.name}")
    if not confirm("\nProceed? [y/N]: "):
        print("Aborted.")
        return 0

    outdir.mkdir(exist_ok=True)

    if passes == "2":
        ok = _compress_two_pass(cwd, src, output, vb, keep_audio)
    else:
        ok = _compress_single_pass(src, output, vb, video_kbps, keep_audio,
                                   encoder, hwaccel_pre)

    if not ok:
        print("ERROR: compression failed.")
        try:
            output.unlink()
        except OSError:
            pass
        return 1

    final_mb = output.stat().st_size / 1_048_576
    verdict = "under target ✓" if final_mb <= target_mb else "slightly over try one preset lower"
    print(f"\n✓ done: {output}  ({final_mb:.1f} MB, {verdict})")
    return 0


def _compress_single_pass(src: Path, output: Path, vb: str, video_kbps: float,
                          keep_audio: bool, encoder: str, hwaccel_pre: list[str]) -> bool:
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
    cmd += hwaccel_pre
    cmd += ["-i", str(src)]
    if encoder == "h264_vaapi":
        cmd += ["-vf", "format=nv12,hwupload"]
    cmd += ["-c:v", encoder, "-b:v", vb, "-maxrate", vb, "-bufsize", f"{int(video_kbps*2)}k"]
    if keep_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(output)]
    return _run_logged(f"compress {src.name}", cmd)


def _compress_two_pass(cwd: Path, src: Path, output: Path, vb: str, keep_audio: bool) -> bool:
    """
    Classic libx264 two-pass: pass 1 writes a stats file, pass 2 uses it to
    allocate bitrate exactly. Log lives in the temp dir and is cleaned up so it
    never litters the working directory. Hardware encoders don't support true
    log based two pass, which is why this path is CPUonly.
    """
    tmp_dir = cwd / ".clipctl_tmp"
    tmp_dir.mkdir(exist_ok=True)
    logprefix = str(tmp_dir / "ffpass")
    try:
        print("\n  [1/2] analysis pass…")
        p1 = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-stats", "-y", "-i", str(src),
              "-c:v", "libx264", "-preset", "medium", "-b:v", vb,
              "-pass", "1", "-passlogfile", logprefix, "-an", "-f", "null", os.devnull]
        if subprocess.run(p1).returncode != 0:
            log_failure(f"2-pass analysis {src.name}", p1)
            return False
        print("  [2/2] encoding pass…")
        p2 = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(src),
              "-c:v", "libx264", "-preset", "medium", "-b:v", vb,
              "-pass", "2", "-passlogfile", logprefix]
        if keep_audio:
            p2 += ["-c:a", "aac", "-b:a", "128k"]
        else:
            p2 += ["-an"]
        p2 += ["-movflags", "+faststart", str(output)]
        return _run_logged(f"2-pass encode {src.name}", p2)
    finally:
        for lg in tmp_dir.glob("ffpass*"):
            try:
                lg.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


# audio track for mute and replace

def run_audio_track(cwd: Path) -> int:
    vids = [p for p in find_media_files(cwd) if kind_of(p) == "video"]
    if not vids:
        print("No video files found in this directory.")
        return 1

    src = pick_one_file(vids, "Which video")
    print("\n  1) Mute (remove audio)")
    print("  2) Replace audio with a music/audio file")
    op = prompt_choice("Choice [1-2]: ", ["1", "2"])

    outdir = cwd / OUTPUT_DIR_NAME
    src_ext = src.suffix.lower()

    if op == "1":
        # mute for video stream is copied untouched, so keeping the SAME container
        # is always safe. Forcing a different one (e.g. avi -> mp4) can produce
        # codec/container combos players reject (mp4v-in-mp4 class).
        output = unique_output(outdir, src, src_ext)
        print(f"\n  {src.name} → {OUTPUT_DIR_NAME}/{output.name}  (audio removed)")
        if not confirm("Proceed? [y/N]: "):
            return 0
        outdir.mkdir(exist_ok=True)
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-c:v", "copy", "-an"]
        if output.suffix.lower() == ".mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += [str(output)]
        ok = _run_logged(f"mute {src.name}", cmd)
        print(f"\n✓ done: {output}" if ok else "ERROR: mute failed.")
        return 0 if ok else 1

    # replace audio for video is stream copied, only the new audio is encoded 
    # so the audio codec must be one the sources container actually allows.
    AUDIO_FOR_CONTAINER = {
        ".mp4": ("aac", "192k"), ".m4v": ("aac", "192k"), ".mov": ("aac", "192k"),
        ".mkv": ("aac", "192k"), ".ts":  ("aac", "192k"),
        ".webm": ("libopus", "160k"),   # webm rejects aac outright
        ".avi": ("libmp3lame", "192k"),  # aac in avi is nonstandard
    }
    if src_ext in AUDIO_FOR_CONTAINER:
        out_ext = src_ext
    else:
        # wmv/flv/mpg etc, mkv can hold the copied video stream + aac
        out_ext = ".mkv"
        print(f"\n  note: {src_ext} output isn't supported for this; writing .mkv instead")
        print("        (holds the untouched video stream + the new audio).")
    acodec, abitrate = AUDIO_FOR_CONTAINER.get(out_ext, ("aac", "192k"))
    output = unique_output(outdir, src, out_ext)

    tracks = [p for p in find_media_files(cwd)
              if kind_of(p) == "audio" or (kind_of(p) == "video" and p != src)]
    if not tracks:
        print("No audio/music files found to use as the new track.")
        return 1
    music = pick_one_file(tracks, "Which audio track")
    minfo = probe(music)
    if minfo is None or not minfo["has_audio"]:
        print(f"ERROR: {music.name} has no audio stream to use.")
        return 1

    print("\n  Length handling:")
    print("  1) Match video length (trim or loop music to fit)")
    print("  2) Stop at whichever is shorter")
    lenmode = prompt_choice("Choice [1-2]: ", ["1", "2"])

    print(f"\n  video: {src.name}")
    print(f"  audio: {music.name}  → {acodec}")
    print(f"  → {OUTPUT_DIR_NAME}/{output.name}")
    if not confirm("Proceed? [y/N]: "):
        return 0

    outdir.mkdir(exist_ok=True)
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
    if lenmode == "1":
        # loop the audio input, shortest then cuts it to the video length
        cmd += ["-i", str(src), "-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-i", str(src), "-i", str(music)]
    cmd += ["-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", acodec, "-b:a", abitrate, "-shortest"]
    if output.suffix.lower() == ".mp4":
        cmd += ["-movflags", "+faststart"]
    cmd += [str(output)]
    ok = _run_logged(f"replace audio {src.name}", cmd)
    print(f"\n✓ done: {output}" if ok else "ERROR: audio replace failed.")
    return 0 if ok else 1


# grab a frame as an image

def run_grab_frame(cwd: Path) -> int:
    vids = [p for p in find_media_files(cwd) if kind_of(p) == "video"]
    if not vids:
        print("No video files found in this directory.")
        return 1

    src = pick_one_file(vids, "Which video")
    info = probe(src)
    if info is None or not info["has_video"]:
        print("ERROR: could not read that video.")
        return 1

    print(f"\n[{src.name}]  duration = {fmt_time(info['duration'])}")
    while True:
        t = input("  Timestamp to grab (HH:MM:SS): ").strip()
        secs = parse_time(t)
        if secs is None:
            print("  Bad format. Example: 00:01:23")
            continue
        if secs > info["duration"] + 0.5:
            print(f"  Past clip end {fmt_time(info['duration'])}.")
            continue
        break

    img_targets = available_image_targets()
    fmt = choose_ext("  Image format:", img_targets, default=".png")

    outdir = cwd / OUTPUT_DIR_NAME
    # build the name directly, round tripping through Path.with_name would
    # let pathlib treat dots inside the filename as an extension and truncate
    stamp = fmt_time(secs).replace(":", "-")
    output = outdir / f"{src.stem}_{stamp}{fmt}"
    n = 2
    while output.exists():
        output = outdir / f"{src.stem}_{stamp}_{n}{fmt}"
        n += 1
    print(f"\n  grab {fmt_time(secs)} → {OUTPUT_DIR_NAME}/{output.name}")
    if not confirm("Proceed? [y/N]: "):
        return 0

    outdir.mkdir(exist_ok=True)
    enc = IMAGE_ENCODER_MAP.get(fmt)
    if enc is None:
        print(f"ERROR: no encoder mapping for {fmt}.")
        return 1
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-ss", str(secs), "-i", str(src), "-frames:v", "1"]
    if enc == "mjpeg":
        cmd += ["-q:v", "2"]
    elif enc == "libwebp":
        cmd += ["-quality", "92"]
    elif enc == "libaom-av1":
        cmd += ["-still-picture", "1", "-crf", "30", "-b:v", "0"]
    cmd += [str(output)]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        log_failure(f"grab frame {src.name}", cmd)
    # a seek at/right past EOF can exit 0 while writing nothing verify
    ok = r.returncode == 0 and output.exists() and output.stat().st_size > 0
    if not ok and output.exists():
        try:
            output.unlink()
        except OSError:
            pass
    print(f"\n✓ done: {output}" if ok
          else "ERROR: frame grab failed (timestamp may be past the last frame).")
    return 0 if ok else 1


# main menu

_TITLE = "clipctl - ffmpeg cli multimedia toolbox"
BANNER = (
    "\n  ┌" + "─" * (len(_TITLE) + 4) + "┐"
    "\n  │  " + _TITLE + "  │"
    "\n  └" + "─" * (len(_TITLE) + 4) + "┘"
)


def main() -> int:
    cwd = Path.cwd()
    print(BANNER)
    print(f"  working dir: {cwd}")

    actions = {
        "1": ("Clip & join videos   (trim numbered clips → one montage)", run_video_clipper),
        "2": ("Video → GIF          (turn a clip into a GIF)", run_video_to_gif),
        "3": ("Compress video       (shrink to a target size, e.g. Discord)", run_compress),
        "4": ("Audio track          (mute, or replace with music)", run_audio_track),
        "5": ("Grab frame           (save a frame as an image)", run_grab_frame),
        "6": ("Clip & join audio    (trim numbered audio → one track)", run_audio_clipper),
        "7": ("Convert images       (png / jpg / webp / bmp / gif / …)", run_image_converter),
        "8": ("Convert format       (video↔video, video→audio, audio↔audio)", run_converter),
    }

    while True:
        print("\nWhat do you want to do?")
        print("  ── video ─────────────────────────────────────────────")
        for k in ("1", "2", "3", "4", "5"):
            print(f"  {k}) {actions[k][0]}")
        print("  ── audio ─────────────────────────────────────────────")
        print(f"  6) {actions['6'][0]}")
        print("  ── image ─────────────────────────────────────────────")
        print(f"  7) {actions['7'][0]}")
        print("  ── convert ───────────────────────────────────────────")
        print(f"  8) {actions['8'][0]}")
        print("  ──────────────────────────────────────────────────────")
        print("  q) Quit")

        choice = prompt_choice("Choice: ", list(actions.keys()) + ["q"])
        if choice == "q":
            print("bye.")
            return 0

        try:
            actions[choice][1](cwd)
        except KeyboardInterrupt:
            print("\n  (cancelled, back to menu)")

        input("\n[enter] to return to the menu…")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\ninterrupted.")
        sys.exit(130)
