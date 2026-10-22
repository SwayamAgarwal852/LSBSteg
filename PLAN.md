# PLAN — LSB-based Steganography System for Image and Video

**Status:** Approved by the team on 2026-10-20 (Phase 2).
**Team:** Swayam Agarwal (23BIT0216), Shriyans Pratihari (23BIT0219).
**Course:** Multimedia & Data Security — simple multimedia project.

---

## 1. Requirements (restated)

A **local** Tkinter desktop application for **covert communication** (not "secure" —
there is no encryption) that hides a UTF-8 text message inside a cover **image**
(output: PNG) or **video** (output: MKV with lossless FFV1, original audio copied
unchanged) using 1-bit Least Significant Bit (LSB) substitution in the R, G, B bytes.
The message is preceded by a **length + CRC32 header** (no end-of-message delimiter).
The decoder returns the exact message or a clear reason why it cannot.
The project also produces real metrics and figures for the slides. No PowerPoint file is
built or edited (decision 2026-10-22); slide fixes are listed in a plain-text
`SLIDE_CORRECTIONS.txt`, and the original `LSB_Steganography.pptx` stays untouched. Video support works by treating frames as images; it is the same algorithm.

### Working rules (summary)
- Phase gates: implement one subproblem at a time, run its tests, show real output,
  stop for the team's "continue".
- No invented numbers, APIs or results. Every number comes from a real run.
- Assumptions are marked and listed here.
- Git: commit locally on `main` after each approved subproblem. Never push,
  force-push or rewrite history without asking.

---

## 2. Environment (verified 2026-10-20)

| Item | Version |
|---|---|
| OS | Windows 11 Home Single Language 10.0.26200 |
| Python | 3.13.2 (`C:\Python313\python.exe`), project venv in `.venv` |
| FFmpeg / ffprobe | 9.0.2 full_build (gyan.dev), installed with `winget install --id Gyan.FFmpeg -e` |
| Packages | exact pins in `requirements.txt` (numpy 2.5.4, pillow 13.0.0, matplotlib 3.11.2, pytest 9.1.1 + dependencies) |

**Supported Python: 3.12 or newer.** Only 3.13.2 is tested. The pinned numpy 2.5.4 and
contourpy 1.4.0 declare `Requires-Python >=3.12`, so older Pythons cannot install
`requirements.txt`. The teammate will install Python 3.13.

---

## 3. Assumptions

- **A1:** Submission = live demo + slides (format/deadline/grading not yet known).
- **A2:** Bits are written MSB-first within each byte (NumPy `unpackbits` default `bitorder="big"`).
- **A3:** Internal pixel convention is RGB, shape H×W×C, uint8, row-major; flattening goes
  pixel by pixel, then R, G, B within a pixel. Pillow gives RGB; video frames are requested
  from FFmpeg as `rgb24`, so no BGR conversion is needed in our code.
- **A4:** Grayscale (`L`) covers stay grayscale: embed in the single grey channel
  (capacity W×H bits), save as `L` PNG. `LA` is handled like RGBA (embed in L, keep alpha).
- **A5:** Palette (`P`) images are converted to RGB (RGBA if the palette has transparency)
  before embedding, because changing the LSB of a palette *index* changes colours visibly.
  Output is a truecolour PNG and the GUI says so. Bilevel (`1`), CMYK and similar modes are
  also converted to RGB.
- **A6:** The decoder decides which channels to read from the stego PNG's own mode
  (L/LA → grey channel; RGB/RGBA → R, G, B). No side information needed.
- **A7 (confirmed):** Empty messages are rejected ("nothing to hide") in the engine and GUI.
- **A8:** For video, the cover frames are the frames FFmpeg decodes to `rgb24`. If the
  source is YUV (most MP4s), that conversion happens once at read time and is not part of
  the steganography. All frames are re-encoded to FFV1 (lossless); frames after the payload
  have unchanged pixels but the file is new.
- **A9:** A video is treated as variable frame rate (VFR) and rejected when ffprobe's
  `r_frame_rate` ≠ `avg_frame_rate` (heuristic). Verified in SP5: synthetic VFR clip → 25/1 vs 1075/91 (rejected); CFR 25 and 30000/1001 MP4s and our own FFV1 MKV outputs report equal rates (accepted).
