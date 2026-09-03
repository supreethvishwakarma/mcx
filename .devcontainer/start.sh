#!/usr/bin/env bash
# Runs every time the Codespace starts. Boots the Flask API and the Next.js
# dashboard, wiring the dashboard's browser-side API calls to the *public*
# forwarded URL for the Flask port (not localhost — the browser tab runs on
# your phone, not inside this container, so it can't see the container's
# localhost).
set -e
cd "$(dirname "$0")/.."

pkill -f "backend/app.py" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
sleep 1

sudo service postgresql start 2>/dev/null || true

nohup .venv/bin/python backend/app.py > /tmp/backend.log 2>&1 &

if [ -n "$CODESPACE_NAME" ]; then
  DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  API_URL="https://${CODESPACE_NAME}-5050.${DOMAIN}"
else
  API_URL="http://localhost:5050"
fi
echo "NEXT_PUBLIC_API_URL=${API_URL}" > dashboard/.env.local

cd dashboard
nohup npm run dev > /tmp/dashboard.log 2>&1 &

echo "Backend:   $API_URL"
echo "Dashboard: (see the Ports tab, or the auto-opened browser tab, for the port-3000 URL)"
