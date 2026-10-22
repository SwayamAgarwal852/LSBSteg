# LSBSteg

A small Windows desktop app that hides a text message inside an **image** or a **video**
using **Least Significant Bit (LSB)** steganography, and reads it back.
University project for *Multimedia & Data Security*. The design and every decision are
in `PLAN.md`.

**What it is:** a tool for *covert* communication. The message is hidden, so a person
looking at the picture or watching the video does not notice it.

**What it is not:** it does **not** encrypt anything and it is **not "secure"**. Anyone
who has this tool, or knows the format below, can read the message. The message
starts with a fixed signature (`LSBS`), so the format is easy to recognise for anyone
who knows it. If the message itself must stay secret, encrypt it before hiding it.

## Features

- Hide UTF-8 text (English, Hindi, emoji, ...) in a **PNG, JPEG or BMP** cover image.
  The result is always a **PNG**.
- Hide text in a **video**. The result is a lossless **FFV1 video in an MKV file**; the
  original audio is copied unchanged.
- Read the message back, or get a clear reason why there is none ("No hidden message",
  "Data corrupted", ...).
- A 13-byte header with the message length and a CRC32 checksum detects damaged data.
- Tkinter GUI: capacity shown before encoding, warnings, cover/stego previews, progress
  bar, the window stays responsive during long jobs (work runs in a background thread).
- `results.py` measures MSE, PSNR, timings and file sizes and draws figures.

## Requirements

- Windows (developed and tested on Windows 11).
- **Python 3.12 or newer.** Only **3.13.2** has been tested.
- **FFmpeg** (ffmpeg and ffprobe) for video. Tested with FFmpeg 9.0.2 (gyan.dev full build).
  Images work without FFmpeg.
- Python packages: exact versions in `requirements.txt` (numpy, Pillow, matplotlib, pytest
  and their dependencies).

## Installation (Windows)

### 1. Python 3.12 or newer

Python **3.12+** is required (only **3.13.2** has been tested). Older versions cannot
install `requirements.txt`: the pinned numpy 2.5.4 and contourpy 1.4.0 need Python ≥ 3.12.

Check your version:

```powershell
python --version
```

Make sure Tkinter is included (it is by default in the python.org installer):

```powershell
python -c "import tkinter; print(tkinter.TkVersion)"
```

### 2. FFmpeg (needed for video)

```powershell
winget install --id Gyan.FFmpeg -e
```

**After installing FFmpeg, close and reopen your terminal** (and VS Code / any IDE you
run it from). winget adds FFmpeg to `PATH`, but terminals that were already open do not
see the change. Then check:

```powershell
ffmpeg -version
ffprobe -version
```

If you get "not recognized", the terminal has not picked up the new `PATH` yet; restart it
(or sign out and back in).

### 3. Virtual environment and packages

From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. You can also skip activation and
call `.\.venv\Scripts\python.exe` directly.

`requirements.txt` contains the exact versions tested on Python 3.13.2.

### 4. Check the setup

```powershell
.\.venv\Scripts\python.exe -c "import numpy, PIL, matplotlib, pytest, tkinter; print('OK')"
```

## Running the app

From the project folder:

```powershell
.\.venv\Scripts\python.exe app.py
```

(or `python app.py` if the virtual environment is activated).

## Using the GUI

**Hide a message (encode)**

1. Choose **Image** or **Video** mode at the top.
2. Click **Browse cover...** and pick the cover file. The app shows the capacity
   ("Capacity: up to N bytes ..."), notes/warnings in orange, and a preview of the cover
   (the first frame for a video). If **Output file** is empty, it is filled in as
   `<cover name>_stego.png` or `<cover name>_stego.mkv` next to the cover.
3. Type the message, or click **Load .txt...** to load a UTF-8 text file. The line under
   the box shows the size in characters and UTF-8 bytes and the percentage of capacity
   ("TOO LONG" if it does not fit).
4. Optionally click **Choose output...** to save somewhere else.
5. Click **Encode (hide message)**. While it works, the buttons are greyed out and the
   progress bar moves. When it is done, a "Done" box appears, the stego preview is shown,
   and **File to decode** is filled in with the new file.

**Read a message (decode)**

1. Choose the same mode (Image or Video) as the file.
2. Click **Browse...** next to **File to decode** (not needed right after encoding).
3. Click **Decode (reveal message)**. The message appears in **Result**.
4. **Copy result** copies the full text; **Save result...** saves it as a UTF-8 `.txt`.