- **A10:** GUI warning when video duration > 10 s or width×height > 640×480 (warning only).
- **A11:** Frame count comes from `ffprobe -count_frames` (exact; decodes the file),
  not the container's `nb_frames`.
- **A12:** FFmpeg is located with `shutil.which("ffmpeg")`; if missing, a friendly
  "FFmpeg missing" error is shown. No hardcoded install paths.
- **A13:** Timings use `time.perf_counter()` on the development laptop and are labelled so.
- **A14:** Test images/videos are generated locally (gradients, noise, ffmpeg `lavfi`
  test sources, palette and RGBA images). Nothing is downloaded. For Phase 4 the team will
  be asked for 2–3 of their own photos and a short video.

---

## 4. Design decisions

| # | Decision |
|---|---|
| D1 | Python 3.12+ (3.13.2 tested) in `.venv`. |
| D2 | Tkinter GUI, one window. Encode/decode logic never imports tkinter. |
| D3 | 1 LSB per R, G, B byte. Alpha never touched. No 2-LSB option. |
| D4 | Length header + CRC32, no delimiter (layout in §5). |
| D5 | Image output always PNG. JPEG/BMP accepted as cover (read only; note shown for JPEG). 16-bit PNGs rejected with a clear message. |
| D6 | Video I/O through FFmpeg pipes on both sides: read with `ffmpeg ... -f rawvideo -pix_fmt rgb24 -`, write raw rgb24 frames into `ffmpeg -f rawvideo ... -c:v ffv1`. In SP5 also test the OpenCV reader and report whether it is bit-exact. **If OpenCV is not needed, remove opencv-python from `requirements.txt` and tell the team.** **Outcome (SP5 Stage A):** OpenCV 5.0.0 read FFV1/bgr0 bit-exactly but is not needed (FFmpeg pipes do all video I/O), so opencv-python was removed with team approval. |
| D7 | FFV1 pixel format `bgr0` (`ffmpeg -h encoder=ffv1` lists `bgr0`/`bgra` as the only 8-bit RGB-family formats; 8-bit `gbrp` is not listed). Losslessness of rgb24 → bgr0 → rgb24 must be **proven** by the SP5 round-trip test. Fallback: `bgra`, then PNG frame sequence + audio (only with approval). **Outcome (SP5):** bgr0 proven bit-exact (random, 0/255 extremes, odd 161×121); ffmpeg auto-inserts a same-size rgb24↔bgr0 swscale step (csp gbr, range pc), which is lossless; bgra not needed. |
| D8 | Container MKV. Audio `-map 1:a? -c:a copy` from the original. Frame rate passed as the exact `r_frame_rate` fraction. |
| D9 | Rotation metadata: frames processed as stored; try to carry the tag with `-display_rotation` (not yet verified on FFmpeg 9.0.2). If it does not work, document that rotation tags are dropped. **Outcome (SP5):** works on FFmpeg 9.0.2 (`-noautorotate -display_rotation <deg>` on the pipe input → DisplayMatrix in MKV). Reader and writer MUST use `-noautorotate`: by default ffmpeg transposes rotated frames, which destroys the message. Only the rotation angle is carried; flips in a display matrix are not. |
| D10 | Video is streamed one frame at a time; never fully loaded in memory. Decoding stops once the payload is read. |
| D11 | Long work runs in a worker thread; progress/results go through `queue.Queue`, polled by the main thread with `root.after(...)`. Only the main thread touches widgets. |
| D12 | `requirements.txt` holds the exact pins tested on Python 3.13. No separate file for older Pythons. |
| D13 | `errors.py` with `CapacityError`, `NoHiddenMessageError`, `CorruptedDataError`, `UnsupportedFormatError`, `FFmpegNotFoundError`, `EmptyMessageError`, plus `FFmpegError` (ffmpeg failed mid-run; added in SP5) under a common base `StegoError`. The GUI maps each to a friendly message box. |
| D14 | Subprocesses use argument lists (no `shell=True`); paths via `pathlib`; images via Pillow (not `cv2.imread`, which fails on non-ASCII Windows paths). Spaces and non-ASCII paths must work. |

