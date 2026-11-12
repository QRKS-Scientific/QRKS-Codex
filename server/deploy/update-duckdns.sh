#!/usr/bin/env bash
# Keeps a free DuckDNS name pointed at this machine if its public IP changes. Cron every 5 minutes:
#   */5 * * * *  DUCKDNS_SUBDOMAIN=qrks-example DUCKDNS_TOKEN=xxxx /home/ubuntu/qrksdock-server/deploy/update-duckdns.sh
set -euo pipefail
curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=" >/dev/null
