# Validasi rilis 0.1.0

Pemeriksaan lokal dilakukan pada 25 September 2026 dengan Python 3.12.14.
Perintah untuk mengulang pengujian:

```bash
python -m unittest discover -s tests -v
python -m scripts.generate_examples
python -m compileall -q forex_agent
python -m pip wheel . --no-build-isolation --no-deps --wheel-dir dist
```

Hasil verifikasi: **44 pengujian lulus**, paket wheel berhasil dibangun, fixture
contoh berhasil diregenerasi. Test HTTP memakai server localhost sungguhan dengan
database sementara, sedangkan API eksternal memakai respons mock.

| Area | Bukti yang diperiksa |
|---|---|
| Indikator | Seed EMA, RSI datar/naik/turun, ATR dengan gap, engulfing, pivot tertunda |
| Risiko | EUR/USD, USD/JPY, XAU/USD, akun non-USD, komisi minimum, biaya RR, minimum units, step, margin |
| Signal | BUY dan SELL, multi-timeframe wajib, sinyal duplikat, output tanpa level saat ditolak |
| Data | Candle future/partial/duplikat/NaN, quote stale/future, pair atau konversi salah |
| Fundamental/disiplin | Kalender unknown, berita high-impact, spread tinggi, batas kerugian |
| Jurnal | Net P/L, expectancy R, profit factor, drawdown P/L tertutup, tengah malam Bangkok, persistensi |
| Adapter | OANDA closed candle dan pemetaan spec/konversi; filter waktu dan skor ticker sentimen |
| AI | Payload tidak membawa saldo/units, hasil resmi tidak dimutasi, respons tidak selesai gagal eksplisit |
| HTTP | Health, autentikasi, JSON rusak/NaN, tidak ada endpoint order atau pembacaan path request |

## Belum diverifikasi langsung

- Koneksi akun OANDA, entitlement Alpha Vantage, dan model OpenAI dengan kredensial
  pengguna. Dokumentasi resmi telah diperiksa; contract tests memakai mock.
- Build/run Docker di lingkungan ini; berkas Docker/Compose disertakan untuk
  dijalankan dan diperiksa di host pengguna.
- Matrix CI Python 3.11 dan 3.13 serta Windows/macOS; workflow GitHub menjalankan
  matrix tersebut setelah diunggah. Pengujian lokal hanya Python 3.12 Linux.
- Profitabilitas strategi, backtest out-of-sample, latency/slippage aktual, dan
  ketahanan layanan publik. Simulasi sintetis menguji alur dan invariant perangkat
  lunak, bukan kemampuan memperoleh profit.

## Evaluasi berikutnya pada lingkungan pengguna

Konfirmasi spesifikasi kontrak dan biaya broker; cocokkan satu snapshot dengan chart
broker yang memakai batas candle sama. Rekonsiliasi semua posisi dan initial_risk
jurnal. Lakukan paper trading, ukur selisih fill/biaya dan expectancy setelah biaya,
lalu uji parameter pada data terpisah. Jangan memilih parameter hanya dari hasil
fixture sintetis. Semua output tetap merupakan bantuan analisis dan pengambilan
keputusan, tanpa jaminan keuntungan atau pengiriman order otomatis.