---

## 5. Header layout (version 1)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 B | Magic `b"LSBS"` | mismatch → "No hidden message found" |
| 4 | 1 B | Version `0x01` | unknown → "made by a different version" |
| 5 | 4 B | Payload length, uint32 big-endian | must be > 0 and ≤ capacity − 13 bytes |
| 9 | 4 B | CRC32 of payload, big-endian (`zlib.crc32`) | mismatch → "data corrupted or not produced by this tool" |
| 13 | N B | Payload (UTF-8 bytes) | invalid UTF-8 → treated as corrupted |

Header = 13 bytes = 104 bits.

**Capacity:**
`capacity_bits = usable_channel_bytes × 1`,
`max_payload_bytes = floor((capacity_bits − 104) / 8)`.
- Image: usable bytes = W×H×3 (RGB/RGBA) or W×H (L/LA).
- Video: usable bytes = frames×W×H×3.
- The GUI shows "up to N bytes (N ASCII characters; non-English characters use 2–4 bytes each)".
- Worked example: 100×100 RGB → 30000 bits → (30000 − 104) // 8 = 3737 bytes.

---

## 6. File structure

```
LSBSteg/
  bitutils.py      text<->bytes (UTF-8), bytes<->bits, embed/extract LSBs in a flat uint8 array
  header.py        build/parse the 13-byte header, CRC32, capacity maths
  errors.py        custom exception classes
  encoder.py       encode_image(), encode_video()
  decoder.py       decode_image(), decode_video()
  video_utils.py   ffprobe metadata, find ffmpeg, frame reader/writer pipes
  metrics.py       MSE, PSNR, capacity, timing helpers
  results.py       runs experiments -> results/metrics.csv + figures
  app.py           Tkinter GUI (entry point: python app.py)
  tests/           pytest suites + conftest.py (synthetic fixtures in temp dirs)
  results/         generated output (CSV, PNG figures)
  README.md, VIVA_NOTES.md, PLAN.md, requirements.txt, .gitignore
```

---

## 7. Subproblems and acceptance tests

### SP1 — Environment and setup
- Done: FFmpeg 9.0.2 via winget, `.venv`, packages, `requirements.txt` (exact pins).
- Remaining: `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`), README install
  section (Python 3.12+, winget FFmpeg, venv, "restart the terminal after installing FFmpeg").
- **Accept:** in a fresh terminal, `ffmpeg -version`, `ffprobe -version` and all venv
  imports succeed.

### SP2 — Bit engine (`bitutils.py`)
- str ↔ bytes ↔ uint8 bit array; `embed_bits(flat, bits, start=0)` returns a modified copy;
  `extract_bits(flat, n, start=0)`. Vectorised NumPy (`(flat & 0xFE) | bits`, `flat & 1`).
- **Accept:** round trips for ASCII, Hindi, emoji; embed→extract returns identical bits;
  every changed byte differs by at most 1; the input array is not mutated; too many bits →
  `CapacityError`.

### SP3 — Header and framing (`header.py`)
- **Accept:** build→parse round trip; wrong magic → `NoHiddenMessageError`; flipped payload
  bit → `CorruptedDataError`; declared length > capacity → error without reading garbage;
  length 0 → error; capacity formula matches hand-computed values (100×100 RGB → 3737 bytes).

### SP4 — Image pipeline
- Cover path + message + output path → PNG; stego path → message. Modes per A4–A6, D5.
- **Accept:** save→reload→exact match for RGB, L, RGBA (alpha byte-identical), palette, JPEG
  cover; one-byte message; exactly-at-capacity passes; one byte over → `CapacityError` with
  numbers; 1×1 image → clear capacity error; 4000×3000 image works (time reported); 16-bit
  PNG → `UnsupportedFormatError`; path with spaces and non-ASCII characters works; clean
  (never encoded) image → "no hidden message".

