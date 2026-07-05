#!/usr/bin/env bash
# SafeKids mobil ilovasini sinash uchun demo Guardian Box (macOS/Linux).
#
#   ./scripts/demo-box.sh start    # box + health'ni ishga tushiradi, pairing kodini chiqaradi
#   ./scripts/demo-box.sh status   # ishlayaptimi, kod nima
#   ./scripts/demo-box.sh stop     # hammasini to'xtatadi
#
# Nima ishlaydi:
#   - device_demo: sun'iy yiqilish stsenariysi HAQIQIY zanjir orqali
#     (tracking -> events -> risk -> notifications -> Device API :8787/:8788)
#     — ilovaga har ~10 soniyada yangi incident keladi.
#   - demo_health: :8790/health va /metrics — Dashboard/Kameralar/Tizim
#     ekranlari uchun (CPU/RAM/disk — mashinaning haqiqiy ko'rsatkichlari).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${DEMO_BOX_DIR:-/tmp/guardian-demo-box}"
BOX_LOG="$RUN_DIR/box.log"
HEALTH_LOG="$RUN_DIR/health.log"

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }

lan_ip() {
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null \
        || hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1"
}

pairing_code() {
    grep -o 'pairing code: [0-9]*' "$BOX_LOG" 2>/dev/null | head -1 | grep -o '[0-9]*' || true
}

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

print_info() {
    local code ip
    code="$(pairing_code)"
    ip="$(lan_ip)"
    echo
    say "Demo Guardian Box ishlayapti"
    cat <<EOF

  Pairing kodi:        ${code:-<box.log da qidiring>}
  Simulyator uchun:    manzil 127.0.0.1, port 8787
  Haqiqiy telefon:     manzil $ip, port 8787 (telefon shu Wi-Fi'da bo'lsin)
  Health tekshirish:   http://127.0.0.1:8790/health
  Loglar:              $BOX_LOG

Ilovani ishga tushirish:
  cd $REPO/mobile
  open -a Simulator && flutter run          # simulyatorda
  flutter run -d <iphone-id>                # haqiqiy iPhone'da

Ilovada: "Enter manually" -> manzil + kod -> Pair.
Eslatma: pairing kodi BIR MARTALIK — qayta ulanish kerak bo'lsa
'./scripts/demo-box.sh stop && ./scripts/demo-box.sh start' qiling
(ilovadagi mavjud pairing esa qayta ishga tushirishdan keyin ham ishlayveradi).
EOF
}

case "${1:-start}" in
start)
    if alive "$RUN_DIR/box.pid"; then
        say "allaqachon ishlayapti"
        print_info
        exit 0
    fi
    rm -rf "$RUN_DIR"
    mkdir -p "$RUN_DIR"
    cd "$REPO"

    say "device_demo (Device API :8787/:8788) ishga tushmoqda"
    nohup uv run python -m guardian_edge.tools.device_demo \
        --data-dir "$RUN_DIR/data" > "$BOX_LOG" 2>&1 &
    echo $! > "$RUN_DIR/box.pid"

    say "demo_health (:8790) ishga tushmoqda"
    nohup uv run python -m guardian_edge.tools.demo_health > "$HEALTH_LOG" 2>&1 &
    echo $! > "$RUN_DIR/health.pid"

    for _ in $(seq 1 30); do
        [ -n "$(pairing_code)" ] && break
        sleep 1
    done
    if [ -z "$(pairing_code)" ]; then
        echo "XATO: pairing kodi chiqmadi — $BOX_LOG ni tekshiring" >&2
        exit 1
    fi
    curl -sf http://127.0.0.1:8790/health >/dev/null \
        || { echo "XATO: health :8790 javob bermayapti — $HEALTH_LOG" >&2; exit 1; }
    print_info
    ;;
status)
    if alive "$RUN_DIR/box.pid"; then
        print_info
    else
        say "ishlamayapti ('./scripts/demo-box.sh start' bilan ishga tushiring)"
    fi
    ;;
stop)
    for pid_file in "$RUN_DIR/box.pid" "$RUN_DIR/health.pid"; do
        alive "$pid_file" && kill "$(cat "$pid_file")" 2>/dev/null
    done
    say "to'xtatildi"
    ;;
*)
    echo "ishlatish: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac
