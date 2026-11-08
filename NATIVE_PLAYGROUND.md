# Mahjong Wild — native wallet Playground

Branch `feat/agency-native-wallet-20261108`, 8 November 2026. Opt-in sandbox; mode guest/Studio semula tetap default ketika AGENCY_WALLET_MODE tidak diisi. Live mode ditolak.

FastAPI memakai engine Python asli dan renderer Studio yang dibangun dari source. Konfigurasi baseline dan hash engine dipatok per tiket; editor Studio asli tetap terpisah.

## Menjalankan

Gunakan image Dockerfile repo dan satu instance. Sediakan persistent volume `/data`, lalu set:

- `AGENCY_WALLET_MODE=sandbox`
- `AGENCY_WALLET_ORIGIN` ke origin HTTPS backend Playground sandbox
- `AGENCY_WALLET_KEY_ID` dan `AGENCY_WALLET_SECRET` khusus game/environment, server-side
- `MAHJONG_AGENCY_DB_PATH=/data/agency.sqlite3`
- Khusus Skygate: `SKYGATE_RELEASE_DIR=/data/releases`

Start: `python tools/start_studio.py`. `/health` memeriksa database serta melaporkan mode dan source commit. Entry point menyiapkan mount Railway lalu menurunkan UID/GID ke 1000. Single replica, tanpa overlap deployment; SQLite tidak boleh dibagikan ke beberapa instance. Simpan volume dan signing key lintas deployment. Cadangkan volume sebelum migrasi atau penghapusan service.

## Kontrak saldo

Buka dari tombol Play storefront agen: token fragment sekali pakai → redeem HMAC → cookie HttpOnly → sesi canonical tenant/player. Tidak ada fallback ke saldo demo, reset saldo, seed pilihan browser, atau payout yang dikirim browser.

Satuan agen tidak diubah. Stake dan biaya harus persis sesuai `coin_scale` (0–12); pilihan pecahan yang tidak sesuai ditolak. Payout total sesudah seluruh free spins/bonus dibulatkan **half-up satu kali** ke presisi agen, dan reserve liability dibulatkan ke atas. Contoh coin_scale 0: payout 0.5 → 1; 0.49 → 0. Kebijakan terlihat di informasi game. Paytable, bobot, multiplier dan batas win tidak diubah. Pembulatan dapat memengaruhi return efektif; sandbox ini bukan persetujuan ekonomi/RTP untuk live.

Intent, payload idempotency, hasil, payout dan sesi disimpan SQLite FULL/WAL sebelum reserve. Retry memakai ronde dan hasil yang sama. Settlement terjadi di server sebelum animasi. Timeout sesudah reserve/settle tidak menyebabkan refund lokal atau reroll. Worker 30 detik memulihkan intent tertunda walau browser ditutup; restart juga memulihkan melalui request state. Session baru milik actor yang sama dapat membaca riwayat. Jangan hapus database untuk mengatasi timeout: cek koneksi/key/risk pool dan pulihkan intent.

## Validasi

- Fault injection setelah reserve dan setelah settle, restart storage, replay request, payload berubah, integer precision, penolakan field payout browser.
- UAT lintas repo di `Playground/tests/agency-native-slots.cjs`: UI 64COR asli → login → tombol Play → mobile Chromium → spin native → restart → retry → kembali ke 64COR; saldo cocok dan settlement journal tepat sekali.
- Skygate juga menguji tombol BUY SPIN dan Bonus Booster dengan biaya dari server.
- Database UAT terisolasi PGlite dan saldo sintetis; bukan transfer bank. Bukti deployment tersimpan dalam dokumen Playground.

Backend pusat tetap berwenang terhadap saldo, batas player, pilihan game agen, environment, settlement dan risk pool. Runtime native tidak memiliki akses master atau konfigurasi payment gateway.
