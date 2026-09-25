# Kontrak data

Lihat [`schemas/snapshot.schema.json`](../schemas/snapshot.schema.json) dan
[`examples/synthetic_snapshot.json`](../examples/synthetic_snapshot.json).
Schema mendeskripsikan bentuk JSON; engine juga memeriksa hubungan antar-field.

| Field | Makna |
|---|---|
| `pair` | Salah satu lima instrumen dengan pemisah `/` |
| `source` | Nama sumber yang sebenarnya; jangan menyamarkan data simulasi |
| `as_of` | Waktu pengambilan snapshot, ISO 8601 dengan offset |
| `simulated` | Boolean eksplisit; `true` menggunakan jam snapshot dan diberi label simulasi |
| `frames` | Object timeframe → array candle; tiap frame wajib 250–5000 bar jika dibutuhkan |
| `quote` | Bid, ask, timestamp asli, flag tradeable |
| `instrument` | Spesifikasi units/tick/pip/margin/komisi dan sumbernya |
| `account` | Ekuitas, free margin, ekuitas awal hari, mata uang, open_trade_count, waktu |
| `conversion` | Mata uang quote/akun, faktor loss/gain/position, waktu |
| `fundamentals` | Kalender, cakupan, sumber, event, sentimen opsional |

## Candle dan waktu

Setiap candle mempunyai `time`, `open`, `high`, `low`, `close`, `volume`, `complete`.
**`time` adalah waktu TUTUP**, bukan waktu buka. Angka harus finite, harga positif,
OHLC konsisten, urutan timestamp naik ketat. Candle future, duplikat, atau belum tutup
ditolak. Tidak ada forward-fill untuk harga yang hilang.

Adapter OANDA menerima timestamp buka, memilih `complete=true`, lalu menambahkan
durasi bar. Daily menggunakan dailyAlignment=0 dan alignmentTimezone=UTC agar
penambahan 24 jam konsisten. Definisi Daily ini bisa berbeda dari chart broker dengan
penutupan New York. Volume OANDA adalah jumlah perubahan harga/tick, bukan volume
pasar forex global; engine tidak memakai volume untuk mengklaim tekanan institusi.

Mode nyata memakai jam komputer UTC, bukan `as_of` sebagai waktu kebenaran. Simulasi
menggunakan `as_of` tetap agar reproduktif; data harus tersedia pada waktu itu.
Jika membuat backtest sendiri, potong tiap frame pada waktu simulasi sebelum
memanggil agent. Tidak ada mesin backtest multi-bar/performance dalam rilis ini.

Frame terbaru dibatasi usia 1,25× durasi + 60 detik; candle pemicu sinyal harus masih
dalam satu durasi timeframe. Celah terbaru > 1,5× durasi ditolak kecuali pola penutupan
akhir pekan yang dikenali. Hari libur/sesi khusus dapat menyebabkan penolakan
konservatif; ini belum kalender sesi broker yang lengkap.

## Spesifikasi instrumen

`pip_size` untuk pelaporan jarak pip; `tick_size` untuk pembulatan harga.
`contract_size` = units per lot, bukan nilai pip. `units_step`, `min_units`,
`max_units` berasal dari broker. `margin_rate` adalah fraksi (0,05 = 5%).
`commission_per_unit_roundtrip` dan `min_commission_roundtrip` harus dalam mata uang
akun, mencakup buka+tutup. Nilai nol berarti input mengasumsikan tidak ada komisi;
pastikan sesuai jenis akun.

Konversi quote ke akun wajib diberikan. Misalnya USD/JPY dengan akun USD membutuhkan
JPY→USD. `loss_factor`, `gain_factor`, `position_factor` dapat berbeda. Mata uang
quote yang sama dengan mata uang akun wajib mempunyai faktor 1. OANDA menggunakan
homeConversions yang diminta lewat pricing; tidak diasumsikan nilai pip tetap USD 10.

`account.open_trade_count` wajib sama dengan jumlah trade terbuka jurnal untuk
mode Signal/Risk. Ini hanya pemeriksaan jumlah; tiket dan risiko aktual tetap harus
direkonsiliasi. Snapshot riil tanpa field tersebut tidak boleh menghasilkan sinyal.

## Kalender dan sentimen

Contoh bentuk input — **waktu/sumber ini contoh sintetis, bukan feed berjalan**:

```json
{
  "status": "ok",
  "as_of": "2026-01-15T12:00:00Z",
  "source": "SYNTHETIC TEST CALENDAR",
  "coverage_from": "2026-01-15T00:00:00Z",
  "coverage_to": "2026-01-16T00:00:00Z",
  "currencies": ["EUR", "USD"],
  "events": [
    {
      "time": "2026-01-15T12:15:00Z",
      "currency": "USD",
      "impact": "high",
      "title": "Inflasi contoh — fiktif",
      "source": "SYNTHETIC",
      "actual": null,
      "forecast": "contoh",
      "previous": "contoh"
    }
  ],
  "sentiment": []
}
```

`status=unknown` memblokir sinyal. `status=ok` dan `events=[]` berarti sumber telah
diperiksa dan benar-benar melaporkan tidak ada event pada cakupan itu; bukan berarti
unduhan gagal. Jangan mengisi `ok` untuk menonaktifkan kontrol berita. Cakupan harus
mencakup kedua mata uang (hanya USD untuk XAU/USD), termasuk jendela ke belakang.

Sentimen berisi object dengan `currency`, `score` (-1 sampai 1), `sample_count`,
`as_of`, `source`. Artikel mentah opsional pada hasil provider tidak dimasukkan ke
prompt AI. Nilai actual/forecast/previous dapat berupa string dengan satuan; kode
tidak mengurangkannya secara otomatis atau menyimpulkan sebab-akibat harga.

## Import CSV

Simpan `M5.csv`, `M15.csv`, `H1.csv`, `H4.csv`, `Daily.csv` dengan header:

```csv
time,open,high,low,close,volume,complete
2026-01-15T12:00:00Z,1.1000,1.1010,1.0990,1.1005,100,true
```

Satu baris di atas hanya contoh format; file analisis membutuhkan minimal 250 bar.
Simpan metadata snapshot tanpa `frames` di JSON terpisah, kemudian jalankan:

```bash
python -m forex_agent import-csv --folder data/csv --metadata data/metadata.json --out data/snapshot.json
```

Tidak ada resampling CSV otomatis. Gunakan data per-timeframe yang sesuai atau
agregasi OHLC sendiri (open pertama, high maksimum, low minimum, close terakhir),
lalu simpan hanya bar yang sudah selesai. Candle lengkap diparsing dan divalidasi;
bar `complete=false` dibuang oleh adapter. Timestamp naive ditolak.
