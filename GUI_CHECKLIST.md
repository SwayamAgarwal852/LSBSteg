# GUI manual test checklist (SP7)

Follow the steps in order and tick each box. Each step lists the **expected
result**. If something differs, write down what you saw.

Start the app from the project folder:

```powershell
.\.venv\Scripts\python.exe app.py
```

The console window must stay **empty** during all tests (no tracebacks, no
warnings), including the error tests.

---

## 0. Prepare test files (once)

Run these in PowerShell from the project folder. They create everything in a
new folder `gui_test` (delete it afterwards).

```powershell
mkdir gui_test; cd gui_test
$py = "..\.venv\Scripts\python.exe"
# images
& $py -c "import numpy as np; from PIL import Image; r=np.random.default_rng(1); Image.fromarray(r.integers(0,256,(300,400,3),dtype=np.uint8)).save('cover.png'); Image.open('cover.png').save('cover.jpg', quality=90); Image.open('cover.png').convert('P').save('palette.png'); Image.fromarray(r.integers(0,256,(20,20,3),dtype=np.uint8)).save('tiny.png')"
ffmpeg -v error -f lavfi -i testsrc=size=64x48 -frames:v 1 -pix_fmt rgb48be deep16.png
# text files
& $py -c "open('hindi.txt','w',encoding='utf-8').write('नमस्ते दुनिया 😀\nSecond line')"
& $py -c "open('ansi.txt','wb').write('café'.encode('cp1252'))"
& $py -c "open('huge.txt','w',encoding='utf-8').write('x'*1000000)"
# videos
ffmpeg -v error -f lavfi -i testsrc2=size=320x240:rate=25:duration=4 -f lavfi -i sine=frequency=440:duration=4 -c:v libx264 -pix_fmt yuv420p -c:a aac clip.mp4
ffmpeg -v error -f lavfi -i testsrc2=size=1280x720:rate=25:duration=12 -c:v libx264 -pix_fmt yuv420p big.mp4
ffmpeg -v error -f lavfi -i testsrc=size=160x120:rate=25:duration=4 -vf "select='lt(n\,25)+not(mod(n\,4))'" -fps_mode vfr -c:v libx264 -pix_fmt yuv420p vfr.mp4
cd ..
```

- [ ] All files exist in `gui_test`: cover.png, cover.jpg, palette.png, tiny.png, deep16.png, hindi.txt, ansi.txt, huge.txt, clip.mp4, big.mp4, vfr.mp4.

---

## 1. Window

- [ ] 1.1 The window opens with the title "LSB Steganography - Image and Video". Mode = **Image**.
- [ ] 1.2 Capacity says "Capacity: choose a cover file". Both previews say "(no preview)". The progress bar is empty.

## 2. Image: encode and decode

- [ ] 2.1 **Browse cover...** → `cover.png`. Expected: capacity "up to 44,987 bytes (44,987 English characters; non-English characters use 2-4 bytes each)"; orange note "Output is a PNG file. Do not re-save, edit or convert it to JPEG..."; Cover preview shows the noise image; Output file is filled with `...\gui_test\cover_stego.png`.
- [ ] 2.2 Type `Hello` in Message. Expected: "Message: 5 characters = 5 bytes (UTF-8), 0.0% of capacity".
- [ ] 2.3 **Clear message**, then **Load .txt...** → `hindi.txt`. Expected: the Hindi text and emoji appear; the size line shows more bytes than characters.
- [ ] 2.4 **Encode**. Expected: while working, all buttons are greyed out and the bar moves; then a "Done" box with the output path; Stego preview appears; "File to decode" is filled with `cover_stego.png`; status "Message hidden in cover_stego.png (... ms)".
- [ ] 2.5 **Decode**. Expected: the Result box shows exactly the Hindi text, emoji and both lines; status "Found a hidden message of ... characters".
- [ ] 2.6 **Copy result**, paste into Notepad. Expected: identical text.
- [ ] 2.7 **Save result...** → `result.txt`. Open it in Notepad. Expected: identical text.
- [ ] 2.8 Cover = `cover.jpg`. Expected: an extra note "The cover is a JPEG: it is only read; the result is saved as PNG." Encode `JPEG test`, then Decode. Expected: `JPEG test`.
- [ ] 2.9 Cover = `palette.png`. Expected: note "Palette image: it will be converted to true colour (RGB/RGBA) first." Encode and Decode work.

## 3. Image: error messages (a box must appear; no crash, empty console)

