#!/usr/bin/env bash
# Pencabut lagi-ngapain. Hook alat lain di settings.json tidak disentuh.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="lagi-ngapain.service"

systemctl --user disable --now "$UNIT" 2>/dev/null || true
rm -f ~/.config/systemd/user/"$UNIT"
systemctl --user daemon-reload
BIN="$HOME/.local/bin/presence"
[ "$(basename "$(readlink "$BIN" 2>/dev/null)")" = atur.py ] && rm -f "$BIN"

python3 - "$DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import cc_pasang
print("  " + cc_pasang.copot()[1])
PY
# Singgahan sampul album murni turunan -- beda dengan konfig, tidak ada
# yang hilang kalau dibuang.
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/lagi-ngapain"

echo "Dicopot. Konfig di ~/.config/lagi-ngapain/ sengaja dibiarkan."
