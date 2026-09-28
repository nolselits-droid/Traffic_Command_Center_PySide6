# Traffic Command Center — PySide6 V0.6.01 TEST1 FIX8

FIX8 merapikan **SIGNAL GROUP CONFIGURATION → Destination Road Arm**.
Label form sekarang sejajar dengan pilihan pertama, seluruh pilihan tujuan
disusun vertikal, dan urutannya dihitung berdasarkan arah kendaraan:
`Straight`, `Left`, kemudian `Right`. Setiap pilihan memakai format ringkas
seperti `Arm 3 – South (Straight)` tanpa menampilkan sudut derajat.

FIX7 memperbaiki sinkronisasi RTC agar nilai waktu diambil setelah operator
menekan YES, ditambah kompensasi setengah waktu respons dan pembulatan ke detik
terdekat. Camera Configuration sekarang mempunyai `RTSP cache / latency`
per kamera (200–3000 ms), dan perubahan hanya me-restart kamera yang disimpan.
Setelah Restore, Intersection Layout langsung dimuat ulang; perubahan
`layoutRevision` dari status controller juga memicu sinkronisasi tanpa menunggu
interval refresh 30 detik.

FIX6 memperbaiki sinkronisasi Intersection Layout saat startup. Live View tidak
lagi membentuk diagram dari placeholder `active_signal_groups = 0`, dan hasil
GET pertama maupun RELOAD manual selalu memicu redraw meskipun payload controller
sama dengan cache lokal. Operator tidak perlu lagi menekan SAVE hanya untuk
menyamakan Live View dengan dashboard ESP32-S3. Panel Intersection Layout juga
diubah menjadi 33:67; RELOAD dan RESET sejajar, sedangkan SAVE berada penuh di
baris bawah.

FIX5 menata field Intersection Diagram dan Signal Group Configuration dalam
satu baris label–nilai. NORTH, SOUTH, EAST, dan WEST dipindahkan ke luar kanvas
agar tidak bertumpuk dengan ARM. Refresh layout otomatis dijalankan secara
silent, tidak menonaktifkan tombol, dan layout yang revision serta isinya sama
tidak dirender ulang.

FIX4 menetapkan pembagian tab Intersection Layout menjadi 40:60 tanpa pembatas
yang dapat digeser, menghapus kedua kotak informasi, menghapus petunjuk drag di
dalam kanvas, dan mengunci isi scroll area agar tidak bergeser horizontal.
Setelah SAVE berhasil, layout yang dikirim langsung dimasukkan ke shared
repository sehingga Live View segera menggunakan layout yang sama, kemudian
GET controller tetap dijalankan sebagai verifikasi.

FIX3 memperbaiki dua masalah yang terlihat pada screenshot Full HD: panel kiri
tidak lagi dapat bergeser horizontal secara tersembunyi, dan Live Preview tidak
lagi berubah menjadi banner hijau yang terlalu lebar. Form pengaturan memakai
label di atas field, sedangkan preview menggunakan widget rasio persegi dengan
ukuran pilihan 460 × 484 px dan batas maksimum 520 × 544 px.

FIX2 merapikan tab **SYSTEM SETTINGS → INTERSECTION LAYOUT** secara horizontal
dan vertikal. Panel pengaturan dibuat lebih ramping, tombol tindakan disusun
vertikal, Signal Group Identification menggunakan satu kolom, dan minimum Live
Preview diturunkan agar seluruh diagram selalu muat tanpa horizontal clipping.

FIX1 merapikan tab **SYSTEM SETTINGS → INTERSECTION LAYOUT** untuk layar
minimum 1180×700 maupun layar Full HD. Panel pengaturan dan panel Live Preview
sekarang mempunyai scroll vertikal independen, ukuran minimum preview diturunkan
tanpa mengubah rasio diagram, dan tombol tindakan disusun dalam dua baris agar
tidak saling menimpa.

Command Center untuk monitoring Traffic Light Controller ESP32-S3 V1.24 TEST4, konfigurasi traffic transaksional, Event & Alarm, dan monitoring kamera RTSP.

V0.6.01 TEST1 menyinkronkan Intersection Layout dengan ESP32-S3 melalui `GET/POST /api/intersection/layout`. Controller menjadi sumber data utama, sedangkan PC menyimpan cache untuk tampilan offline. Editor memakai `layoutRevision` untuk mencegah penimpaan perubahan yang lebih baru. Signal Group Identification juga dipindahkan ke tab Intersection Layout agar susunan menu sama dengan dashboard ESP32-S3. Camera Layout tetap merupakan pengaturan lokal Command Center.