- [ ] 3.1 Restart the app. Click **Encode** at once. Expected: "Check your input - Please choose a cover file first."
- [ ] 3.2 Cover = `cover.png`, empty message, **Encode**. Expected: "Check your input - The message is empty - there is nothing to hide."
- [ ] 3.3 Type `hi`, delete the Output file text, **Encode**. Expected: "Please choose where to save the output file."
- [ ] 3.4 Output = `...\gui_test\out.jpg`, **Encode**. Expected: "The output file must end in .png (lossless PNG)."
- [ ] 3.5 Output = the cover path itself (`...\gui_test\cover.png`), **Encode**. Expected: "The output file must be different from the cover file."
- [ ] 3.6 Cover = `tiny.png` (capacity 137 bytes). Load `hindi.txt` and add text until the size line says "TOO LONG", then **Encode**. Expected: "Message too long - Message is ... bytes but this cover holds at most 137 bytes ...".
- [ ] 3.7 Restart the app. Click **Decode** with no file. Expected: "Please choose the file to decode first."
- [ ] 3.8 File to decode = `cover.png` (never encoded). Expected: "No hidden message - No hidden message was found in this file...".
- [ ] 3.9 Cover = `deep16.png`. Expected: "Unsupported file - 16-bit PNGs are not supported. Please use an 8-bit image." The capacity line says "unknown".
- [ ] 3.10 **Load .txt...** → `ansi.txt`. Expected: "Not UTF-8 text - The text file is not UTF-8...".
- [ ] 3.11 In Image mode, Browse cover → `clip.mp4` (choose "All files"). Expected: "Image mode accepts PNG, JPEG or BMP files. For a video, switch to Video mode."
- [ ] 3.12 **Corrupted data:** encode `secret message` into `cover.png` → `cover_stego.png`, close the app, then run:
      `.\.venv\Scripts\python.exe -c "from PIL import Image; im=Image.open('gui_test/cover_stego.png'); px=im.load(); r,g,b=px[50,0]; px[50,0]=(r^1,g,b); im.save('gui_test/damaged.png')"`
      Start the app and decode `damaged.png`. Expected: "Data corrupted - Data corrupted or not produced by this tool (CRC mismatch)..."
- [ ] 3.13 After every error above, all buttons are clickable again.

## 4. Very long message

- [ ] 4.1 Cover = `cover.png`. **Load .txt...** → `huge.txt` (1,000,000 characters on one line). Expected: within a second, the message box shows "[Message loaded from huge.txt: 1,000,000 characters - too long to show here...]" and the size line shows "TOO LONG" (1,000,000 > 44,987).
- [ ] 4.2 Video mode, cover = `clip.mp4` (capacity is large). Load `huge.txt`, **Encode**, then **Decode**. Expected: an info box "Long message ... Showing only the first 5,000 characters..."; the window does not freeze; the result box shows 5,000 x's.
- [ ] 4.3 **Save result...** → `huge_result.txt`. Expected: the file is 1,000,000 bytes (check with right-click → Properties).
- [ ] 4.4 **Clear message**. Expected: the box is editable again and empty.

## 5. Video: encode and decode

- [ ] 5.1 Select **Video** mode. Expected: cover, output and previews are cleared.
- [ ] 5.2 Cover = `clip.mp4`. Expected: capacity "up to 2,879,987 bytes ..."; note "The output MKV (lossless) is much larger than the input. Converting it to MP4, uploading it to social media or sending it through messaging apps re-compresses it and destroys the hidden message."; NO "Large video" note; preview shows the first frame; Output = `clip_stego.mkv`.
- [ ] 5.3 Message `Video secret नमस्ते`, **Encode**. Expected: buttons greyed while working; "Done" box; Stego preview shows the first frame; status shows the time.
- [ ] 5.4 **Decode**. Expected: `Video secret नमस्ते` exactly.
- [ ] 5.5 Play `clip_stego.mkv` in VLC (or another player that supports FFV1). Expected: it looks the same as `clip.mp4` and the 440 Hz tone is still there. (The Windows "Media Player" may not play FFV1; that is a player limitation.)
- [ ] 5.6 Compare file sizes of `clip.mp4` and `clip_stego.mkv`. Expected: the MKV is much larger.
- [ ] 5.7 Cover = `big.mp4`. Expected: extra note "Large video (1280x720, 12.0 s): encoding may be slow...". Encode `x` and check that the window stays responsive (you can move it) while working.
- [ ] 5.8 While 5.7 is encoding, try to close the window. Expected: "Please wait - A task is still running..." and the window stays open. After "Done", closing works.

## 6. Video: error messages

- [ ] 6.1 Video mode, Output = `...\gui_test\out.mp4`, **Encode**. Expected: "The output file must end in .mkv (lossless FFV1 MKV)."
- [ ] 6.2 Video mode, cover = `cover.png` (choose "All files"). Expected: "This looks like an image. Switch to Image mode."
- [ ] 6.3 Cover = `vfr.mp4`, message `hi`, **Encode**. Expected: "Unsupported file - Variable frame rate video (r_frame_rate 25/1, average 1075/91) is not supported."
- [ ] 6.4 Decode `clip.mp4` (never encoded). Expected: "No hidden message".
- [ ] 6.5 **FFmpeg missing:** close the app, then in PowerShell:
      `$env:PATH = ($env:PATH -split ';' | Where-Object { $_ -notlike '*FFmpeg*' }) -join ';'; .\.venv\Scripts\python.exe app.py`
      Video mode, cover = `clip.mp4`. Expected: "FFmpeg missing - ffprobe was not found. Install FFmpeg (winget install --id Gyan.FFmpeg -e) and restart the terminal." Close the app and open a new terminal afterwards (this only changed PATH for that one terminal).
- [ ] 6.6 **Negative demo:** `ffmpeg -v error -i gui_test\clip_stego.mkv -c:v libx264 gui_test\reencoded.mp4`, then decode `reencoded.mp4`. Expected: "No hidden message" or "Data corrupted" (the re-encoding destroyed the LSBs).

## 7. Mode switch and closing

- [ ] 7.1 With a cover loaded, switch Image → Video → Image. Expected: cover, output, file to decode, capacity, notes and previews are cleared each time; the message text stays.
- [ ] 7.2 Close the window with the X button when idle. Expected: it closes at once and the console stays empty.

Not testable by hand (covered by automated tests): "Video processing failed"
(ffmpeg crashing in the middle) and "Nothing to hide" from the engine (the GUI
already stops an empty message in step 3.2).
