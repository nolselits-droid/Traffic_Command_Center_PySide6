# Traffic Command Center — PySide6 V0.5.02

Command Center read-only untuk Traffic Light Controller ESP32-S3 V1.23.1 dengan monitoring RTSP camera.

V0.5.02 menambahkan tampilan **Traffic Configuration read-only** untuk membaca Plan, Stage, Schedule, Hari Libur, nama SG, revision, Apply State, dan Safety langsung dari firmware V1.23.1. Event & Alarm V0.5.01 serta perbaikan RTSP/layout kamera V0.4 FIX2 tetap dipertahankan. Traffic Control dan perubahan konfigurasi traffic masih dinonaktifkan.

## Fitur utama

- Maksimal lima controller melalui `GET /api/status`.
- Pilihan `MOCK DATA` atau `LIVE API`.
- Overview dan diagram persimpangan mengikuti data ESP32-S3 aktual.
- Jumlah kamera otomatis mengikuti `SG aktif + 1 PTZ`.
- Kamera controller terpilih saja yang aktif.
- Grid Live View memakai substream.
- Double-click kamera membuka main stream secara fullscreen.
- Retry stream otomatis setiap lima detik.
- Hikvision Standard dan Custom RTSP.
- Konfigurasi kamera disimpan lokal.
- Password kamera disimpan melalui Windows Credential Manager menggunakan `keyring`.
- Traffic Control tetap dinonaktifkan dalam LIVE API.
- Rasio panel Live Camera dan Live Intersection Diagram tetap 7:4 ketika status stream berubah.
- Alarm komunikasi controller, mode HOLD/FLASHING/SAFETY, status safety, dan camera offline.
- Alarm aktif ditutup otomatis saat kondisi pulih dan pemulihan dicatat sebagai event baru.
- Acknowledge satu/beberapa alarm atau seluruh alarm aktif.
- Filter event berdasarkan controller, severity, status, dan kata pencarian.
- Export event yang sedang difilter ke file CSV.
- Indikator jumlah alarm aktif dan alarm baru pada top bar.
- Response time API, jumlah kegagalan berurutan, dan last successful update.
- Auto-reconnect bertahap 1, 2, 5, 10, lalu maksimum 15 detik ketika controller offline.
- Audit perubahan Controller Connection serta waktu aplikasi start/close.
- Traffic Configuration read-only untuk maksimal lima controller.
- Ringkasan Active SG, jumlah Plan/Schedule/Holiday, Config/Runtime Revision, Apply State, dan Safety.
- Daftar 24 Plan dan seluruh Stage/SG pada Plan yang dipilih.
- Daftar 24 slot Schedule untuk Sunday–Saturday dan Holiday.
- Daftar seluruh 32 slot Hari Libur.
- Peringatan jelas jika data berasal dari Draft Config Editor yang belum di-Commit.
- Request konfigurasi dilakukan secara lazy dan satu per satu hanya ketika halaman dibuka.

## Persyaratan Windows

1. Python 64-bit direkomendasikan.
2. Install VLC Media Player dengan arsitektur yang sama dengan Python:
   - Python 64-bit → VLC 64-bit.
   - Python 32-bit → VLC 32-bit.
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

Jika `LIVE` tampil tetapi gambar tetap hitam, periksa codec kamera dan samakan VLC/Python 32/64-bit. Jika `TIMEOUT` atau `ERROR`, periksa URL, user/password, port 554, dan izin RTSP kamera.

## Alarms & Events

Database dibuat otomatis pada saat aplikasi dijalankan:

```text
command_center_data/events.db
```

Event yang lebih lama dari 90 hari dibersihkan otomatis jika sudah tidak aktif. Alarm aktif tidak dihapus oleh proses retention.

Severity:

- `CRITICAL`: controller offline, mode SAFETY, green conflict, fault, atau konfigurasi tidak valid.
- `WARNING`: mode HOLD/FLASHING, camera offline, atau status safety non-kritis.
- `INFO`: kondisi pulih atau kembali normal.
- `AUDIT`: aplikasi start/close dan perubahan pengaturan koneksi controller.

