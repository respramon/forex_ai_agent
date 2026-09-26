# Validasi 0.1.0 dan perluasan replay

Pemeriksaan awal dilakukan pada 25 September 2026; pemeriksaan ulang pada
26 September 2026 menggunakan Python 3.12.14.
Perintah untuk mengulang pengujian:

```bash
python -m unittest discover -s tests -v
python -m scripts.generate_examples
python -m scripts.generate_agent_replay_example
python -m forex_agent backtest --data examples/agent-replay.synthetic.json --out data/agent-result.json
python -m forex_agent backtest --data examples/backtest.synthetic.json --strategy sma --out data/sma-result.json
python -m compileall -q forex_agent
python -m pip wheel . --no-deps --wheel-dir dist
```

Hasil verifikasi: **83 pengujian lulus**, paket wheel berhasil dibangun, fixture
contoh berhasil diregenerasi. Tes HTTP memakai server localhost sungguhan dengan
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
| Replay agent | Sinyal dari aturan yang sama dengan Signal Mode, calendar as-of, larangan actual masa depan, area entry dan next-open |
| Replay determinism | Semua gap exit diproses sebelum fill pada open yang sama; trigger exit memakai sisi bid/ask yang diinferensikan dari midpoint dan spread |
| Rekonsiliasi | Perbedaan ID, units, SL, snapshot akun berubah, migrasi jurnal lama |
| API reliability | Idempotency journal-open, query boolean ketat, readiness database, penulisan JSON atomik dan permission `0600` |
| Riset | Interval timeframe candle cocok dengan metadata model; biaya per candle dan financing pada replay |

## Belum diverifikasi langsung

- Koneksi akun OANDA, entitlement Alpha Vantage, dan model OpenAI dengan kredensial
  pengguna. Dokumentasi resmi telah diperiksa; contract tests memakai mock.
- Build/run Docker di lingkungan ini; berkas Docker/Compose disertakan untuk
  dijalankan dan diperiksa di host pengguna.
- Matrix CI Python 3.11 dan 3.13 serta Windows/macOS; workflow GitHub menjalankan
  matrix tersebut setelah diunggah. Pengujian lokal hanya Python 3.12 Linux.
- Profitabilitas strategi, backtest out-of-sample pada data **pasar nyata**, latency/slippage aktual, dan
  ketahanan layanan publik. Simulasi sintetis menguji alur dan invariant perangkat
  lunak, bukan kemampuan memperoleh profit.
- Kesesuaian state OANDA saat koneksi jaringan nyata. Snapshot `/openTrades` dan
  versi transaksi diuji memakai mock; rekening dengan perubahan di tengah
  pengambilan perlu diuji pada akun practice.

## Evaluasi berikutnya pada lingkungan pengguna

Konfirmasi spesifikasi kontrak dan biaya broker; cocokkan satu snapshot dengan chart
broker yang memakai batas candle sama. Rekonsiliasi semua posisi dan initial_risk
jurnal. Lakukan paper trading, ukur selisih fill/biaya dan expectancy setelah biaya,
lalu uji parameter pada data terpisah. Jangan memilih parameter hanya dari hasil
fixture sintetis. Semua output tetap merupakan bantuan analisis dan pengambilan
keputusan, tanpa jaminan keuntungan atau pengiriman order otomatis.