## Fitur utama

- Maksimal lima controller melalui `GET /api/status`.
- Koneksi controller hanya melalui `LIVE API · ESP32-S3`; tidak ada data simulasi atau fallback Mock.
- Overview dan diagram persimpangan mengikuti data ESP32-S3 aktual.
- Jumlah kamera Live View mengikuti kamera yang enabled dan dipilih untuk ditampilkan; PTZ/dome bersifat opsional.
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
- Header menampilkan jam lebih dahulu, kemudian tanggal (`HH:mm:ss  DD/MM/YYYY`).
- System Settings ditempatkan sebelum Users pada sidebar.
- Editor Controller ID/Name, Safe Apply All Red, Hold Duration, dan Minimum Green Before Skip.
- Editor Startup Yellow Flashing dan Startup All Red untuk startup berikutnya.
- Editor nama SG1–SG12 dengan penyimpanan metadata NVS.
- Sinkronisasi RTC dari PC atau input manual dengan peringatan dampak Schedule.
- Informasi interface, mode alamat, IP, subnet, gateway, dan DNS ditampilkan read-only.
- SKIP, HOLD, dan FLASHING dieksekusi langsung; proses/hasil ditampilkan non-modal di bawah tombol.
- Nilai Mode sampai Config/Runtime Revision memakai font lebih besar dan warna semantik.
- Sidebar global dapat hide/open melalui tombol `☰` atau `Ctrl+B`; kondisi terakhir disimpan lokal.
- Khusus Live View, panel kanan Intersection Diagram tetap; hanya grid Live Camera yang melebar/menyempit.
- Template Intersection Diagram: Four-Way, T-Junction, Straight Road, dan Single Approach.
- Rotation 0°/90°/180°/270° serta posisi SG1–SG12 yang dapat dipindahkan dengan drag.
- Rotasi lampu individual per SG: Auto, 0°, 90°, 180°, atau 270°.
- Movement memakai checkbox independen Straight, Left, dan Right sehingga seluruh kombinasinya dapat dipilih.
- Flow hanya berupa garis tipis dan ujung panah; tidak mewarnai atau memblok area jalan.
- Intersection dan Camera Layout memakai setting di kiri serta preview tetap terlihat di kanan.
- Two-Way menggambar movement masuk sesuai pilihan dan satu flow lurus keluar pada lajur kiri sebelahnya; rute Left/Right tidak dibalik menjadi flow tambahan.
- Arah aliran Inbound, Outbound, Two-Way, atau Hidden; warna garis mengikuti status SG dan flashing.
- Camera Auto Layout menyesuaikan jumlah kamera tanpa menyediakan slot kosong untuk PTZ yang tidak digunakan.
- Camera Custom Layout menggunakan grid stabil 4×4; kamera dapat dipindah dengan drag atau input row/column serta diatur width/height-nya.

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
2. Pastikan `Connection Source` menampilkan `LIVE API · ESP32-S3`.
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

Pada **LIVE VIEW**, tombol SKIP, HOLD, dan FLASHING langsung menggunakan endpoint firmware berikut tanpa dialog konfirmasi:

```text
POST /api/control/skip
POST /api/control/hold?active=0|1
POST /api/control/flashing?active=0|1
```

Selama request berlangsung ketiga tombol dinonaktifkan untuk mencegah double-click. Hasil accepted/rejected tampil di bawah tombol dan tetap masuk Audit Event. Firmware tetap menjadi pengaman dan validator final untuk Minimum Green, Safety Override/Fault, input lokal, serta Safe Apply.

## Collapsible Sidebar

Tombol `☰` pada header dan shortcut `Ctrl+B` menyembunyikan atau membuka sidebar pada seluruh halaman. Halaman aktif tidak berubah. Kondisi terakhir disimpan melalui local application settings; kondisi awal instalasi tetap OPEN.

## Backup & Restore

Halaman **BACKUP & RESTORE** dapat menyimpan backup sebagai file JSON di PC. Sebelum Restore, file harus divalidasi oleh controller dan operator dapat memeriksa Source Controller, firmware, jumlah data, Active SG, conflict count, serta checksum.

