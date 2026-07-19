# clipctl

A monolithic CLI multimedia toolbox built on `ffmpeg`. Clip and join video/audio, convert between video/audio/image formats, make GIFs, compress clips to a target size, swap audio tracks, and grab frames and all from one interactive prompt.
Built for turning NVIDIA Instant Replay dumps into finished montages without opening an NLE.
It has automatic GPU encoder detection.

## Features

- **Video clipper** - auto detects numbered clips (`1.mp4`, `2.mkv`, …), lets you pick which ones to include, trim each, and joins them into a single `output.<ext>`.
- **Audio clipper** - same workflow for numbered audio files (`1.mp3`, `2.wav`, …).
- **Format converter** - video↔video, video→audio, audio↔audio. Video to video does a zero loss stream copy remux when the codecs allow it, and re encodes when they don't.
- **Image converter** - png, jpg, webp, bmp, tiff, gif, plus avif/tga when your ffmpeg build supports them (capability checked). Converting a transparent image to a no alpha format (jpg/bmp) flattens onto white instead of ffmpeg's default black.
- **Video → GIF** - 2 pass palettegen for clean colors; pick fps and width.
- **Compress to target size** - give it a size (or a 10/25/50/100 MB preset) and it computes the bitrate to land under it. Handy for Discord/upload limits. Note: For Discord standard limit you need to select
custom size and enter `8` to recieve an 8mb file perfect for discord, of course if you have nitro you can increase it.
- **Audio track tools** - mute a clip, or replace gameplay audio with a music file (loops or trims to fit). Container aware: opus for webm, mp3 for avi, so the mux never fails.
- **Grab frame** - save any frame as an image (thumbnails, Steam screenshots).
- **webm montages** - the video clipper can output webm (VP9+Opus), not just mp4/mkv/mov.
- **Codec aware remuxing** - the converter checks that the source codecs are actually *playable* in the target container before stream copying. ffmpeg will happily mux things like PCM into mp4 (`ipcm`) that no player on earth opens; clipctl won't.
- **Hardware encoder auto detect** - NVENC → QSV → AMF/VAAPI → libx264, with a test encode to confirm the encoder actually works before committing to it. If a GPU encoder is present but fails the test, you see the real ffmpeg error and can override.
- **Mixed format safe** - clips with different resolutions, sample rates, or containers are normalized before concatenation so the join doesn't desync or fail.
- **Failure diagnostics that persist** - every failed ffmpeg command lands in `clipctl_output/errors.log` with the exact command line and stderr, so a broken encode is reportable, not a shrug.
- **Single file**, single dependency: `ffmpeg` + `ffprobe` on `PATH`. No pip packages, no requirements.txt, no config files.
- **Cross platform**: Linux x86_64, Linux aarch64, Windows x86_64, Windows arm64.
- **Preserves source bitrate** by probing each input with ffprobe and matching the output bitrate.
- **Resolution selector**: 1080p, 1440p, 4K, or keep original.
- **Per clip trim ranges** through a simple interactive prompt.
- **Auto discovers numbered files.** Scans the current directory for `1.<ext>`, `2.<ext>`, sorts ascending, and warns about gaps. If two files claim the same number (`1.mp4` + `1.avi`), it asks which one you meant instead of guessing.
- **Clean output.** Everything the tool creates lands in a `clipctl_output/` folder, your clip dump stays untouched, and old results never pollute the file scan.

## Requirements

- Python 3.9+
- `ffmpeg` and `ffprobe` available on `PATH`

```bash
# Linux
sudo apt install ffmpeg      # Debian/Ubuntu
sudo dnf install ffmpeg      # Fedora
sudo pacman -S ffmpeg        # Arch

# Windows
winget install ffmpeg
```

### GPU drivers (optional)

You don't need a GPU, the tool falls back to CPU encoding. If you want hardware acceleration:

