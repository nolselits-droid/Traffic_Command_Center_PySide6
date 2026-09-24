# Traffic Command Center — PySide6 V0.5.03

Command Center untuk monitoring Traffic Light Controller ESP32-S3 V1.23.1, konfigurasi traffic transaksional, Event & Alarm, dan monitoring kamera RTSP.

V0.5.03 mengembangkan halaman **Traffic Configuration** menjadi editor terpadu untuk Plan, Stage, Schedule, dan Holiday. Seluruh perubahan berada dalam satu Draft controller, divalidasi firmware, kemudian dapat disimpan ke NVS atau disimpan sekaligus diminta melalui Safe Apply. Versi ini juga mengaktifkan Traffic Control serta Backup & Restore melalui API firmware V1.23.1.

## Fitur utama

- Maksimal lima controller melalui `GET /api/status`.
- Pilihan `MOCK DATA` atau `LIVE API`.
- Overview dan diagram persimpangan mengikuti data ESP32-S3 aktual.
- Jumlah kamera otomatis mengikuti `SG aktif + 1 PTZ`.
- Kamera controller terpilih saja yang aktif.
- Grid Live View memakai substream; double-click membuka main stream fullscreen.
- Retry stream otomatis setiap lima detik.
- Hikvision Standard dan Custom RTSP.
- Password kamera disimpan melalui Windows Credential Manager menggunakan `keyring`.
- Alarm komunikasi, HOLD/FLASHING/SAFETY, status safety, dan camera offline.
- Alarm aktif ditutup otomatis saat kondisi pulih dan pemulihan dicatat sebagai event baru.
- Acknowledge alarm, filter event, dan export CSV.
- Auto-reconnect bertahap saat controller offline.
- Traffic Configuration untuk Plan 1–24 dan Stage 1–24 per Plan.
- Editor state 12 Signal Group dengan nama SG dan penanda SG aktif.
- Seluruh 8 kelompok Schedule dan 24 slot per kelompok.
- Seluruh 32 slot Holiday.
- Lebar kolom SG seragam dan horizontal scroll untuk seluruh 12 SG.
- Satu sesi Draft Command Center pada satu controller dalam satu waktu.
- Draft yang dibuka dari dashboard atau client lain hanya dapat dilihat; Command Center tidak mengambil alih atau membatalkannya.
- Firmware menjadi validator final sebelum Save atau Safe Apply.
- Pilihan `SAVE TO NVS`, `SAVE & SAFE APPLY`, dan `APPLY SAVED`.
- Audit untuk pembukaan Draft, perubahan, validasi, Save, Apply, dan Cancel.
- Traffic Control `SKIP`, timed `HOLD`, dan `FLASHING` dengan konfirmasi operator serta guard Safety/Safe Apply.
- Backup configuration ke file JSON di PC.
- Validasi file sebelum Restore, preview source/checksum, serta pilihan Full Restore atau Traffic & Operational Settings.
- Tampilan `FLASH YELLOW 500/1000` berkedip pada Overview dan Live Intersection Diagram.
- Lebar kolom status API/OPEN pada Overview tetap ketika response time berubah.
- Live View menampilkan Config Revision, Runtime Revision, dan Apply State tanpa request API tambahan.
- Header menampilkan tanggal/jam berukuran besar dengan blok Operator Pusat yang stabil.

## Persyaratan Windows

1. Python 64-bit direkomendasikan.
2. Install VLC Media Player dengan arsitektur yang sama dengan Python.
3. Pastikan VLC dapat membuka RTSP kamera secara manual.

## Instalasi

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Jika aplikasi menampilkan `VLC TIDAK TERSEDIA`, periksa bahwa VLC sudah terpasang dan arsitekturnya sama dengan Python.

Status RTSP pada caption kamera:

```text
CONNECTING
OPENING / BUFFERING
LIVE
RETRY · ERROR
RETRY · TIMEOUT 12s
```

## Alarms & Events

Database dibuat otomatis pada saat aplikasi dijalankan:

```text
command_center_data/events.db
```

Event yang lebih lama dari 90 hari dibersihkan otomatis jika sudah tidak aktif. Alarm aktif tidak dihapus oleh proses retention. `Acknowledge` hanya menandai bahwa alarm sudah diketahui operator; tidak menyelesaikan alarm dan tidak mengubah operasi ESP32-S3.

## Menghubungkan controller

1. Buka **CONTROLLERS**.
2. Pilih `LIVE API · ESP32-S3`.
3. Aktifkan slot controller.
4. Masukkan IP atau Base URL ESP32-S3.
5. Tekan **SAVE & CONNECT**.

## Mengatur kamera

