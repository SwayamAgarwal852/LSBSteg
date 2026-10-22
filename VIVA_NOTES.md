# Viva notes

Plain-language notes for the viva. Numbers come from real runs on the development laptop
(Windows 11, Python 3.13.2, FFmpeg 9.0.2); see `PLAN.md` for the full design.

## What we did, step by step

**SP1 – Environment.** We installed Python 3.13 and FFmpeg 9.0.2 (with winget), made a
virtual environment and pinned every package version in `requirements.txt`, so anyone can
install exactly what we tested. The pinned numpy needs Python 3.12 or newer, so that is our
minimum. The README explains the setup, including "restart the terminal after installing
FFmpeg", because an already open terminal does not see the new PATH.

**SP2 – Bit engine.** `bitutils.py` turns text into UTF-8 bytes and bytes into bits (most
significant bit first). It writes bits into the last bit of each byte with
`(byte & 0xFE) | bit` and reads them back with `byte & 1`. Tests show that English, Hindi
and emoji round-trip exactly, that no byte changes by more than 1, that 0 and 255 do not
overflow, and that the original array is never modified.

**SP3 – Header.** Before the message we write a 13-byte header: the signature `LSBS`, a
version number, the message length and a CRC32 checksum. The length tells the decoder
where the message ends, and the CRC tells it whether the data is damaged. If the length
is impossible for the cover, the decoder stops after reading only the 104 header bits.
We tested 1,000 never-encoded random covers: none returned text.

**SP4 – Images.** Images are loaded with Pillow and turned into RGB, RGBA, grayscale or
grayscale+alpha. We hide bits only in R, G, B (or grey), never in alpha. Palette images
are converted to true colour first. The output is always PNG, because PNG is lossless. We
found that Pillow reports 16-bit RGB PNGs as normal 8-bit images, so we read the PNG
header ourselves to reject them. A 4000×3000 image with a 1,020,000-byte message took
4.68 s to encode and 0.71 s to decode (one run, including PNG saving and loading).

**SP5 – Video.** A video is just many images. FFmpeg decodes the cover into raw RGB frames
through a pipe; Python hides the bits frame after frame; a second FFmpeg pipe writes the
frames into a lossless FFV1 video in an MKV file and copies the original audio. We first
proved that FFV1 with `bgr0` gives back exactly the same pixels, including random frames,
all-black and all-white frames and an odd size (161×121). Two surprises: FFmpeg
automatically rotates phone videos that have a rotation tag, which scrambles the bits, so
we read and write with `-noautorotate` and copy the rotation tag ourselves; and videos
with a variable frame rate are rejected. A 10 s 640×480 clip with a 1,000,008-byte message
took 1.13 s to encode and 1.31 s to decode (one run).

**SP6 – Metrics.** `metrics.py` computes MSE and PSNR; `results.py` runs experiments at
1, 10, 50 and 100 % of capacity and writes `metrics.csv` and figures (side by side,
difference ×255, histograms). On our three real covers (a macaw photo, a transparent
parchment PNG and a 10 s video clip) PSNR was about 71 dB at 1 % and 51.1–51.3 dB at
100 %, and all 12 messages came back exactly; these numbers are measured on our covers,
not a general rule. For video we report both the mean PSNR of the changed frames and the
pooled PSNR over all frames, clearly labelled. The scroll's difference figure showed
stripes; we measured that they come from our ASCII test message (its top bit is always 0)
meeting the scroll's transparent pixels (RGB 0), not from the method.

**SP7 – GUI.** A Tkinter window with Image/Video mode, cover and output selection, a
message box, capacity and size labels, warnings, previews, a progress bar and a status
bar. All checks and texts are in `gui_logic.py`, which has no widgets and is unit-tested.
Long jobs run in a background thread so the window does not freeze, and every error is a
friendly message box, never a traceback. We also found that Tk freezes on a single line of
1,000,000 characters, so such text is only previewed and Copy/Save use the full text.

**SP8 – Testing and negative demonstrations.** We checked every acceptance item against a
test (181 tests in total), closed two small gaps, and ran the suite twice from a clean
state and once in a fresh clone with a new virtual environment: all passed. We then
damaged stego files on purpose: JPEG re-saving, H.264 re-encoding, resizing and cropping
from the left or top all destroyed the message, and the decoder reported an error instead
of wrong text. Cropping the right or bottom edge only hurt when it removed pixels that held
message bits, and truly lossless RGB H.264 (`libx264rgb -crf 0`) kept the message.

## Likely viva questions

**1. Why LSB?**
It is the simplest hiding method: changing the last bit changes a value by at most 1
(out of 255), far too small to notice by eye, and it holds a lot of data (1 bit per colour value).
It also suits a short student project: easy to explain and to test exactly.

**2. Why a length header instead of an end-of-message delimiter?**
A delimiter (a special text like `###`) could also appear inside the message, and the
decoder would have to scan until it finds it. Our header stores the exact length, so the
decoder reads exactly the right number of bits, and the CRC32 tells us whether they are
correct. The signature `LSBS` lets us say "no hidden message" instead of printing garbage.

**3. Why PNG and not JPEG for the output?**
JPEG is lossy: it changes pixel values when saving, and that destroys the last bits. We
tested it: a stego PNG re-saved as JPEG at quality 95 (and even quality 100) gave "No hidden
message". PNG is lossless, so every bit is kept. A JPEG can still be used as a *cover*; the
result is saved as PNG.