| GPU             | What you need                                                                 |
| --------------- | ----------------------------------------------------------------------------- |
| NVIDIA          | Standard NVIDIA driver. Most ffmpeg builds include NVENC.                     |
| AMD (Windows)   | AMD driver (AMF ships with it). Use a recent ffmpeg build with h264_amf.      |
| AMD (Linux)     | mesa-va-drivers package; /dev/dri/renderD128 must exist.                      |
| Intel (any OS)  | Intel Media Driver (intel-media-va-driver on Debian/Ubuntu).                  |

The tool runs a 1 frame test encode through each candidate before picking it, so misconfigured GPUs get caught up front so you'll never wait 5 minutes to find out NVENC didn't actually work :3

---

## Usage

Drop your clips in a folder, name them `1`, `2`, `3`... in the order you want them joined, and run:

```bash
python3 clipctl.py        # Linux
python clipctl.py         # Windows
```

You'll get a menu:

```
What do you want to do?
  ── video ─────────────────────────────────────────────
  1) Clip & join videos   (trim numbered clips → one montage)
  2) Video → GIF          (turn a clip into a GIF)
  3) Compress video       (shrink to a target size, e.g. Discord)
  4) Audio track          (mute, or replace with music)
  5) Grab frame           (save a frame as an image)
  ── audio ─────────────────────────────────────────────
  6) Clip & join audio    (trim numbered audio → one track)
  ── image ─────────────────────────────────────────────
  7) Convert images       (png / jpg / webp / bmp / gif / …)
  ── convert ───────────────────────────────────────────
  8) Convert format       (video↔video, video→audio, audio↔audio)
  q) Quit
```

The **clip & join** and **convert format** modes work on files named `1`, `2`, `3`… as before. The other modes (GIF, compress, audio track, grab frame) act on a single file you pick from a list, and the image converter works on any images in the folder.

Answer the prompts. The result is `output.<ext>` in the same folder, the extension matches your inputs if they all share one, otherwise `.mp4` (video) / `.mp3` (audio).

### File naming rules

- Filename stem must be a positive whole number: `1.mp4`, `2.mkv`, `42.mov`.
- `01.mp4`, `clip1.mp4`, `Clip 1.mp4` won't be detected!
- If the same number exists with two extensions (`1.mp4` and `1.avi`), the tool prompts you to pick which file is clip 1.
- Supported video extensions: `.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`, `.m4v`, `.flv`, `.ts`, `.mpg`, `.mpeg`, `.wmv`.
- Same idea for audio: `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`, `.aac`, `.opus`, `.wma`.
- The numbered file rule only applies to the clip & join modes. Image conversion, GIF, compress, audio track and grab frame just let you pick a file from a list , name it whatever.

---

### Picking clips

After listing the numbered files it found, the tool asks which ones you want:

```
Which clips do you want to edit? (joined in ascending number order)
Numbers comma separated, or 'a' for all: 1,3,4
```

Whatever you pick, clips are always joined in ascending number order.

### Trimming

Ranges use `HH:MM:SS*HH:MM:SS` (start * end):

```
[1.mp4]  duration = 00:00:32
  Range (HH:MM:SS*HH:MM:SS): 00:00:04*00:00:18
```

Clips are trimmed individually, then concatenated into `output.<ext>`.

## Time syntax

```
HH:MM:SS*HH:MM:SS
```

- Two timestamps separated by a single `*`.
- Each timestamp is hours:minutes:seconds. Hours can be 1 to 4 digits (yes, you can address a 100+ hour file).
- The second timestamp must be **strictly later** than the first.
- The second timestamp must not exceed the clip's duration.

Examples:

| Range                   | Meaning                                          |
| ----------------------- | ------------------------------------------------ |
| 00:00:10*00:01:30       | Keep from 0:10 to 1:30 (80 seconds total)        |
| 00:05:00*00:05:45       | Keep a 45 second slice starting at 5:00          |
| 01:00:00*01:30:00       | Keep 30 minutes starting at 1 hour in            |
| 0:00:00*0:00:30         | Keep the first 30 seconds                        |

If you mistype, the tool reprompts; it doesn't crash or guess like others :3

