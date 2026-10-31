#!/usr/bin/env bash
# Remove the SentinelEye agent. Configuration (and the token in it) is kept unless --purge is given.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "error: run as root (sudo)" >&2; exit 1; }

systemctl disable --now sentineleye-agent.service 2>/dev/null || true
rm -f /etc/systemd/system/sentineleye-agent.service
systemctl daemon-reload
rm -rf /opt/sentineleye-agent

if [ "${1:-}" = "--purge" ]; then
    rm -rf /etc/sentineleye-agent
    userdel sentineleye 2>/dev/null || true
    echo "Agent, configuration and service user removed."
else
    echo "Agent removed. Configuration left in /etc/sentineleye-agent (use --purge to delete it)."
fi
echo "Revoke this server's token in SentinelEye if the machine is being retired."
