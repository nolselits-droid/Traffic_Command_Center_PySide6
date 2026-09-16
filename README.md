# Traffic Command Center — PySide6 V0.4 FIX2

Command Center read-only untuk Traffic Light Controller ESP32-S3 V1.23.1 dengan monitoring RTSP camera.

FIX2 mempertahankan perbaikan RTSP pada FIX1 dan menstabilkan layout Live View. Perubahan teks status kamera tidak lagi dapat mengubah lebar panel kamera maupun Live Intersection Diagram.

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

## Penyimpanan

```text
command_center_data/controllers.json
command_center_data/cameras.json
```

File `cameras.json` tidak menyimpan password. Password disimpan melalui Credential Manager pada sistem operasi.

## Batas keamanan

- ESP32-S3 hanya menerima request GET `/api/status` dari Command Center.
- Tidak ada perintah SKIP, HOLD, FLASHING, Safe Apply, atau perubahan konfigurasi traffic.
- Stream kamera dihentikan ketika operator meninggalkan halaman Live View.
- Controller tetap bekerja mandiri jika Command Center atau kamera terputus.