---

### Converting

Pick a file (or several comma separated, or `a` for all), pick a target format, confirm.

- **Video → video**: stream copy (instant, lossless) when the source codecs are valid in the target container, otherwise re encode with the detected encoder.
- **Video → audio**: extracts and encodes the audio track.
- **Audio → audio**: straight transcode.
- **Converting to webm** always re encodes with VP9 + Opus , the only codecs webm allows. CPU only and slow by nature; no hardware shortcut for VP9. (The video clipper can also output webm directly same VP9+Opus path.)
- **Converting to avi** uses mp3 audio (aac in avi is nonstandard and some players choke on it).
- Results land in `clipctl_output/` named after the source. Existing files are never overwritten , rerunning the same conversion gets `name_2.ext`, `name_3.ext`, …

---

## Images

Mode **7** converts any images in the current folder. Pick files (or `a` for all), pick a target format, done , results land in `clipctl_output/`.

- Formats: png, jpg, bmp, tiff, gif, ppm, tga, plus **webp** and **avif** if your ffmpeg build has `libwebp` / `libaom-av1` (the menu only offers what's actually available).
- **Transparency**: converting an alpha image (transparent png/webp) to a format without alpha (jpg, bmp) flattens it onto **white**. ffmpeg's default would make it black, clipctl composites over white so logos/cutouts look right.
- **webp**: you're asked lossy (quality 90) vs lossless.
- Animated gif/webp are treated as single images (first frame); this isn't an animation editor.

## GIFs

Mode **2** turns a video into a GIF using the proper 2 pass palette method (generate an optimized palette, then apply it) so colors don't band. You pick a trim range (or the whole clip), fps (default 15), and width (default 480px, aspect preserved). Lower fps + narrower width = smaller file.

## Compressing to a size

Mode **3** targets a file size. Give it a preset (10/25/50/100 MB) or a custom number; it computes the video bitrate from `size / duration` (reserving 128k for audio, aiming ~7% under so container overhead doesn't push you over). It reports the final size and whether it landed under target. Very short or very tiny targets get a quality warning first.

You choose **1 or 2 passes**:

- **Single pass** - fast, uses your detected GPU encoder (NVENC/QSV/etc). The bitrate is capped (`-maxrate`), so it lands close to target on most footage. Good enough for the common case.
- **Two pass** - encodes twice: an analysis pass that measures the video, then the real pass that spends the bitrate budget where it's actually needed. Hits the target size **more precisely** and gives **better quality at the same size**. It runs on **CPU (libx264)** , true two pass is a CPU encoder feature, and it's what actually nails an exact size , so it's slower than single pass. Worth it when you're squeezing under a hard limit (e.g. Discord's 8 MB) and the footage is busy.

Rule of thumb: single pass for a quick share, two pass when the size limit is strict and you can wait a bit. On hard/noisy footage the difference is real , in testing, a 2 pass encode to a 3 MB target landed at 2.7 MB, where a single pass guess would over or undershoot.

## Audio track (mute / replace)

Mode **4** either:
- **Mutes** the video = the video stream is copied untouched into the **same container** as the source (instant, no re encode). Same container is deliberate: forcing e.g. avi→mp4 around a copied stream is exactly how you end up with unplayable mp4v-in-mp4 files.
- **Replaces** the audio with a music/audio file you pick (the donor is checked for an actual audio stream first, another video's audio works too). Video is stream copied; only the new audio is encoded, with the codec chosen per container so the mux can't fail: **aac** for mp4/mkv/mov/ts, **opus** for webm (webm rejects aac), **mp3** for avi. Exotic sources (wmv/flv/mpg) fall back to **.mkv** with a printed note, since mkv can hold the untouched video stream. You choose whether to loop/trim the music to the video length, or stop at whichever is shorter.

Perfect for montages: record gameplay, mute it, drop a track over the top.

## Grab a frame

Mode **5** saves a single frame at a timestamp you give (`HH:MM:SS`) as an image in your chosen format. Good for montage thumbnails or Steam store screenshots.

---

## How encoder selection works

On first use per session the tool:

1. Asks ffmpeg which encoders are compiled in (`ffmpeg -encoders`).
2. Tries candidates in this order: NVENC → QSV → AMF (Windows) / VAAPI (Linux) → libx264.
3. For each candidate, runs a 1 frame test encode at a realistic size and pixel format. The first to pass wins.

This catches the common "ffmpeg has the encoder built in but the driver isn't actually working" case, which would otherwise fail several minutes into your encode.

If a GPU encoder is present but fails the test, the tool prints the actual ffmpeg error (e.g. `Cannot load libcuda.so.1`), asks whether you want to use it anyway (the test can false negative), and only then falls back to libx264. You can also skip detection entirely:

```bash
CLIPCTL_ENCODER=h264_nvenc python3 clipctl.py        # Linux
set CLIPCTL_ENCODER=h264_nvenc && python clipctl.py  # Windows cmd
```

---

## Output

- **Location**: everything goes into `clipctl_output/` inside the working directory (created on first use). Clipper results are named `output.<ext>`, converter results keep the source name.
- **Container**: the clip & join modes let you choose the output container (mp4/mkv/mov/webm), defaulting to your inputs extension when they all share one, else mp4. Picking webm switches the whole pipeline to VP9+Opus. The converter keeps the source name with the new extension.
- **Resolution**: whatever you picked. With "original" + mixed resolution inputs, the first clip's resolution is used (concat needs uniform size).
- **Video bitrate**: matches each source's bitrate.
- **Frame rate**: preserved per source.
- **Audio**: re encoded to AAC 48kHz stereo. Stream copy isn't safe across mid frame trim points or mixed sample rates, so the tool re encodes for accuracy.

---

## What you'll see when it runs

Run from a folder with 1.mp4 (15s) and 2.mp4 (10s), pick mode 1:

```
  ┌───────────────────────────────────────────┐
  │  clipctl - ffmpeg cli multimedia toolbox  │
  └───────────────────────────────────────────┘
  working dir: /home/motan/obs

Choice: 1

Found 2 file(s):
  1: 1.mp4
  2: 2.mp4

Which clips do you want to edit? (joined in ascending number order)
Numbers comma separated, or 'a' for all: a

Probing…
  1.mp4: 1920x1080  h264  00:00:15  4499kbps  30.00fps
  2.mp4: 1920x1080  h264  00:00:10  4496kbps  30.00fps

Output resolution:
  1) 1080p
  2) 1440p
  3) 4K
  4) Keep original
Choice [1-4]: 4

Output container:
  1) .mp4  2) .mkv  3) .mov  4) .webm
Choice [1-4] [enter = .mp4]:

Detecting encoder…
  using: NVIDIA NVENC  (h264_nvenc)

Enter the trim range for each clip:

[1.mp4]  duration = 00:00:15
  Range (HH:MM:SS*HH:MM:SS): 00:00:02*00:00:08

[2.mp4]  duration = 00:00:10
  Range (HH:MM:SS*HH:MM:SS): 00:00:01*00:00:05

=== Summary ===
  resolution: 1920x1080  (original)
  encoder:    NVIDIA NVENC
  output:     clipctl_output/output.mp4
    1.mp4: 00:00:02 → 00:00:08  (00:00:06)
    2.mp4: 00:00:01 → 00:00:05  (00:00:04)
  total:      00:00:10

Proceed? [y/N]: y

[1/2] trimming 1.mp4 → 00:00:06
[2/2] trimming 2.mp4 → 00:00:04

concatenating → output.mp4

✓ done: /home/motan/obs/clipctl_output/output.mp4
```

(The encoder lines depend on your machine , on a box where the GPU test fails you'll see the actual ffmpeg error and a "use it anyway?" prompt instead.)

### Prompt reference

| Stage                 | What it asks                       | Valid input                              |
| --------------------- | ---------------------------------- | ---------------------------------------- |
| Duplicate number      | Which one is clip N? [1-K]:        | the listed file's number                 |
| Clip selection        | Numbers comma separated, or 'a':   | e.g. 1,3,4 or a for all                  |
| Resolution            | Choice [1-4]:                      | 1, 2, 3, or 4                            |
| Output container      | Choice [1-4] [enter = .mp4]:       | 1-4, an ext like `webm`, or enter        |
| Trim range (per file) | Range (HH:MM:SS*HH:MM:SS):         | A range, e.g. 00:00:05*00:01:00          |
| Compress passes       | Choice [1-2]:                      | 1 (single, fast) or 2 (two pass)         |
| Confirm               | Proceed? [y/N]:                    | y to continue, anything else aborts      |

---

## Notes

- Trims are **frame accurate**: each part is re encoded, and `-ss` before `-i` with transcoding decodes from the previous keyframe and drops frames up to your exact start point. Cuts land where you type them.
- All temp files (trim parts, GIF palettes, two pass logs) live in a `.clipctl_tmp/` folder in the working directory and are cleaned up automatically, including on failure or `Ctrl+C`.
- Nothing is uploaded anywhere, it's a local wrapper around your own `ffmpeg` binary.

## Troubleshooting

**ffmpeg and ffprobe must be installed and on PATH**
Install ffmpeg. On Windows, confirm the folder containing ffmpeg.exe is in your PATH environment variable. Open a new shell after editing PATH.

**No numbered video files found**
Files must literally be 1.mp4, 2.mkv, etc. Not clip1.mp4. Not 01.mp4. Not "1 - intro.mp4". Rename them first.

**gap warning: missing [3]**
You have e.g. 1.mp4, 2.mp4, 4.mp4 with no 3.mp4. The tool continues with what it finds (and you can just not select the missing number anyway). Ignore the warning if intentional.

**Encoder picks libx264 even though I have a GPU**
The test encode failed, the tool now prints the exact ffmpeg error on screen when this happens, so read that first. To reproduce manually:

```
ffmpeg -hide_banner -f lavfi -i color=c=black:s=640x360:d=1:r=30 \
       -vf format=yuv420p -frames:v 1 -c:v h264_nvenc -f null -
```

Replace h264_nvenc with whichever encoder you expected (h264_qsv, h264_amf, h264_vaapi).

Common causes:
- GPU drivers not installed or out of date.
- Your ffmpeg build doesn't include the encoder (verify with `ffmpeg -encoders | grep <name>`).
- On Linux: user not in the video and render groups (`sudo usermod -aG video,render $USER`, then relogin).

If you're sure the GPU works, answer `y` at the "Use it anyway?" prompt, or force it with `CLIPCTL_ENCODER=h264_nvenc`.

**Something failed, where are the diagnostics?**
Every failed ffmpeg command is appended to `clipctl_output/errors.log` with a timestamp, the exact command line (copy paste it to rerun manually), and the captured stderr where available. That's the file to attach when opening an issue.

**Converted file shows weird codecs / won't play**
Shouldn't happen anymore, the converter refuses to stream copy codec combos players can't handle (the mp4v/ipcm-in-mp4 class of garbage) and re encodes instead. If you still hit one, open an issue with the source file's ffprobe output.

**Non monotonic DTS during concat**
Usually a harmless warning, the output still plays. If playback actually breaks, open an issue with the source file's ffprobe output.

**Converting to webm is slow**
That's VP9 on CPU. It's the only option, webm doesn't allow h264, so there's no hardware fast path. Use mkv if you just want a different container without the pain.

**Encode is slow on Windows ARM**
Windows arm64 has no useful hardware encoder available, so it falls back to libx264. That's expected.

---

## Tests (only if you are schizo and don't trust me that I tested it before).

Time parsing, remux compatibility matrix, codec maps, filename collision handling, encoder list parsing has a stdlib only test suite.

```bash
python3 -m unittest test_clipctl -v     # Linux
python -m unittest test_clipctl -v      # Windows
```


## License

Do whatever you want, no warranty.