Every problem (empty message, message too long, wrong file type, no hidden message,
damaged data, FFmpeg missing, ...) is shown as a message box, never as a crash.
Very long messages with very long lines are only previewed in the window (Tk freezes on
huge single lines); Copy/Save always use the full, exact text.

A full manual test list is in `GUI_CHECKLIST.md`.

## How it works (in simple words)

Every pixel of a colour image is three numbers (Red, Green, Blue), each 0–255, stored as
8 bits. The **last bit** (the least significant bit) changes the value by only 1, for
example 200 → 201, a change far too small to notice by eye (our difference figures have
to multiply it by 255 to make it visible at all).

1. The message is turned into bytes with UTF-8, and the bytes into bits (most significant
   bit first).
2. A 13-byte **header** is put in front of the message (table below).
3. The bits are written, one by one, into the last bit of the R, G, B values of the
   pixels: row by row, pixel by pixel, R then G then B. Each value changes by at most 1.
   Alpha (transparency) is never touched. Grayscale images use their single grey value.
4. The result is saved **losslessly** (PNG, or FFV1 for video), so every bit survives.

Decoding reads the last bits back in the same order: first the 104 header bits, then
exactly as many message bits as the header says, and checks the CRC32.

**Video** uses the same method: the video is treated as a sequence of RGB frames. The
bits fill frame 1, then frame 2, and so on. FFmpeg decodes the cover into raw RGB frames,
Python changes the bits, and FFmpeg writes the frames into a lossless FFV1 MKV. Frames are
streamed one at a time, so the whole video is never in memory, and decoding stops as soon
as the message has been read.

Palette images (GIF-style PNGs) are converted to true colour first, because changing the
last bit of a palette *index* can select a completely different colour.

## Header layout (version 1)

| Offset | Size | Field | Meaning |
|---|---|---|---|
| 0 | 4 bytes | Magic `LSBS` | Not there → "No hidden message" |
| 4 | 1 byte | Version `1` | Other value → "made by a different version" |
| 5 | 4 bytes | Message length (bytes, big-endian) | Must be > 0 and fit in the cover |
| 9 | 4 bytes | CRC32 of the message (big-endian) | Mismatch → "Data corrupted" |
| 13 | N bytes | The message (UTF-8) | Invalid UTF-8 → "Data corrupted" |

Header = 13 bytes = 104 bits. There is no end-of-message marker: the length field says
where the message ends.

## Capacity

One bit is hidden per R, G, B value (per grey value for grayscale images):

```
capacity_bits     = number of carrier bytes
                    (image: W × H × 3 for RGB/RGBA, W × H for grayscale;
                     video: frames × W × H × 3)
max_message_bytes = floor((capacity_bits − 104) / 8)
```

Worked example, a 100 × 100 RGB image:
100 × 100 × 3 = 30,000 bits; 30,000 − 104 = 29,896; 29,896 / 8 = 3,737 → **3,737 bytes**.

Video example, 320 × 240, 100 frames:
100 × 320 × 240 × 3 = 23,040,000 bits → (23,040,000 − 104) / 8 → **2,879,987 bytes**.

Capacity is in **bytes**, not characters: an English letter is 1 byte in UTF-8, a Hindi
letter 3 bytes, an emoji 4 bytes. A message that is too long is rejected before anything
is written ("Message too long").

## Supported formats

| | Input (cover) | Output (stego) |
|---|---|---|
| Image | PNG, JPEG, BMP. 8-bit only. RGB, RGBA, grayscale (L, LA) used directly; palette images are converted to RGB (RGBA if transparent), 1-bit and CMYK images to RGB. | Always PNG |
| Video | Any constant-frame-rate video FFmpeg can read. Tested as cover: MP4 (H.264, with and without AAC audio). Our own MKV output is what the decoder reads. The file dialog also offers .mkv, .mov, .avi, .webm, .m4v as covers (not tested). | Always MKV with FFV1 video (`bgr0`) and the original audio copied |

Rejected with a clear message: 16-bit PNGs, GIF and other image formats, variable frame
rate videos, files that are not images/videos.

## Running the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