**4. Why FFV1 in MKV for video?**
Normal video codecs (H.264 in MP4) are lossy, like JPEG. FFV1 is a lossless codec; we
proved that our frames come back bit-exact. MKV is a container that holds FFV1 and lets us
copy the original audio unchanged. The cost is size: for our real 10 s 640×360 clip the MKV
was 42 times larger than the H.264 cover at 1 % of capacity (45,959,159 vs 1,094,286 bytes)
and 72.7 times larger at 100 % (79,513,865 bytes); for a synthetic test clip it was about
11 times. Measured per frame, the real clip's MKV was 2.8 times bigger than the synthetic
one's (153,197 vs 53,991 bytes), and the file grew as more last bits were changed
(45.96 MB at 1 % → 79.51 MB at 100 %). We did not study the FFV1 compression itself.

**5. What does PSNR mean?**
Peak Signal-to-Noise Ratio compares the cover and the stego image:
MSE = average of (cover − stego)², PSNR = 10·log10(255² / MSE) in decibels. Higher means
more similar; identical images have MSE 0 and infinite PSNR. We did not run any test
with people looking at the images; PSNR is only a numerical measure.

**6. Why is PSNR about 51 dB at full capacity?**
At 100 % every last bit is overwritten by a message bit. For random-looking data about half
of the bits already have the right value, so about half of the values change by 1. Then
MSE ≈ 0.5 and PSNR = 10·log10(65025 / 0.5) ≈ 51.14 dB. Measured on our three real covers
at 100 %: 51.14 dB (macaw), 51.25 dB (scroll), 51.14 dB (video, pooled); and 51.1393 dB on
10 million random bytes. With less data, fewer values change and PSNR is higher (71.14–71.36
dB at 1 % on our covers). These are measurements on our covers, not a general rule: a cover
whose last bits are not random (like the scroll's black transparent area) gives a slightly
different value.

**7. What is the capacity?**
One bit per R, G, B value: max message bytes = (W × H × 3 − 104) / 8, rounded down
(104 = header bits). A 100×100 RGB image holds 3,737 bytes; our 640×480 image holds
115,187 bytes; our 4-second 320×240 video (100 frames) holds 2,879,987 bytes. Capacity is
in bytes: a Hindi letter takes 3 bytes and an emoji 4.

**8. What happens if the message is too long?**
The app checks before writing anything and shows "Message too long" with both numbers,
for example "138 bytes but this cover holds at most 137 bytes". The GUI already shows
"TOO LONG" while typing. For video, ffmpeg is not even started (tested).

**9. Can it be detected?**
Not by eye. But plain LSB replacement is a well-known method, and statistical
steganalysis (for example the chi-square attack or RS analysis) is known to detect it,
especially at high capacity. **We did not run a detection test ourselves.** But we saw the
effect these attacks use in our own histograms: LSB replacement evens out each pair of
values 2k and 2k+1. In the macaw photo at 100 %, red value 232 dropped from 726,161 to
557,955 pixels and value 233 rose from 336,473 to 504,679, while the pair's total stayed
1,062,634. Also, anyone who knows our format can simply look for the `LSBS` signature.

**10. Is it secure?**
No. It is hiding, not encryption. Anyone with this tool can read the message. For secrecy
the message should be encrypted before hiding; we did not add encryption (it was out of
scope).

**11. What if the stego video is re-encoded or uploaded?**
The message is lost. We tested H.264 re-encoding with ffmpeg's defaults, with `yuv420p`
(what phones and websites produce) and even "lossless" `-crf 0` in YUV: all gave "No hidden
message". Social media and messaging apps re-compress video, so the message would not
survive (we did not upload anything; this follows from the re-encoding test). Only truly
lossless RGB H.264 (`libx264rgb -crf 0`) kept the message.

**12. Why did autorotate matter?**
Phone videos are often stored sideways with a "rotate 90°" tag. By default FFmpeg rotates
the frames when decoding, so the pixels arrive in a different order and the hidden bits
are scrambled: we verified that the first four hidden bytes became `ff ff ff ff` instead of
`LSBS`. We use `-noautorotate` when reading and writing, so frames are processed exactly as
stored, and we copy the rotation angle into the output file (checked with ffprobe; we did
not check every video player). A flip in the tag is not copied (verified).

**13. How are threads used in the GUI?**
Encoding a video can take seconds, and if it ran in the GUI thread the window would freeze.
So the work runs in a background thread (`Worker` in `gui_logic.py`). Tkinter is not
thread-safe, so the worker never touches widgets: it puts its result or its error into a
`queue.Queue`. The main thread checks the queue every 100 ms with `root.after` and updates
the window. Buttons are disabled while a job runs, and closing the window during a job is
refused so no FFmpeg process or half-written file is left behind.

**14. How do you know the decoded message is correct?**
The CRC32 checksum in the header. If even one bit of the message changes, the CRC no longer
matches and the app says "Data corrupted" (tested by flipping a single bit). In all our
damage tests the decoder reported an error and never returned wrong text.

**15. How did you prove FFV1 is really lossless?**
We wrote random frames, plus all-black and all-white frames, into an FFV1 MKV, read them
back with an independent FFmpeg call and compared them with `np.array_equal`: identical,
also for an odd frame size (161×121). This is an automated test, so it is checked on every
test run.
