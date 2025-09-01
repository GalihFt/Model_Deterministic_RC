# Aplikasi Alokasi Perbaikan Kontainer

Aplikasi web interaktif yang dibangun menggunakan Streamlit untuk membantu dalam pengambilan keputusan alokasi perbaikan kontainer. Aplikasi ini memberikan rekomendasi vendor perbaikan berdasarkan estimasi biaya yang paling efisien, dengan mempertimbangkan berbagai parameter seperti kapasitas vendor, tipe kontainer, dan algoritma alokasi.

## Tujuan & Kegunaan

Tujuan utama dari aplikasi ini adalah untuk mengoptimalkan dan mengefisiensikan biaya perbaikan kontainer. Dengan data kerusakan yang diinput, aplikasi ini akan:

1. **Menghitung Biaya:** Secara otomatis menghitung total biaya perbaikan untuk setiap vendor yang tersedia berdasarkan data master material.
2. **Memberikan Rekomendasi Alokasi:** Mengalokasikan setiap pekerjaan perbaikan (berdasarkan Nomor EOR) ke vendor yang paling hemat biaya.
3. **Menyediakan Analisis Komparatif:** Menampilkan perbandingan biaya antar vendor, potensi penghematan, dan ringkasan alokasi dalam format yang mudah dipahami.

## Fitur Utama

- **Dua Mode Input:**
  - **Input Manual:** Untuk melakukan estimasi cepat biaya perbaikan satu kontainer dengan beberapa item kerusakan.
  - **Input Massal (Bulk):** Mengunggah data perbaikan untuk banyak kontainer sekaligus melalui file .csv, .xlsx, .xls, atau .ods.
- **Integrasi Google Sheets:** Mengambil data master material, harga, dan MHR (Man-Hour Rate) secara _real-time_ dari Google Sheet, sehingga mudah diperbarui tanpa mengubah kode.
- **Algoritma Alokasi Fleksibel:**
  - **Prediksi Total:** Mengalokasikan pekerjaan berdasarkan potensi penghematan biaya total terbesar.
  - **Prediksi Harga per MHR:** Mengalokasikan berdasarkan efisiensi biaya per jam kerja (MHR).
- **Manajemen Kapasitas Vendor:** Pengguna dapat menentukan batas kapasitas harian untuk setiap vendor, baik dari segi jumlah kontainer maupun total MHR.
- **Filter Prioritas Perbaikan:** Memungkinkan pemrosesan data untuk tipe-tipe kontainer spesifik yang menjadi prioritas (20A, 40C, dll.), dengan dukungan multi-pilihan.
- **Hasil Interaktif & Dapat Diunduh:** Menampilkan hasil dalam bentuk tabel ringkasan dan tabel detail yang interaktif. Semua hasil dapat diunduh dalam format .csv untuk analisis lebih lanjut.
- **Validasi Data:** Memberikan peringatan jika ada material dari file input yang tidak ditemukan di dalam data master.

## Teknologi yang Digunakan

- **Python:** Bahasa pemrograman utama.
- **Streamlit:** Framework untuk membangun dan mendeploy aplikasi web data interaktif.
- **Pandas:** Untuk manipulasi dan analisis data.
- **gspread & oauth2client:** Untuk berinteraksi dengan Google Sheets API.

## Instalasi & Konfigurasi Lokal

Untuk menjalankan aplikasi ini di komputer lokal Anda, ikuti langkah-langkah berikut.

### 1\. Prasyarat

- Python 3.8 atau yang lebih baru.
- Git.
- Akun Google.

### 2\. Kloning Repositori

    git clone https://github.com/GalihFt/Model_Deterministic_RC.git
    cd Model_Deterministic_RC


### 3\. Siapkan Lingkungan Virtual & Instal Dependensi

Sangat disarankan untuk menggunakan _virtual environment_.

    # Membuat virtual environment  
    python -m venv venv  
    # Mengaktifkan di Windows  
    venv\Scripts\activate
    # Mengaktifkan di macOS/Linux  
    source venv/bin/activate

Dari file requirements.txt digunakan untuk instalasi dependensinya.

    pip install -r requirements.txt  

## Menjalankan Aplikasi

Setelah semua konfigurasi selesai, jalankan aplikasi dengan perintah berikut di terminal:

    streamlit run streamlit_app.py  

Aplikasi akan terbuka secara otomatis di browser Anda.

## Catatan 
Terkait sumber data yang digunakan dalam aplikasi ini, khususnya data master material yang diambil dari Google Sheets, akses bersifat terbatas dan tidak dapat diakses secara publik. Untuk dapat menjalankan aplikasi dengan fungsionalitas penuh, Anda memerlukan:

- Otorisasi akses ke Google Sheet yang menjadi sumber data.

- File kredensial JSON yang valid dari Google Service Account yang telah diberi izin akses ke sheet tersebut.

Tanpa akses ini, aplikasi tidak akan dapat mengambil data master dan fungsionalitas kalkulasi tidak akan berjalan.