### SP5 — Video pipeline
- ffprobe → width, height, r/avg frame rate, exact frame count, audio, rotation.
  Reader pipe → modify frames until payload written → writer pipe (FFV1 bgr0) → mux
  original audio (copy).
- Risks: bgr0 not round-tripping, pipe deadlock on full stderr, timestamp drift,
  audio/MKV compatibility, runtime.
- **Accept:**
  1. Bit-exactness proof: random frames written then read back are `np.array_equal`.
  2. Round trip with a message spanning more than one frame (e.g. 160×120 testsrc, 20 KB message).
  3. Output frame count and frame rate equal the input.
  4. Audio present, same codec, identical packet hash vs original.
  5. Synthetic VFR clip rejected.
  6. Over-capacity rejected before anything is written.
  7. FFmpeg missing → `FFmpegNotFoundError` (simulated).
  8. OpenCV reader comparison reported → keep or remove opencv-python (D6).

### SP6 — Metrics (`metrics.py`, `results.py`)
- MSE, PSNR = 10·log10(255² / MSE) (MSE = 0 → "identical / ∞"), capacity, % used,
  embed/extract time, exact match; video per-frame PSNR on modified frames, frames
  modified, file sizes. Video reports (a) mean PSNR over modified frames and (b) PSNR of
  the MSE pooled over all frames, clearly labelled.
- `results/metrics.csv` + figures: side-by-side, difference ×255, histogram overlay.
- **Accept:** PSNR unit tests on hand-computed cases; CSV and PNGs produced by a real run.

### SP7 — Tkinter GUI (`app.py`)
- Image/Video mode, Browse cover, Load .txt (UTF-8), message box, choose output,
  Encode, Decode, read-only result box, capacity label, status bar, progress bar,
  side-by-side preview (first frame for video), large-video warning (A10),
  "re-encoding destroys the message" warning. All errors as message boxes; never a traceback.
- **Accept:** manual checklist followed by the team; automated tests of non-GUI handlers.
- **SP7 progress (2026-10-22):**
  - Done (commit 0a86fd3): `gui_logic.py` (validation, friendly messages, warnings, previews,
    jobs, Worker thread + queue), `app.py` (one window, `root.after` polling), 48 tests in
    `tests/test_gui_logic.py` + `tests/test_app_smoke.py` (170 total pass), `GUI_CHECKLIST.md`.
  - Verified 2026-10-22: real `python app.py` launch → window "LSB Steganography - Image and
    Video" appeared, closed by WM_CLOSE, stderr/stdout empty. Deliberate breakage caught by tests:
    (1) empty-message check disabled → `test_empty_message` fails; (2) buttons never re-enabled →
    2 smoke tests fail; (3) A10 `>` changed to `>=` → `test_video_notes[640-480-250-25/1]` fails.
    Restored; 170 pass.
  - Remaining: the team runs `GUI_CHECKLIST.md` by hand.

### SP8 — Testing and negative demonstrations
- All tests above, plus: stego PNG re-saved as JPEG → extract; stego MKV re-encoded to
  H.264 MP4 → extract. Report what actually happens.
- GUI manual test checklist.
- **SP8 progress (2026-10-22):**
  - Audit of SP2–SP7 acceptance items vs tests done; gaps closed: results CSV columns
    (times, sizes, PSNR vs MSE) now checked; cover video file checked unchanged.
  - Negative demos run for real and turned into `tests/test_negative.py` (11 tests):
    JPEG re-save (q95 and q100 4:4:4), 99% resize, 1 px crop left/top → message lost
    (only 47–72 of 104 header bits survived; in one flat-grey resize all 104 survived by
    luck and the CRC caught it). Crop right/bottom keeps the message while its pixels are
    untouched. H.264 re-encode (default, yuv420p, crf 0 yuv444p) → lost; libx264rgb crf 0
    (lossless RGB) → message kept.
  - Deliberate breakage: decoder swallowing errors (10 fail), column-major pixel order
    (2 fail), swapped CSV file sizes (1 fail), encoder touching the cover (1 fail). Restored.
  - Clean run (caches deleted): 181 passed, twice; no stray files or ffmpeg processes.
    Fresh clone + new venv + `pip install -r requirements.txt`: 181 passed.
  - Remaining: the team runs `GUI_CHECKLIST.md` by hand.

