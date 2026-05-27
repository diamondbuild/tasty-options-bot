#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

printf 'Tastytrade username: '
read -r TASTYTRADE_USERNAME

printf 'Tastytrade password (input hidden): '
stty -echo
read -r TASTYTRADE_PASSWORD
stty echo
printf '\n'

printf 'Tastytrade account number: '
read -r TASTYTRADE_ACCOUNT_NUMBER

cat > .env <<EOF
TASTYTRADE_USERNAME=${TASTYTRADE_USERNAME}
TASTYTRADE_PASSWORD=${TASTYTRADE_PASSWORD}
TASTYTRADE_ACCOUNT_NUMBER=${TASTYTRADE_ACCOUNT_NUMBER}
TASTYTRADE_IS_PRODUCTION=false
BOT_LIVE_TRADING=false
BOT_REQUIRE_MANUAL_APPROVAL=true
EOF

chmod 600 .env
printf 'Wrote %s/.env with live trading disabled.\n' "$(pwd)"
printf 'Safe flags:\n'
grep -E 'TASTYTRADE_IS_PRODUCTION|BOT_LIVE_TRADING|BOT_REQUIRE_MANUAL_APPROVAL' .env