There are 181 tests (bit engine, header, image and video pipelines, metrics, GUI logic,
a GUI smoke test and the negative demonstrations). A full run took 29–104 s on the
development laptop. Video tests are skipped if FFmpeg is not installed. Every test works in
its own temporary folder; nothing is written into the project folder.

## Regenerating the results (`results.py`)

`results.py` encodes and decodes random ASCII messages at 1, 10, 50 and 100 % of the
capacity of each cover and writes `metrics.csv` (MSE, PSNR, times, file sizes, exact
match) plus three figures per cover (side by side, difference × 255, histograms) into the
output folder. Every run needs a `--label`, so synthetic test output is never mistaken
for real results.

Synthetic covers (generated locally; `results/synthetic/` is not stored in git):

```powershell
mkdir -Force results\synthetic\covers
.\.venv\Scripts\python.exe -c "import numpy as np; from PIL import Image; r=np.random.default_rng(0); g=np.linspace(0,255,640)[None,:,None]*np.ones((480,1,3)); Image.fromarray(np.clip(g+r.integers(-20,21,g.shape),0,255).astype(np.uint8)).save('results/synthetic/covers/synthetic_gradient_640x480.png')"
ffmpeg -v error -y -f lavfi -i testsrc2=size=320x240:rate=25:duration=4 -c:v libx264 -pix_fmt yuv420p results\synthetic\covers\synthetic_testsrc2_320x240.mp4
.\.venv\Scripts\python.exe results.py --label synthetic --image results\synthetic\covers\synthetic_gradient_640x480.png --video results\synthetic\covers\synthetic_testsrc2_320x240.mp4 --out results\synthetic
```

With your own photos and videos:

```powershell
.\.venv\Scripts\python.exe results.py --label real --image photo.jpg --video clip.mp4
```

(default output folder: `results`).

## Measured results (our three real covers)

These numbers were **measured on our three covers** with `results.py --label real`; they
are not a general rule. Every one of the 12 runs decoded to exactly the original message.
PSNR is computed on the R, G, B values only (alpha is never changed and was checked to be
byte-identical).

| Cover | 1 % | 10 % | 50 % | 100 % of capacity |
|---|---|---|---|---|
| Macaw photo, JPEG 4016 × 6016 RGB (capacity 9,060,083 B) | 71.15 dB | 61.14 dB | 54.15 dB | 51.14 dB |
| Parchment scroll, PNG 2000 × 1232 RGBA (capacity 923,987 B) | 71.36 dB | 61.36 dB | 54.27 dB | 51.25 dB |
| Video clip, 640 × 360, 300 frames (capacity 25,919,987 B) — **pooled** PSNR (MSE over all frames) | 71.14 dB | 61.14 dB | 54.15 dB | 51.14 dB |
| same clip — **mean** PSNR over modified frames only | 60.85 dB | 52.39 dB | 51.42 dB | 51.14 dB |

Frames modified in the video: 4, 31, 151 and 300. The two video PSNRs differ at low payload
because the pooled value also counts the unchanged frames, while the mean only averages
the frames that carry message bits.

The difference figure of the scroll shows vertical stripes. We measured why: the test
message of `results.py` is printable ASCII, whose top bit is always 0, and a 2000-pixel
row holds 6000 bits (a multiple of 8), so that bit always lands in the same columns. Most
of the scroll's pixels are transparent with RGB 0 (last bit already 0), so at that bit
position only 25.1 % of the values changed instead of about 50 %. In the macaw photo, whose
last bits are close to random (50.1 % are 1), the same test message changed 50.0–50.1 % of
the values at every bit position, so there are no stripes. The stripes come from the test
message and the cover together, not from the method.

The figures are written to `results/real/`, which is git-ignored because they show our
own photos.

## Project files

```
app.py            Tkinter GUI (entry point: python app.py) - widgets only
gui_logic.py      everything the GUI needs without widgets: checks, messages, worker thread
encoder.py        encode_image(), encode_video()
decoder.py        decode_image(), decode_video()
bitutils.py       text <-> bytes <-> bits, write/read LSBs in a byte array
header.py         13-byte header, CRC32, capacity formula
image_utils.py    load images (mode handling, 16-bit check), save PNG
video_utils.py    ffprobe, FFmpeg frame reader and writer (pipes)
errors.py         one exception class per kind of error
metrics.py        MSE, PSNR, capacity, timing
results.py        experiment runner -> metrics.csv + figures
tests/            pytest test suites (181 tests)
pytest.ini        pytest settings
requirements.txt  exact package versions
PLAN.md           approved plan, assumptions, decisions, progress
GUI_CHECKLIST.md  manual GUI test list
VIVA_NOTES.md     plain-language notes and likely viva questions
LSB_Steganography.pptx  original presentation (kept unchanged)
```

