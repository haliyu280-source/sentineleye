#!/usr/bin/env bash
# Public demo helper: exposes the local SentinelEye backend through a Cloudflare Quick Tunnel and
# points the Vercel-hosted dashboard at it.
#
# Quick Tunnel URLs are temporary: Cloudflare assigns a new random *.trycloudflare.com address every
# time the tunnel starts, with no uptime guarantee. Run "publish" after every restart.
#
#   deploy/demo-tunnel.sh start     start the tunnel (or reuse a running one) and print its URL
#   deploy/demo-tunnel.sh url       print the current tunnel URL
#   deploy/demo-tunnel.sh publish   rebuild the Vercel dashboard against the current tunnel URL
#   deploy/demo-tunnel.sh stop      stop the tunnel
#
# Needs cloudflared; "publish" also needs the Vercel CLI, logged in, with frontend/ linked to the project.
set -euo pipefail

BACKEND=${SENTINELEYE_BACKEND:-http://127.0.0.1:8000}
if [ -d "$HOME/Library/Logs" ]; then
    LOG=${SENTINELEYE_TUNNEL_LOG:-$HOME/Library/Logs/sentineleye-tunnel.log}
else
    LOG=${SENTINELEYE_TUNNEL_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/sentineleye-tunnel.log}
fi
PATTERN="cloudflared tunnel --no-autoupdate --url $BACKEND"
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

die() { echo "error: $*" >&2; exit 1; }

current_url() {
    [ -f "$LOG" ] || return 1
    grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | tail -1
}

running() { pgrep -f "$PATTERN" >/dev/null; }

# Check a tunnel URL from the outside. A brand-new trycloudflare.com name can be cached locally as
# "not found" if it was looked up too early, so resolve it through public DNS when dig is available.
answers() {
    local url=$1 host ip
    host=${url#https://}
    ip=$(command -v dig >/dev/null && dig +short @1.1.1.1 "$host" | grep -m1 -E '^[0-9.]+$' || true)
    if [ -n "$ip" ]; then
        curl -fsS -o /dev/null --max-time 10 --resolve "$host:443:$ip" "$url/healthz" 2>/dev/null
    else
        curl -fsS -o /dev/null --max-time 10 "$url/healthz" 2>/dev/null
    fi
}

start() {
    command -v cloudflared >/dev/null || die "cloudflared is not installed"
    curl -fsS -o /dev/null "$BACKEND/healthz" || die "backend is not answering at $BACKEND/healthz"
    if running; then
        echo "Tunnel already running."
    else
        mkdir -p "$(dirname "$LOG")"
        : > "$LOG"
        nohup cloudflared tunnel --no-autoupdate --url "$BACKEND" >> "$LOG" 2>&1 &
        # Wait for the URL and a registered connection before anyone looks the name up
        for _ in $(seq 1 60); do
            current_url >/dev/null && grep -q "Registered tunnel connection" "$LOG" && break
            sleep 1
        done
        sleep 5
    fi
    url=$(current_url) || die "no tunnel URL yet; see $LOG"
    for _ in $(seq 1 30); do
        answers "$url" && break
        sleep 2
    done
    answers "$url" || die "tunnel started but $url/healthz is not answering yet; see $LOG"
    echo "$url"
}

publish() {
    command -v vercel >/dev/null || die "the Vercel CLI is not installed"
    url=$(current_url) || die "no tunnel URL; run: $0 start"
    answers "$url" || die "$url is not answering; run: $0 start"
    cd "$ROOT/frontend"
    [ -f .vercel/project.json ] || die "frontend/ is not linked to a Vercel project (run: vercel link)"
    vercel env rm VITE_SENTINELEYE_API_URL production --yes >/dev/null 2>&1 || true
    printf '%s' "$url" | vercel env add VITE_SENTINELEYE_API_URL production >/dev/null
    vercel deploy --prod --yes
}

case "${1:-}" in
    start) start ;;
    url) current_url || die "no tunnel URL; run: $0 start" ;;
    publish) publish ;;
    stop) pkill -f "$PATTERN" && echo "Tunnel stopped." || echo "No tunnel running." ;;
    *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
