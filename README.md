# vibe-coding-presence

Discord Rich Presence buat vibe coding: lagi ngoding apa di **Claude Code
CLI**, dan lagi dengerin lagu apa. Jalan di **Linux, macOS, dan Windows**.

Menampilkan proyek yang sedang dikerjakan, apa yang sedang dilakukan, berapa
sesi yang aktif, dan sudah berapa lama — langsung di profil Discord. Saat
tidak ada yang dikerjakan, gantian lagu yang sedang diputar beserta sampul
albumnya.

```
Terminal
📁 aio-lcd +1 lainnya
Menjalankan perintah · 2 sesi aktif
01:23 elapsed
```

Tanpa dependensi. Cuma Python 3 pustaka baku (plus bash di Linux).

[![uji](https://github.com/Lamiore/vibe-coding-presence/actions/workflows/uji.yml/badge.svg)](https://github.com/Lamiore/vibe-coding-presence/actions/workflows/uji.yml)
[![lisensi](https://img.shields.io/badge/lisensi-GPL--3.0-blue)](LICENSE)
![Python 3](https://img.shields.io/badge/Python%203-tanpa%20dependensi-3776AB?logo=python&logoColor=white)
![platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-555)

---

## Cara kerja

Hook Claude Code berumur sangat pendek — prosesnya mati begitu selesai, dan
Rich Presence ikut hilang saat soketnya tertutup. Jadi hook **tidak** bicara
ke Discord. Pembagiannya:

```
hook (tulis JSON, keluar)  →  spool di XDG_RUNTIME_DIR  →  daemon (pegang soket IPC)
      ~1,3 ms                     tmpfs, langsung dihapus       menerbitkan tiap ≥15 dtk
```

Hook sengaja tidak memanggil interpreter, tidak mengurai JSON, dan tidak
menyentuh jaringan — dia jalan di setiap tool call, jadi biayanya harus
mendekati nol. Kalau daemonnya mati, direktori spool tidak ada dan hook
langsung keluar tanpa menulis apa pun.

Di macOS dan Windows hook-nya versi Python (`hooks/lagi-ngapain-hook.py`),
dipanggil lewat *exec form* Claude Code — tanpa shell. bash bawaan macOS (3.2)
tidak punya `EPOCHREALTIME`, dan Windows belum tentu punya bash sama sekali.
Biayanya ~25 ms per tool call di Mac (versi bash ~4 ms), dan isinya tetap cuma
menyalin stdin ke spool. Di sana spool-nya ada di `$TMPDIR` (macOS) atau
`%LOCALAPPDATA%` (Windows).

Daemon berbicara protokol Discord IPC secara langsung (bingkai
`<opcode u32 LE><panjang u32 LE><JSON>` lewat soket domain Unix, atau named
pipe `\\.\pipe\discord-ipc-*` di Windows). Hanya empat opcode yang dipakai,
jadi memasang `pypresence` — yang butuh venv karena pip sistem terkunci PEP
668 — tidak sepadan.

## Lagu yang sedang diputar

Saat tidak ada sesi yang sedang bekerja — atau tidak ada sesi sama sekali —
presence berpindah menampilkan lagu yang sedang diputar:

```
Terminal                          Terminal
📁 lagi-ngapain          →         ♪ NIKI — Did You Like Her In The Morning?
Ngoprek terminal                  Lagi dengerin
   (lagi ngoding)                    (nganggur)
```

Kalau tidak ada sesi sama sekali **dan** tidak ada yang diputar — misalnya PC
baru dinyalakan — presence tetap nempel sebagai kartu kosong:

```
Playing Terminal
💻 Nganggur
```

Urutan prioritasnya: sesi yang sedang bekerja → lagu → kartu kosong. Matikan
kartu kosong lewat `kartu_kosong: false` kalau lebih suka profil bersih saat
tidak ngapa-ngapain.

Kerjaan dan lagu sengaja tidak pernah tampil bersamaan: Discord cuma punya dua baris
teks, jadi menggabungkannya membuat dua-duanya terpotong.

Sumbernya beda per OS, bentuk kartunya sama:

| OS | sumber | yang terbaca |
|---|---|---|
| Linux | **MPRIS** di D-Bus sesi lewat `busctl` | hampir semua pemutar: Spotify, VLC, mpv, tab browser |
| macOS | **AppleScript** lewat `osascript` | Spotify dan Apple Music saja |
| Windows | **Windows Media Session** lewat PowerShell | semua yang muncul di panel media Windows, tab browser termasuk |

Di Linux dipakai `busctl`, bukan pustaka D-Bus: pip sistem terkunci PEP 668
dan `busctl` sudah pasti ada (bagian dari systemd).

**macOS cuma Spotify dan Music.** Apple mengunci API now-playing sistem untuk
aplikasi pihak ketiga sejak macOS 15.4, jadi tab browser tidak bisa dibaca
tanpa trik yang rapuh. Pemutarnya hanya ditanya kalau prosesnya memang jalan —
`tell application` ke aplikasi yang mati justru menyalakannya. Pertama kali,
macOS menanyakan izin *python3 ingin mengendalikan Spotify*; kalau ditolak,
lagunya tidak tampil dan log memberi petunjuk sekali (System Settings →
Privacy & Security → Automation). Python Homebrew ditandatangani ad-hoc, jadi
izin itu bisa perlu diberikan ulang sesudah `brew upgrade python`.

**Windows dibaca tiap 15 detik**, bukan 5: tiap pembacaan menyalakan
PowerShell, dan penerbitan presence memang direm 15 detik.

**Yang perlu disadari soal browser.** Tab browser mengumumkan judul apa pun
yang sedang diputar, bukan cuma musik — judul video YouTube ikut tampil. Yang
**tidak** terbaca: judul tab biasa (GNOME Wayland menutup itu, dan MPRIS memang
hanya mengumumkan media), halaman tanpa media, dan video yang dijeda.

Kalau itu tidak diinginkan:

```bash
./cc_daemon.py --musik off      # matikan seketika, service dimuat ulang
./cc_daemon.py --musik on
```

Atau tutup pemutar tertentu saja lewat `abaikan_pemutar` di konfig, mis.
`["brave", "firefox"]` — Spotify tetap terbaca, browser tidak.

Kebalikannya juga berguna: Spotify desktop yang sudah disambungkan ke Discord
punya presence sendiri, jadi `["spotify"]` membuat lagunya tidak tampil dobel
di profil — lagu dari browser tetap terbaca.

### Sampul album

Sampul album jadi gambar besar presence — **di kartu musik maupun saat lagi
ngoding**. Slot itu yang biasanya diisi ikon aplikasi, jadi selama ada lagu
yang diputar ikon aplikasinya memang tergantikan sampulnya; nama aplikasinya
tetap tertulis di baris teratas presence. Di kartu kerja judul lagunya cuma
muncul saat gambarnya disentuh kursor — dua baris teksnya sudah kepakai nama
proyek dan kegiatan. Matikan lewat `sampul_saat_kerja: false` kalau ikon
aplikasinya lebih penting.

Discord menerima URL
`https://` mentah di `assets.large_image` — klien Discord sendiri yang
menandatanganinya ke media proxy miliknya — jadi tidak ada berkas yang perlu
diunggah ke mana pun, dan tidak ada token akun yang dibutuhkan.

Sumber sampulnya dua, dicoba berurutan:

1. **`mpris:artUrl` dari pemutarnya**, kalau isinya sudah URL `http(s)`.
   Spotify desktop dan mpd begitu. Nol permintaan keluar.
2. **iTunes Search API**, kalau tidak. Pemutar berbasis browser menulis
   sampulnya ke berkas sementara di `/tmp`, dan berkas lokal tidak berarti
   apa-apa buat Discord. Tanpa akun, tanpa kunci API. Dicoba dua kali:
   artis + album dulu, lalu artis + judul lagu. Jatuhan itu bukan hiasan —
   `entity=album` sering nihil walau albumnya jelas ada (mis. *a beautiful
   blur (deluxe)*), sementara pencarian per lagu menemukannya dan tetap
   membalas sampul album yang sama.

Hasilnya disinggahi di `~/.cache/lagi-ngapain/sampul.json` (lewat
`CacheDirectory=` di berkas unit — sandbox service-nya bikin `~/.cache`
read-only, dan tanpa baris itu singgahannya gagal ditulis diam-diam), termasuk hasil
"tidak ketemu" — satu lagu cuma ditanyakan sekali, sesudah itu dibaca dari
disk. Galat jaringan sengaja **tidak** disinggahi, supaya sampulnya muncul
sendiri begitu internetnya pulih — tapi lagu yang barusan gagal juga tidak
dicoba lagi selama satu menit. Tenggat urllib berlaku per operasi soket, bukan
per permintaan, jadi tanpa rem itu satu API yang macet bisa menahan denyut
daemon berulang-ulang. Kalau gagal, kartunya tetap tampil, cuma tanpa gambar.

Matikan lewat `sampul: false` di konfig.

### Kata di pojok atas

Baris teratas presence adalah `<jenis> <nama aplikasi>`, dan dua-duanya bisa
diatur. Nama aplikasi diganti di Developer Portal (Application ID tidak
berubah); jenisnya lewat konfig:

| nilai | tampil |
|---|---|
| `0` | Playing *(bawaan saat ngoding)* |
| `2` | Listening to *(bawaan saat dengerin)* |
| `3` | Watching |
| `5` | Competing in |

`1` (Streaming) sengaja ditolak: diuji langsung ke Discord, nilainya diterima
tapi tidak dikembalikan — dia menuntut URL Twitch/YouTube yang sah. Jatuh ke
bawaan lebih baik daripada diam-diam kehilangan jenisnya.

## Privasi

Rich Presence terbaca oleh **seluruh daftar teman**. Bawaannya karena itu
sengaja kasar: jalur berkas, isi perintah, dan teks prompt tidak pernah
ditampilkan kecuali diminta.

| mode | yang tampil |
|---|---|
| `minimal` | "Sedang ngoding" — tidak ada nama proyek |
| `normal` *(bawaan)* | nama folder proyek + jenis kegiatan |
| `detail` | tambah nama berkas yang disunting / perintah yang dijalankan |

Bahkan di `detail`, perintah Bash dipotong ke **kata pertama saja** — jadi
`psql -U admin -W hunter2 -h db.internal` tampil sebagai `psql`.

Mode `minimal` juga menutup judul lagu, bukan cuma nama proyek — judul lagu
sama personalnya. Sampul album ikut ditutup di mode itu — di kedua kartu:
gambar sampul yang kebaca orang membocorkan lagunya persis seperti judulnya.

**Dua sumber data, tidak ada yang lain:** muatan hook Claude Code (`cwd`,
nama alat, id sesi) dan pemutar musik (MPRIS / AppleScript / Windows Media
Session, lihat di atas). Judul jendela, isi berkas,
ketikan, dan papan klip tidak pernah disentuh.

**Satu permintaan keluar,** dan cuma satu jenis: pencarian sampul ke iTunes
Search API. Yang dikirim artis + album (lalu judul lagu) — jadi Apple bisa tahu apa
yang sedang diputar, walau tidak tahu siapa yang memutarnya. Sekali per lagu
baru; sisanya dari singgahan. Mode `minimal` tidak pernah mengirimnya sama
sekali, dan `sampul: false` mematikannya di semua mode.

Proyek yang namanya tidak boleh tampil sama sekali didaftarkan di
`proyek_privat`; namanya diganti "proyek privat".

## Pasang

Paling gampang lewat menu terminal — jalan di ketiga OS:

```bash
python3 atur.py      # Linux, macOS  (Windows: py atur.py)
```

```
 vibe-coding-presence
 ──────────────────────────────────────
 Presence  ● nyala
 Daemon    jalan
 Discord   kebuka
 App ID    1402837465912837465
 ──────────────────────────────────────
  1  Masukin / ganti Application ID
  2  Nyalain presence
  3  Matiin presence
  q  Keluar
```

"Nyalain" yang pertama sekaligus memasang hook dan autostart. "Matiin"
bertahan walau PC di-restart: daemon tetap dinyalakan saat login, membaca
`aktif: false`, lalu langsung keluar dengan rapi — jadi autostart-nya tidak
perlu dicabut-pasang. Status Discord diperiksa dengan benar-benar menyambung,
bukan sekadar melihat berkas soket, karena di macOS berkas itu tertinggal
sesudah Discord ditutup.

Pemasang langsungnya, kalau lebih suka tanpa menu:

```bash
./pasang.sh          # Linux (systemd)
python3 pasang.py    # macOS (launchd)
py pasang.py         # Windows (Run di registry, tanpa admin)
```

| OS | autostart | log |
|---|---|---|
| Linux | service systemd pengguna `lagi-ngapain` | `journalctl --user -u lagi-ngapain -f` |
| macOS | LaunchAgent `io.github.lamiore.lagi-ngapain` | `~/Library/Logs/lagi-ngapain.log` |
| Windows | nilai `lagi-ngapain` di `HKCU\…\Run`, lewat `pythonw` (tanpa jendela) | `~/.cache/lagi-ngapain/daemon.log` |

Clone repo ini ke tempat tetap dulu — autostart dan hook menunjuk ke folder
itu. Di macOS dan Windows, jalankan `pasang.py` lagi sesudah memindah repo
atau menaikkan versi Python mayor.

> **Windows belum diuji di mesin asli.** Suite ujinya lolos di Windows di
> GitHub Actions — termasuk bolak-balik bingkai lewat named pipe sungguhan, dan
> skrip PowerShell Windows Media Session yang jalan tanpa galat (tanpa ada
> media yang diputar). Alur penuhnya — Discord asli, lagu yang benar-benar
> diputar, autostart saat login — belum dicoba di PC Windows.

Pemasang akan meminta **Application ID** Discord. Bikin dulu:

1. buka <https://discord.com/developers/applications>
2. **New Application**, namai misalnya `Terminal` — nama aplikasi ini yang
   jadi baris paling atas di presence, dan tidak bisa diganti per pembaruan.
   `Claude Code` sendiri ditolak Discord ("The application name is invalid"),
   karena nama merek.
3. salin **Application ID** di halaman *General Information*

Tidak perlu bot, token, maupun OAuth. Application ID bukan rahasia.

Pemasang menyunting `~/.claude/settings.json` (dicadangkan dulu ke
`settings.json.sebelum-lagi-ngapain`) dan hanya menyisipkan entri miliknya —
hook alat lain seperti `rtk` atau `context-mode` tidak disentuh.

> Claude Code membaca ulang `settings.json` saat itu juga, jadi sesi yang
> **sedang berjalan** pun langsung ikut terpantau — tidak perlu dibuka ulang.
> (Diuji langsung: presence terbit ~15 detik setelah `pasang.sh` selesai,
> dari sesi yang sudah jalan sebelum pemasangan.)

Di Windows tidak ada systemd yang menyalakan ulang daemon yang jatuh. Daemon
menyentuh berkas `detak` tiap detik dan hook diam kalau detaknya basi, jadi
daemon yang mati tidak meninggalkan spool yang terus menumpuk; menghentikannya
pun lewat berkas tanda, bukan sinyal, supaya presence sempat dikosongkan.

## Pakai

```bash
./cc_daemon.py --status               # konfig, soket, keadaan spool
systemctl --user restart lagi-ngapain # setelah mengubah konfig (Linux)
journalctl --user -u lagi-ngapain -f  # lihat apa yang diterbitkan (Linux)
./copot.sh                            # cabut hook + service (Linux)
python3 pasang.py --copot             # cabut hook + autostart (macOS/Windows)
```

Muat ulang sesudah mengubah konfig di macOS dan Windows:

```bash
launchctl kickstart -k gui/$(id -u)/io.github.lamiore.lagi-ngapain   # macOS
py pasang.py                                                        # Windows
```

`--musik on|off` menyimpan konfig dan memuat ulang daemon sendiri di ketiga OS.

Konfigurasi: `~/.config/lagi-ngapain/konfig.json`

| kunci | bawaan | arti |
|---|---|---|
| `client_id` | — | Application ID Discord |
| `aktif` | `true` | saklar presence dari `atur.py`; `false` bertahan lewat restart |
| `mode` | `normal` | tingkat privasi (lihat di atas) |
| `proyek_privat` | `[]` | nama folder yang disamarkan |
| `jeda_publish` | `15` | jarak minimum antar penerbitan, detik |
| `ttl_sesi` | `900` | sesi sediam ini dianggap mati, detik |
| `tampilkan_timer` | `true` | tampilkan timer di presence |
| `sumber_timer` | `nyala_pc` | `nyala_pc`: sejak PC dinyalakan, sama di semua kartu; `sesi`: sejak sesi tertua, kartu kerja saja |
| `musik` | `true` | tampilkan lagu saat tidak ada yang dikerjakan |
| `sampul` | `true` | cari sampul album lagu yang sedang diputar |
| `sampul_saat_kerja` | `true` | pasang sampulnya juga di kartu kerja, bukan cuma saat nganggur |
| `kartu_kosong` | `true` | tetap tampilkan presence saat tidak ada sesi & tidak ada lagu |
| `abaikan_pemutar` | `[]` | awalan nama pemutar yang tidak boleh dibaca |
| `label` | `{}` | timpaan teks kegiatan, mis. `{"Bash": "Ngetik perintah"}` |
| `tipe_kerja` | `0` | kata pojok atas saat ngoding (lihat di bawah) |
| `tipe_musik` | `2` | kata pojok atas saat dengerin |

`jeda_publish` tidak bisa turun di bawah 15 detik — Discord membatasi laju
`SET_ACTIVITY` (~5 per 20 detik), dan tool call beruntun akan menjebolnya.

## Catatan Linux

**Discord Flatpak menaruh soketnya di tempat lain.** Bukan di akar
`$XDG_RUNTIME_DIR`, tapi di `$XDG_RUNTIME_DIR/app/com.discordapp.Discord/`.
Daemon menggeledah keduanya (plus jalur Snap) alih-alih bergantung pada
symlink — symlink ke soket Flatpak menggantung setiap kali Discord ditutup.

**Discord ditutup lalu dibuka lagi: presence balik sendiri.** Diukur langsung
(`uji/probe/pulih_koneksi.py`): daemon melihat broken pipe, menunggu 10 detik,
menyambung ulang, lalu menerbitkan ulang saat itu juga. Penerbitan ulangnya
wajib -- Discord membuang presence saat koneksi putus, jadi mengirim muatan
yang "sama" tetap perlu. Jeda terburuknya sekitar 10 detik sesudah Discord
kebuka lagi.

**Presence tidak nyangkut.** Kalau terminal ditutup paksa, `SessionEnd` tidak
sempat jalan; sesi yang diam melewati `ttl_sesi` dibuang sendiri. Discord
ditutup di tengah jalan pun aman — daemon menyambung ulang tiap 10 detik dan
menerbitkan ulang, karena presence hilang saat koneksi putus.

## Uji

```bash
python3 uji/semua.py                # seluruh uji, ~1 dtk
python3 uji/uji_cc_state.py         # satu berkas saja
python3 uji/probe/pulih_koneksi.py  # ~40 dtk, di luar suite
```

Tanpa Discord yang menyala dan tanpa menyentuh jaringan — bagian IPC-nya
diuji lewat server soket palsu (dan server named pipe `_winapi` di Windows)
yang bicara protokol yang sama, pembaca lagunya lewat jawaban `busctl`,
`osascript`, dan PowerShell palsu, dan pencarian sampulnya lewat pencari yang
disuntik.

Suite yang sama jalan otomatis di GitHub Actions (`.github/workflows/uji.yml`)
di Linux, macOS, dan Windows tiap push dan pull request.

### Mengubah kata-katanya

Semua teks kegiatan bisa ditimpa dari konfig tanpa menyentuh kode:

```json
{ "label": { "Bash": "Ngetik perintah", "idle": "Rehat dulu" } }
```

Kunci yang tidak disebut memakai bawaan di `cc_state.LABEL_BAWAAN`. Selain
nama alat, ada empat kunci khusus: `mcp`, `lainnya` (cadangan, `{alat}`
diganti nama alatnya), `berpikir`, `idle`, dan `dengerin`.

## Lisensi

GPL-3.0
