#!/usr/bin/env bash
# SentinelEye. Copyright (c) 2026 Ali Khaleel Hassan. All rights reserved. See LICENSE.
# Install the SentinelEye agent as a systemd service on Ubuntu (tested on 24.04).
#
#   sudo ./install.sh --url https://sentineleye.example.com --server-id 3
#
# The agent token is read from the SENTINELEYE_TOKEN environment variable, or prompted for
# without echo. It is never accepted as a command-line flag, which would leave it in shell
# history and in the process list.
set -euo pipefail

INSTALL_DIR=/opt/sentineleye-agent
CONFIG_DIR=/etc/sentineleye-agent
CONFIG_FILE=$CONFIG_DIR/agent.env
UNIT_FILE=/etc/systemd/system/sentineleye-agent.service
SERVICE_USER=sentineleye
SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

url=""
server_id=""
interval=30
allow_http=false
reconfigure=false

usage() {
    sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "Options: --url URL  --server-id N  [--interval SECONDS]  [--allow-http]  [--reconfigure]"
}

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --url) url=${2:-}; shift 2 ;;
        --server-id) server_id=${2:-}; shift 2 ;;
        --interval) interval=${2:-}; shift 2 ;;
        --allow-http) allow_http=true; shift ;;
        --reconfigure) reconfigure=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "unknown option: $1" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "run as root (sudo)"
[ -r /proc/stat ] || die "this agent supports Linux only"
command -v systemctl >/dev/null || die "systemd is required"
command -v python3 >/dev/null || die "python3 is required (apt install python3)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "python3 3.10 or newer is required"
[ -d "$SOURCE_DIR/sentineleye_agent" ] || die "run this script from the agent/ directory of the SentinelEye repository"

# 1. Unprivileged service account
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "Created system user $SERVICE_USER"
fi

# 2. Code (owned by root, readable by the service account, not writable by it)
install -d -m 755 "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/sentineleye_agent"
cp -r "$SOURCE_DIR/sentineleye_agent" "$INSTALL_DIR/"
find "$INSTALL_DIR" -name '__pycache__' -prune -exec rm -rf {} +
chown -R root:root "$INSTALL_DIR"
chmod -R u=rwX,go=rX "$INSTALL_DIR"

# 3. Configuration (contains the token: root-owned, group-readable by the service only)
install -d -m 750 -o root -g "$SERVICE_USER" "$CONFIG_DIR"
if [ -f "$CONFIG_FILE" ] && [ "$reconfigure" = false ]; then
    echo "Keeping existing $CONFIG_FILE (use --reconfigure to replace it)"
else
    [ -n "$url" ] || read -r -p "SentinelEye backend URL: " url
    [ -n "$server_id" ] || read -r -p "Server id (from registration): " server_id
    token=${SENTINELEYE_TOKEN:-}
    if [ -z "$token" ]; then
        read -r -s -p "Agent token (input hidden): " token
        echo
    fi
    [[ "$server_id" =~ ^[0-9]+$ ]] || die "server id must be a number"
    [[ "$interval" =~ ^[0-9]+$ ]] || die "interval must be a number of seconds"

    umask 027
    tmp=$(mktemp "$CONFIG_DIR/.agent.env.XXXXXX")
    {
        echo "# Written by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "SENTINELEYE_URL=$url"
        echo "SENTINELEYE_SERVER_ID=$server_id"
        echo "SENTINELEYE_TOKEN=$token"
        echo "SENTINELEYE_INTERVAL=$interval"
        [ "$allow_http" = true ] && echo "SENTINELEYE_ALLOW_HTTP=true"
    } > "$tmp"
    chown root:"$SERVICE_USER" "$tmp"
    chmod 640 "$tmp"
    mv "$tmp" "$CONFIG_FILE"
    unset token
    echo "Wrote $CONFIG_FILE"
fi

# 4. Prove the configuration works before enabling the service
echo "Sending a test sample..."
if ! runuser -u "$SERVICE_USER" -- env PYTHONPATH="$INSTALL_DIR" PYTHONDONTWRITEBYTECODE=1 \
        python3 -m sentineleye_agent --config "$CONFIG_FILE" --once; then
    die "test sample was not accepted; check the URL, server id and token, then rerun with --reconfigure"
fi

# 5. Service
install -m 644 "$SOURCE_DIR/sentineleye-agent.service" "$UNIT_FILE"
systemctl daemon-reload
systemctl enable sentineleye-agent.service
# restart, not start: a running agent must pick up new code or a reconfigured token
systemctl restart sentineleye-agent.service
systemctl --no-pager --lines=5 status sentineleye-agent.service || true

echo
echo "Installed. Useful commands:"
echo "  systemctl status sentineleye-agent"
echo "  journalctl -u sentineleye-agent -f"
echo "  sudo systemctl restart sentineleye-agent"
