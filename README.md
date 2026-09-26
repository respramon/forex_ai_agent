# Forex AI Agent

Asisten analisis forex berbahasa Indonesia dengan strategi terukur, kontrol risiko,
jurnal SQLite, CLI, API lokal, dan narasi AI opsional. Seluruh perhitungan dilakukan
oleh Python; model AI menjelaskan hasil yang telah diperiksa mesin.

**Mulai tanpa API key:** Python 3.11+ dan standard library sudah cukup.

```bash
cd forex-ai-agent
python -m forex_agent demo
python -m forex_agent demo --scenario news
python -m unittest discover -s tests -v
```

Contoh pertama menampilkan setup dari **data sintetis**, contoh kedua menunjukkan
penolakan menjelang berita penting fiktif. Keduanya memakai jam simulasi tetap,
bukan harga pasar saat ini. Tidak ada pengiriman order ke broker.

## Cakupan

| Kebutuhan | Implementasi |
|---|---|
| Instrumen | EUR/USD, GBP/USD, USD/JPY, AUD/USD, XAU/USD |
| Multi-timeframe | M5, M15, H1, H4, Daily; candle tutup saja |
| Indikator | EMA20/50/200, SMA20, RSI14 Wilder, MACD12/26/9, Bollinger20/2, ATR14 Wilder |
| Struktur | Pivot terkonfirmasi, support/resistance, HH/HL atau LH/LL, Fibonacci 38,2/50/61,8% |
| Price action | Engulfing, pin bar, doji, inside bar |
| Strategi | Trend following, breakout, pullback; proxy BOS/sweep/FVG sebagai konteks SMC |
| Fundamental | Filter kalender ekonomi, actual/forecast/previous yang disuplai, sentimen mata uang |
| Risiko | Sizing otomatis, konversi mata uang, spread/slippage/komisi, margin, RR bersih ≥ 2 |
| Disiplin | Batas harian, eksposur gabungan per mata uang, cooldown, deduplikasi sinyal |
| AI | Adapter OpenAI Responses untuk penjelasan opsional; skor mesin bukan peluang menang |

## Empat mode

| Mode | Perintah | Hasil |
|---|---|---|
| Analyst | `analyze --mode analyst` | Observasi teknikal/fundamental tanpa entry/SL/TP |
| Signal | `analyze --mode signal` | BUY, SELL, atau NO_TRADE dengan alasan dan sizing |
| Risk Manager | `risk --trade ...` | APPROVED_RISK atau REJECTED untuk transaksi usulan |
| Journal | `journal ...` | Catat buka/tutup dan evaluasi P/L bersih, R, win rate, profit factor |

`APPROVED_RISK` menilai aturan risiko; pengguna tetap perlu menilai kelayakan arah
dan setup. `NO_TRADE` mengosongkan level entry, stop, target, dan RR.

## Riset paper: backtest dan baseline ML

Jalur riset terpisah dari `analyze`/`risk`/jurnal akun. Dataset contoh di bawah
**sepenuhnya sintetis**; hasilnya tidak mengukur potensi profit di pasar.

```bash
python -m forex_agent backtest --data examples/backtest.synthetic.json --out data/backtest-result.json
python -m forex_agent train --data examples/backtest.synthetic.json --pair EUR/USD --timeframe M5 --out data/model.synthetic.json
python -m forex_agent predict --model data/model.synthetic.json --data examples/backtest.synthetic.json
```

Backtest memvalidasi candle seluruh simbol sebelum replay, memproses sinyal pada
penutupan dan fill pada open berikutnya, mendahulukan stop jika stop serta target
terjangkau pada candle yang sama, dan menghentikan order baru setelah batas
drawdown. Output lengkap berisi event, transaksi, dan ekuitas mark-to-market.
`train` memakai fitur kausal, split menurut waktu dengan purge batas label,
normalisasi pada training saja, dan test yang tidak digunakan untuk memilih
ambang. Skor model belum dikalibrasi sebagai peluang menang. Format dataset,
asumsi, batas, audit, benchmark dan roadmap ada di
[PLATFORM_ROADMAP.md](docs/PLATFORM_ROADMAP.md).