### SP9 — Documentation
- README (purpose, Python 3.12+, install incl. FFmpeg, run, usage, algorithm, header,
  formats, limitations) and `VIVA_NOTES.md` (one plain paragraph per subproblem).
  Docs checked against the code.
- **SP9 progress (2026-10-22):**
  - Done (commit 0202627): README.md (purpose/honest framing, features, requirements,
    install, run, GUI steps, algorithm, header, capacity, formats, tests, results.py recipe,
    file list, limitations) and VIVA_NOTES.md (SP1–SP8 paragraphs, 15 questions).
  - Checked: 58 UI strings/error texts/constants matched against the code; numbers taken
    from runs in this session; README commands run verbatim in a fresh clone (install,
    setup check, 181 tests, results recipe → 8 runs exact, app launch); FFmpeg hidden from
    PATH → 150 passed, 31 skipped. Rotation flip loss and autorotate scrambling re-verified
    by a real run. 10 wording mismatches found in the drafts and fixed.
  - Note: §6 above lists `tests/conftest.py`; it was never needed and does not exist
    (README lists the real files).
  - Remaining: the team runs `GUI_CHECKLIST.md` by hand.

### SP10 — Extras
- **Removed (team decision 2026-10-22):** the new deck `LSB_Steganography_v2.pptx`.
  No PowerPoint file is built or edited. Instead, `SLIDE_CORRECTIONS.txt` (plain text)
  lists slide by slide what to change (current wording → suggested wording) and the real
  numbers/figure paths for results and limitations slides. The original
  `LSB_Steganography.pptx` stays untouched.
- **Pending approval:** chi-square detectability demo.
- **Rejected:** encryption.

---

### Phase 4 progress (2026-10-22) — real covers
- Covers (team files, read-only, not in git): macaw JPEG 4016x6016 RGB; parchment scroll PNG
  2000x1232 RGBA (8-bit); phone-style MP4 1280x720 13.83 s 30/1 + AAC (over A10 limits) ->
  converted copy `clip_640.mp4` 640x360, 10 s, 300 frames, 30/1, AAC (made by us, original
  untouched; originals' SHA-256 unchanged).
- `results.py --label real` -> `results/real/` (git-ignored: figures show the team's photos).
  12 runs (1/10/50/100 %), all exact. PSNR: macaw 71.15/61.14/54.15/51.14 dB, scroll
  71.36/61.36/54.27/51.25 dB (R,G,B only; alpha byte-identical at all 4 sizes), video pooled
  71.14/61.14/54.15/51.14 dB. Video stego 45.96-79.51 MB vs 1.09 MB cover.
- Figures inspected: histograms show the pairs-of-values effect; vertical stripes in the scroll
  difference image come from the ASCII test message (top bit always 0) with 6000-bit rows.
- GUI code path (gui_logic + Worker) encode/decode exact for both images and the video; ffprobe:
  frames, rate, audio (identical packet hash) kept; no rotation tag in cover or stego.
- Waiting for the team: commit figures or keep them out of git; then Phase 5.

## 8. Risks

| Risk | Mitigation |
|---|---|
| FFV1/bgr0 not bit-exact | Proven first in SP5; fallback `bgra`, then PNG sequence (with approval) |
| PATH not refreshed → "FFmpeg missing" | Restart terminal; friendly error; README note |
| Only Python 3.13 tested | README states 3.12+ supported, 3.13 tested |
| Long/HD videos slow, large output | A10 warning; measured timings reported |
| opencv-python 5.0 is a new major version | Removed after the SP5 Stage A comparison (not needed) |
| Slides describe a delimiter | Listed in `SLIDE_CORRECTIONS.txt`; the team edits the slides |

---

## 9. Task order

SP1 finish → SP2 → SP3 → SP4 → SP5 (bit-exact proof first) → SP6 → SP7 → SP8 → SP9 →
Phase 4 (team's photos/video) → `results.py` run → `SLIDE_CORRECTIONS.txt` → final report.
Stop for "continue" after each step; commit locally on `main` after each approved step.