`Acknowledge` hanya menandai bahwa alarm sudah diketahui operator. Acknowledge tidak menyelesaikan alarm dan tidak mengubah operasi ESP32-S3.

## Menghubungkan controller

1. Buka **CONTROLLERS**.
2. Pilih `LIVE API · ESP32-S3 read-only`.
3. Aktifkan slot controller.
4. Masukkan IP atau Base URL ESP32-S3.
5. Tekan **SAVE & CONNECT**.

## Mengatur kamera

1. Buka **CAMERA CONFIGURATION**.
2. Pilih controller dan kamera.
3. Isi:
   - Camera profile
   - Enable camera
   - Camera IP/hostname
   - RTSP port
   - Username dan password
   - Main stream path
   - Substream path
4. Tekan **TEST CONNECTION** untuk membuka substream.
5. Tekan **PREVIEW** untuk memeriksa main stream fullscreen.
6. Tekan **SAVE CAMERA**.

Preset Hikvision:

```text
Main stream : /Streaming/Channels/101
Substream   : /Streaming/Channels/102
RTSP port   : 554
```

Untuk kamera SG berikutnya, nomor channel dapat disesuaikan dengan konfigurasi kamera di lapangan. Pada kamera IP Hikvision yang berdiri sendiri, channel umumnya tetap 101/102 pada setiap alamat IP kamera.

Kolom Camera IP/hostname dapat berisi IP saja atau URL RTSP lengkap. Jika URL lengkap sudah memiliki path, aplikasi tidak menambahkan path untuk kedua kalinya.

## Membaca Traffic Configuration

1. Hubungkan controller dalam mode `LIVE API`.
2. Buka **TRAFFIC CONFIGURATION**.
3. Pilih controller lalu tekan **REFRESH CONFIGURATION** jika ingin membaca ulang.
4. Gunakan tab:
   - **OVERVIEW** untuk status konfigurasi dan nama 12 SG.
   - **PLANS & STAGES** untuk memilih Plan dan melihat Stage serta state setiap SG.
   - **SCHEDULE** untuk memilih kelompok hari dan membaca 24 slot jadwal.
   - **HOLIDAYS** untuk membaca seluruh 32 slot tanggal hari libur.

Command Center membaca endpoint berikut secara berurutan:

```text
GET /api/editor/status
GET /api/editor/system
GET /api/editor/plans
GET /api/editor/plan?plan=N
GET /api/editor/schedule?day=N
GET /api/editor/holidays
```

Jika Config Editor pada dashboard controller sedang terbuka, firmware mengembalikan sumber `DRAFT`. Command Center menampilkan banner kuning karena data tersebut mungkin belum di-Commit, disimpan, atau diterapkan. Command Center tidak membuka maupun mengubah Draft tersebut.

## Penyimpanan

```text
command_center_data/controllers.json
command_center_data/cameras.json
```

File `cameras.json` tidak menyimpan password. Password disimpan melalui Credential Manager pada sistem operasi.

## Batas keamanan

- ESP32-S3 hanya menerima request GET untuk status dan pembacaan konfigurasi dari Command Center.
- Pembacaan konfigurasi dimulai hanya ketika halaman Traffic Configuration dibuka, dijalankan satu per satu, dan dihentikan saat halaman ditinggalkan.
- Tidak ada request POST ke Config Editor dan tidak ada Editor Start, Update, Commit, Save, atau Safe Apply.
- Tidak ada perintah SKIP, HOLD, FLASHING, Safe Apply, atau perubahan konfigurasi traffic.
- Stream kamera dihentikan ketika operator meninggalkan halaman Live View.
- Controller tetap bekerja mandiri jika Command Center atau kamera terputus.
- Database Event & Alarm hanya berada di PC Command Center dan tidak membebani ESP32-S3.