Order paper tersimpan dalam ledger SQLite terpisah dengan idempotensi `client_id`
dan `execution_id`, fill parsial, dan reservasi risiko. Jalur ini tidak
mengirim order ke broker; OANDA pada aplikasi lama tetap baca saja.

## Instalasi opsional

Perintah `python -m forex_agent` berjalan langsung dari folder. Untuk command `forex-agent`:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
forex-agent demo
```

Tidak ada dependency runtime pihak ketiga yang wajib. Instalasi paket menggunakan
setuptools sebagai build tool. Credential dibaca dari environment OS. `.env.example`
adalah panduan; file `.env` tidak dibaca otomatis oleh CLI.

## Jalankan analisis dan risiko

```bash
# Contoh file yang disertakan: simulasi, bukan pasar berjalan.
python -m forex_agent analyze --snapshot examples/synthetic_snapshot.json --mode analyst
python -m forex_agent analyze --snapshot examples/synthetic_snapshot.json --mode signal --db data/demo.sqlite3 --json
python -m forex_agent risk --snapshot examples/synthetic_snapshot.json --trade examples/proposed_trade.json --db data/demo.sqlite3

# Semua parameter risiko tersentral di config/risk.json.
python -m forex_agent demo --policy config/risk.json --out data/report.json

# Instrument/timeframe lain; NO_TRADE adalah keluaran yang sah.
python -m forex_agent demo --pair "XAU/USD" --timeframe H1
```

Demo memakai database sementara baru setiap kali. Analisis file memakai SQLite
persisten; permintaan sinyal yang sama akan ditolak jika sudah diterbitkan.
Mode Analyst dan Risk Manager tidak mengonsumsi kuota penerbitan sinyal.

## Narasi AI opsional

Set `OPENAI_API_KEY` dan `OPENAI_MODEL` ke model yang tersedia pada proyek API Anda,
lalu tambahkan `--explain`:

```bash
python -m forex_agent demo --explain
```

Ringkasan pair, status, alasan, risiko, dan timestamp dikirim untuk narasi. Saldo,
posisi, dan isi jurnal tidak disertakan. Prompt utama berada di
[`forex_agent/prompts/system.md`](forex_agent/prompts/system.md). Output AI berada di
`ai_commentary_unverified`; kegagalan AI tidak mengubah hasil perhitungan.
Biaya dan ketersediaan model mengikuti akun penyedia.

## Sumber data berjalan

Adapter OANDA mendukung pengambilan candle, quote, metadata instrumen, NAV, margin,
jumlah trade terbuka, dan konversi mata uang. Environment bawaan adalah **practice**.
Ketersediaan XAU/USD mengikuti akun dan divisi broker.

```bash
# Set OANDA_API_TOKEN dan OANDA_ACCOUNT_ID melalui environment terlebih dahulu.
# Gunakan kalender aktual yang sudah dinormalisasi, bukan contoh sintetis.
python -m forex_agent fetch-oanda --pair "EUR/USD" --contract-size 100000 --day-start-equity 10000 --fundamentals data/calendar-current.json --out data/market.json
python -m forex_agent analyze --snapshot data/market.json --mode signal --db data/account-practice.sqlite3
```

`--contract-size` adalah konvensi **units per lot** broker Anda. Contoh 100.000 untuk
forex tidak berlaku otomatis bagi emas. OANDA menerima units; lot di laporan adalah
ekuivalen berdasarkan ukuran kontrak yang Anda berikan. `--day-start-equity` harus
sesuai ekuitas awal hari akun pada timezone jurnal (bawaan Asia/Bangkok).

Kalender di versi ini diimpor melalui JSON terverifikasi dari pengguna/pipeline
eksternal; adapter unduhan kalender otomatis belum disertakan. Jika kalender tidak
diketahui, kedaluwarsa, atau tidak mencakup mata uang terkait, sinyal diblokir.
Adapter sentimen Alpha Vantage sudah tersedia; hasilnya dapat digabungkan ke
`fundamentals.sentiment`. Lihat [integrasi](docs/INTEGRATIONS.md).

Jumlah trade terbuka snapshot harus sama dengan jurnal. Rekonsiliasi tiket, ukuran,
dan risiko posisi secara manual sebelum memakai akun yang sudah mempunyai posisi.

## Jurnal

```bash
python -m forex_agent journal --db data/demo.sqlite3 open --file examples/journal_trade.json
python -m forex_agent journal --db data/demo.sqlite3 close --id demo-001 --net-pnl 180 --closed-at 2026-01-15T14:00:00Z
python -m forex_agent journal --db data/demo.sqlite3 summary --simulated
```

Masukkan P/L dalam mata uang akun **setelah semua komisi, swap, dan biaya aktual**.
`initial_risk` adalah risiko kas awal termasuk estimasi biaya, bukan persen. Simulasi
dan transaksi nyata dipisahkan dalam kueri. Gunakan satu database per akun dan mata
uang. Jurnal tidak mengirim atau menutup order broker.

## API lokal dan Docker

```bash
# Contoh Bash: token acak disimpan hanya dalam environment sesi.
export FOREX_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m forex_agent serve --policy config/risk.json
# Terminal lain: GET http://127.0.0.1:8000/health
```

Untuk Docker, set environment token yang sama lalu jalankan:

```bash
docker compose up --build
```

API berada di localhost port 8000. Semua endpoint selain `/health` membutuhkan
`Authorization: Bearer ...`. SQLite tersimpan pada named volume. Petunjuk request
dan batas pemakaian server ada di [API.md](docs/API.md).

## Parameter bawaan

| Aturan | Nilai |
|---|---:|
| Risiko per transaksi / batas keras | 1% / 2% |
| RR bersih minimum | 1:2 |
| Minimum jarak SL | 1,5 × ATR14; struktur dapat memperlebar |
| Konfirmasi | 4 dari 5; keselarasan trend dan RSI wajib |
| Kerugian harian | 3% ekuitas awal hari |
| Risiko portofolio terbuka | 4% ekuitas |
| Risiko terbuka per mata uang | 3% ekuitas; tidak saling menetralkan posisi |
| Transaksi / sinyal per hari | Masing-masing maksimum 3 |
| Kekalahan beruntun dalam hari jurnal | 3 |
| Jeda antar-aktivitas / antar-sinyal | 60 menit |
| Jendela berita high-impact | 30 menit sebelum dan sesudah |
| Maksimum usia quote/akun/konversi | 120 detik |
| Maksimum usia kalender | 15 menit |

Nilai ini adalah aturan desain contoh yang perlu dievaluasi dengan data broker
Anda. Skor konfirmasi bukan estimasi probabilitas, dan belum ada klaim profitabilitas
atau validasi hasil strategi pada data pasar nyata.

## Isi proyek

| Lokasi | Isi |
|---|---|
| `forex_agent/` | Engine, indikator, strategi, risiko, adapter, CLI, API, jurnal |
| `forex_agent/prompts/` | Prompt sistem utama |
| `config/` | Aturan risiko |
| `docs/ARCHITECTURE.md` | Arsitektur dan workflow |
| `docs/STRATEGY_AND_RISK.md` | Definisi strategi, rumus, asumsi dan batas implementasi |
| `docs/INTEGRATIONS.md` | Tools/API, autentikasi, sumber dokumentasi resmi |
| `docs/DATA_CONTRACT.md` | Format snapshot, kalender, CSV, waktu dan mata uang |
| `docs/SIMULATION.md` | Contoh penggunaan dan output yang dihasilkan kode |
| `docs/VALIDATION.md` | Hasil pengujian dan bagian yang belum diuji langsung |
| `examples/` | Snapshot sintetis, output, proposal, contoh jurnal |
| `schemas/` | JSON Schema snapshot |
| `tests/` | Pengujian aturan dan integrasi dengan mock |
| `.github/workflows/` | CI Python 3.11–3.13 |

## Unggah ke GitHub

Ekstrak ZIP, lalu unggah **isi folder `forex-ai-agent`** sebagai root repository
agar `.github/workflows/ci.yml` aktif. Alternatif dengan Git:

```bash
cd forex-ai-agent
git init
git add .
git commit -m "Initial forex analysis agent"
git branch -M main
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

Ganti USERNAME/REPOSITORY dengan repository Anda. Jangan unggah `.env`, snapshot
akun nyata, atau database jurnal. File tersebut ditempatkan di `data/` yang diabaikan
Git. Lisensi MIT; lihat [SECURITY.md](SECURITY.md).
