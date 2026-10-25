# Music Tag Studio
Windows desktop tag editor for MP3, FLAC, M4A, OGG, OPUS and WAV.

## Run
Install Python 3.10+ (with py launcher), then double-click `run.bat`.

Or:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Build exe
Double-click `build_exe.bat`. Result: `dist\MusicTagStudio.exe`.

## Usage
1. Select folder. Recursive scan finds supported music files.
2. Click a row, edit metadata manually or click 'แยกชื่อไฟล์ → Tags'.
3. Search MusicBrainz with an artist/song query; the top result fills fields and optionally fetches album art from Cover Art Archive.
4. Verify results, then save. Alternatively select a local image for cover art.
5. Multi-select rows to batch-set Artist/Album (only).

## Important limitations
- Search is text-based, NOT audio fingerprint identification. Results can be wrong, especially for ambiguous filenames; always verify.
- Online lookup requires internet and relies on third-party MusicBrainz / Cover Art Archive availability.
- Album artwork is saved to supported formats using Mutagen; compatibility depends on the specific file/container and player.
- Back up original music files before editing. This app writes directly to source files, with no undo.
- Batch operation updates only Artist/Album, not cover artwork or title.
- Scan and online lookup are background threads; saving and batch writes run in the UI thread and may pause briefly.

## Auto Match + Apply (v2)
1. เลือกโฟลเดอร์เพลง: ตารางแสดง Checkbox, ชื่อไฟล์, นักร้อง, ชื่อเพลง, อัลบั้ม, ตำแหน่ง และสถานะ
2. ติ๊กเพลงที่ต้องการ (ค่าเริ่มต้นเลือกทุกเพลง) แล้วกด **Auto Match ที่ติ๊ก** เพื่อค้นหา MusicBrainz โดยยังไม่เขียนไฟล์
3. ตรวจสอบข้อมูลที่ปรากฏในคอลัมน์ Artist/Title/Album และสถานะรายเพลง (รายการที่ไม่มั่นใจจะไม่ถูกเสนอให้ Apply)
4. กด **Apply ที่ติ๊ก** และยืนยัน เพื่อบันทึก metadata และฝังรูปปกเมื่อ Cover Art Archive มีภาพ

หมายเหตุ: Auto Match ต้องใช้อินเทอร์เน็ต; จำกัดความเร็วคำขอ MusicBrainz; ไม่ได้ระบุเพลงด้วยการฟังเสียง; ควรสำรองเพลงก่อนเขียนข้อมูล; หากไม่พบปกจะบันทึกเฉพาะ metadata. การเลือก release จากผลการค้นหาอาจไม่ตรงเวอร์ชันเพลงทุกครั้ง.
