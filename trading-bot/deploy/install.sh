#!/usr/bin/env bash
# install.sh — One-shot VPS setup for tania-trading-bot
#
# Run on VPS (root or sudo):
#   curl -fsSL https://.../install.sh | bash
# Or manually:
#   scp -r trading-bot/ root@vps:/opt/tania-trading/
#   ssh root@vps 'cd /opt/tania-trading && bash deploy/install.sh'

set -euo pipefail

INSTALL_DIR="/opt/tania-trading"
REPO_BRANCH="claude/halo-project-nkW96"

echo "=== Tania Trading Bot — VPS installer ==="
echo "Install dir: $INSTALL_DIR"
echo ""

# ---------------------------------------------------------------------------
# 1. System deps
# ---------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
  echo "[1/5] Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
else
  echo "[1/5] Docker already installed: $(docker --version)"
fi

if ! docker compose version &>/dev/null; then
  echo "       Installing docker compose plugin..."
  apt-get update -qq
  apt-get install -y docker-compose-plugin
fi

# ---------------------------------------------------------------------------
# 2. Install directory
# ---------------------------------------------------------------------------
if [ ! -d "$INSTALL_DIR" ]; then
  echo "[2/5] Creating $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ---------------------------------------------------------------------------
# 3. .env check
# ---------------------------------------------------------------------------
if [ ! -f .env ]; then
  echo "[3/5] .env missing — copy .env.example → .env and fill in credentials"
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "      created .env from .env.example. EDIT IT NOW with nano/vi:"
    echo "      nano $INSTALL_DIR/.env"
    exit 1
  else
    echo "ERROR: .env.example missing too. Did you copy the project over?"
    exit 1
  fi
else
  echo "[3/5] .env present"
fi

# Quick sanity check on credentials
if grep -q "BINANCE_TESTNET_API_KEY=$" .env 2>/dev/null; then
  echo "ERROR: BINANCE_TESTNET_API_KEY is empty in .env"
  exit 1
fi

# ---------------------------------------------------------------------------
# 4. Build containers
# ---------------------------------------------------------------------------
echo "[4/5] Building docker images..."
docker compose build

# ---------------------------------------------------------------------------
# 5. Smoke test
# ---------------------------------------------------------------------------
echo "[5/5] Running smoke test — fetch server time from Binance testnet..."
docker compose run --rm tania-bot python -c "
import httpx, os
url = os.environ['BINANCE_TESTNET_REST_BASE'] + '/fapi/v1/time'
r = httpx.get(url, timeout=10)
r.raise_for_status()
print('Server time OK:', r.json())
"

echo ""
echo "=== Install complete ==="
echo ""
echo "Next steps:"
echo ""
echo "  1. Start everything:"
echo "     cd $INSTALL_DIR && docker compose up -d"
echo ""
echo "  2. Watch bot logs:"
echo "     docker compose logs -f tania-bot"
echo ""
echo "  3. Watch research logs:"
echo "     docker compose logs -f tania-research"
echo ""
echo "  4. Emergency close (panic button):"
echo "     docker compose run --rm tania-bot python emergency_close.py"
echo ""
echo "  5. Stop everything:"
echo "     cd $INSTALL_DIR && docker compose down"
echo ""