- **Traffic & Operational Settings**: Plan, Stage, Schedule, Holiday, dan setting operasional.
- **Full Restore**: seluruh konfigurasi dan identitas controller.
- Network Setup tetap dipertahankan pada kedua mode.
- Restore hanya diaktifkan ketika controller ONLINE, Safety `OK`, dan Safe Apply `IDLE`.

## System Settings

Halaman **SYSTEM SETTINGS** menggunakan beberapa transaksi terpisah agar kegagalan satu kelompok tidak membuat operator mengira seluruh data sudah tersimpan:

- **SAVE IDENTITY & OPERATIONAL**: Controller ID/Name, Safe Apply All Red, Hold Duration, dan Minimum Green Before Skip.
- **SAVE STARTUP PATTERN**: Yellow Flashing dan All Red yang berlaku pada startup berikutnya.
- **SAVE SG NAMES**: metadata nama SG1–SG12; tidak membutuhkan Safe Apply.
- **SYNC FROM PC / SET MANUAL RTC**: memperbarui DS3231 lalu firmware mengevaluasi ulang Schedule.

Semua tombol tulis dinonaktifkan saat controller offline, Safety tidak `OK`, Safe Apply tidak `IDLE`, Traffic Configuration Draft terbuka, atau RAM traffic masih dimodifikasi. Firmware tetap menjadi validator final. Network hanya ditampilkan; perubahan network wajib melalui portal Network Setup Mode GPIO38 aktif LOW.

Tab **INTERSECTION LAYOUT** dan **CAMERA LAYOUT** memiliki sumber penyimpanan berbeda:

- **Intersection Layout** dibaca dan disimpan pada ESP32-S3. Cache lokal hanya dipakai untuk tampilan ketika controller offline; penyimpanan dinonaktifkan saat offline.
- Menu Intersection Layout sama dengan ESP32-S3: **DIAGRAM / LAYOUT**, **ROAD ARM**, dan **SIGNAL GROUP CONFIGURATION**.
- Signal Group Identification SG1–SG12 berada di bawah Live Preview dan tetap disimpan melalui API System Settings controller.
- Posisi lampu dan posisi nama SG dapat diubah secara terpisah dengan drag langsung pada preview.
- Save memakai `expectedRevision`; HTTP 409 meminta operator memuat ulang layout sebelum mengedit kembali.
- Preview dan Live View menggunakan kanvas persegi serta transformasi koordinat yang sama agar posisi SG konsisten.
- **Camera Layout / AUTO** menyusun kamera berdasarkan jumlah kamera yang enabled dan visible. Kamera PTZ/overview otomatis diprioritaskan jika tersedia.
- **Camera Layout / CUSTOM** menggunakan grid 4×4. Penyimpanan ditolak jika dua kamera bertumpuk atau melewati batas grid.
- Menonaktifkan tampilan PTZ tidak meninggalkan ruang kosong; kamera SG mengisi area Live Camera.

## Penyimpanan lokal

```text
command_center_data/controllers.json
command_center_data/cameras.json
command_center_data/display_layouts.json  # Camera Layout + cache Intersection Layout
command_center_data/events.db
```

File `cameras.json` tidak menyimpan password. Password disimpan melalui Credential Manager pada sistem operasi.
Cache Intersection Layout tidak menjadi sumber konfigurasi ketika controller online; data controller selalu menggantikannya setelah sinkronisasi berhasil.

## Batas keamanan

- Perubahan konfigurasi hanya tersedia pada `LIVE API`, controller ONLINE, dan Draft milik sesi Command Center.
- Firmware V1.24 TEST4 tetap menjadi sumber data dan validator final.
- Save/Apply tidak tersedia sebelum Draft dimodifikasi dan lulus validasi firmware.
- Safe Apply hanya diminta ketika Safety `OK` dan proses Apply tidak sedang sibuk.
- Draft eksternal tidak diambil alih atau dibatalkan oleh Command Center.
- Jika aplikasi ditutup ketika memiliki Draft, operator mendapat peringatan; Draft tetap berada pada controller jika penutupan diteruskan.
- SKIP, HOLD, dan FLASHING mengikuti guard UI dan validasi final firmware.
- Restore selalu membutuhkan validasi file serta konfirmasi operator.
- System Settings tidak dapat ditulis ketika Traffic Configuration Draft/RAM changes atau Safe Apply masih aktif.
- Network tidak pernah diubah dari Command Center.
- Controller tetap bekerja mandiri jika Command Center atau kamera terputus.