## Limitations

Everything below was measured or verified in this project unless it says otherwise.

- **No encryption, not secure.** The message is only hidden. Anyone who knows the
  format can read it; the `LSBS` signature makes our files easy to recognise.
- **Text only.** The payload is UTF-8 text; files cannot be hidden.
- **JPEG destroys the message.** Re-saving a stego PNG as JPEG (quality 95, and even
  quality 100 with 4:4:4) → "No hidden message". Only 51–62 % of the hidden bits survived
  (on three test covers), close to the 50 % expected by pure chance.
- **Lossy video re-encoding destroys the message.** Re-encoding the stego MKV to H.264
  MP4 (`ffmpeg -i stego.mkv -c:v libx264 -c:a copy out.mp4`, also with `-pix_fmt yuv420p`,
  and even "lossless" `-crf 0 -pix_fmt yuv444p`) → "No hidden message". Social media and
  messaging apps that re-compress video would therefore destroy it too (we did not test
  any upload ourselves). **Exception:** `-c:v libx264rgb -crf 0` (truly lossless RGB H.264) kept the message.
- **Crop and resize.** Resizing (99 %, bicubic) or cropping even 1 pixel off the left or
  top edge destroys the message (the bit order shifts). Cropping the right or bottom edge
  keeps it **only** if the removed pixels held no message bits (bits are stored row by
  row from the top-left), e.g. a 52-byte message in a 320-pixel-wide image survived a
  1-pixel right crop, a 3,000-byte message did not.
- **When a lossy copy fails, which error appears is luck.** Usually the signature is gone
  ("No hidden message"); once (a flat grey image resized to 99 %) all 104 header bits
  survived by chance and the CRC32 check reported "Data corrupted" instead. Whenever
  message bits were lost, the decoder reported an error; it never returned wrong text.
- **Rotated (phone) videos.** FFmpeg by default *rotates* frames that carry a rotation
  tag, which scrambles the hidden bits (verified: the first 4 LSB bytes became
  `ff ff ff ff` instead of `LSBS`). The app reads and writes frames as stored
  (`-noautorotate`) and copies the rotation angle (e.g. 90°) into the MKV. A **flip** in
  the display matrix is **not** carried over (verified: a 90° + horizontal-flip input gave
  a 90°-only output). The message is still decoded correctly.
- **Variable frame rate videos are rejected** (detected when ffprobe's `r_frame_rate`
  differs from `avg_frame_rate`; this is a heuristic).
- **16-bit PNGs are rejected** ("16-bit PNGs are not supported"). Pillow silently reports
  16-bit RGB PNGs as 8-bit, so the app reads the PNG header itself to catch them.
- **Large output video.** FFV1 is lossless, so the MKV is much bigger than a normal MP4.
  On our real 10 s 640 × 360 clip (1,094,286 bytes, H.264) the stego MKV was
  45,959,159 bytes at 1 % of capacity (**42 ×**) and 79,513,865 bytes at 100 % (**72.7 ×**).
  On the synthetic 10 s 640 × 480 test clip it was only about **11 ×** (1,236,974 →
  13,497,659 bytes). What we measured: per frame, the real clip's MKV took 153,197 bytes at
  1 % against 53,991 bytes for the synthetic clip, although the real frames have fewer
  pixels (2.8 × more per frame); and filling the capacity with message bits added another
  33.6 MB. We did not study the FFV1 compression itself. The app warns for videos longer
  than 10 s or larger than 640 × 480.
- **Detectable by statistical analysis.** Plain LSB replacement is a well-known, easily
  detected method: statistical steganalysis (for example the chi-square attack or RS
  analysis) can reveal it, especially when a large part of the capacity is used.
  **We did not run a detection test ourselves.** What we *saw in our histograms*: LSB
  replacement evens out each pair of values 2k and 2k+1. In the macaw photo at 100 %,
  red value 232 went from 726,161 to 557,955 pixels and value 233 from 336,473 to
  504,679 (the pair's total, 1,062,634, stays the same). This pair-evening is the effect
  the chi-square attack looks for.