1. Buka **CAMERA CONFIGURATION**.
2. Pilih controller dan kamera.
3. Isi profile, status enable, alamat, port, username/password, serta path stream.
4. Tekan **TEST CONNECTION** untuk substream dan **PREVIEW** untuk main stream.
5. Tekan **SAVE CAMERA**.

Preset Hikvision:

```text
Main stream : /Streaming/Channels/101
Substream   : /Streaming/Channels/102
RTSP port   : 554
```

## Traffic Configuration

1. Hubungkan controller dalam mode `LIVE API` dan pastikan status ONLINE.
2. Buka **TRAFFIC CONFIGURATION**.
3. Tekan **EDIT CONFIGURATION** untuk membuka satu Draft pada controller.
4. Edit Plan/Stage, Schedule, dan Holiday sesuai kebutuhan.
5. Tekan **VALIDATE**. Save hanya aktif setelah firmware menyatakan Draft valid.
6. Pilih salah satu:
   - **SAVE TO NVS**: menyimpan konfigurasi tetapi tidak mengubah traffic runtime.
   - **SAVE & SAFE APPLY**: menyimpan lalu meminta pergantian runtime melalui Safe Apply.
   - **CANCEL DRAFT**: membuang seluruh perubahan Draft.
7. Jika konfigurasi sudah tersimpan tetapi belum aktif, gunakan **APPLY SAVED**.

Semua bagian merupakan satu transaksi. Cancel membuang perubahan Plan, Stage, Schedule, dan Holiday dalam Draft yang sama. Tombol pemilih controller dikunci selama Draft milik Command Center masih terbuka.

Jika controller sudah memiliki Draft dari dashboard/client lain, halaman menampilkan `SOURCE: DRAFT · EXTERNAL SESSION`. Data tetap dapat diperiksa, tetapi semua tombol perubahan dan Cancel dinonaktifkan.

Endpoint baca dan transaksi utama:

```text
GET  /api/editor/status
GET  /api/editor/system
GET  /api/editor/plans
GET  /api/editor/plan?plan=N
GET  /api/editor/schedule?day=N
GET  /api/editor/holidays
POST /api/editor/start
POST /api/editor/validate
POST /api/editor/cancel
POST /api/operator/save
POST /api/operator/save-apply
POST /api/runtime/apply
```

Mutasi Draft menggunakan endpoint firmware untuk stage count, stage, schedule, holiday, serta operasi clear. Command Center tidak menulis NVS secara langsung.

## Traffic Control

Pada **LIVE VIEW**, tombol SKIP, HOLD, dan FLASHING menggunakan endpoint firmware berikut:

```text
POST /api/control/skip
POST /api/control/hold?active=0|1
POST /api/control/flashing?active=0|1
```

Tombol hanya aktif sesuai status controller. Firmware tetap menjadi pengaman dan validator final untuk Minimum Green, Safety Override/Fault, input lokal, serta Safe Apply.

## Backup & Restore

Halaman **BACKUP & RESTORE** dapat menyimpan backup sebagai file JSON di PC. Sebelum Restore, file harus divalidasi oleh controller dan operator dapat memeriksa Source Controller, firmware, jumlah data, Active SG, conflict count, serta checksum.

- **Traffic & Operational Settings**: Plan, Stage, Schedule, Holiday, dan setting operasional.
- **Full Restore**: seluruh konfigurasi dan identitas controller.
- Network Setup tetap dipertahankan pada kedua mode.
- Restore hanya diaktifkan ketika controller ONLINE, Safety `OK`, dan Safe Apply `IDLE`.

## Penyimpanan lokal

```text
command_center_data/controllers.json
command_center_data/cameras.json
command_center_data/events.db
```

File `cameras.json` tidak menyimpan password. Password disimpan melalui Credential Manager pada sistem operasi.

## Batas keamanan

- Perubahan konfigurasi hanya tersedia pada `LIVE API`, controller ONLINE, dan Draft milik sesi Command Center.
- Firmware V1.23.1 tetap menjadi sumber data dan validator final.
- Save/Apply tidak tersedia sebelum Draft dimodifikasi dan lulus validasi firmware.
- Safe Apply hanya diminta ketika Safety `OK` dan proses Apply tidak sedang sibuk.
- Draft eksternal tidak diambil alih atau dibatalkan oleh Command Center.
- Jika aplikasi ditutup ketika memiliki Draft, operator mendapat peringatan; Draft tetap berada pada controller jika penutupan diteruskan.
- SKIP, HOLD, dan FLASHING mengikuti guard UI dan validasi final firmware.
- Restore selalu membutuhkan validasi file serta konfirmasi operator.
- Controller tetap bekerja mandiri jika Command Center atau kamera terputus.
