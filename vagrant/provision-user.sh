#!/usr/bin/env bash
# Aprovisionamiento como usuario vagrant: MCP server de KiCad y registro en Claude Code.
set -euo pipefail

MCP_DIR="$HOME/KiCAD-MCP-Server"

if [ ! -d "$MCP_DIR" ]; then
  git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git "$MCP_DIR"
fi

cd "$MCP_DIR"
# La red NAT de la VM es inestable: reintentos largos de npm
npm config set fetch-retries 8
npm config set fetch-retry-mintimeout 20000
npm config set fetch-retry-maxtimeout 120000
for intento in 1 2 3; do
  npm install && break
  echo "npm install falló (intento $intento), reintentando..."; sleep 15
done
pip3 install --break-system-packages -r requirements.txt
npm run build

# Ubicación del módulo pcbnew de KiCad 9 (PPA): /usr/lib/python3/dist-packages
KICAD_PY="$(python3 -c 'import pcbnew,os;print(os.path.dirname(os.path.dirname(pcbnew.__file__)))' 2>/dev/null || true)"
KICAD_PY="${KICAD_PY:-/usr/lib/python3/dist-packages}"

if ! claude mcp list 2>/dev/null | grep -q '^kicad'; then
  claude mcp add kicad -s user -e PYTHONPATH="$KICAD_PY" -- node "$MCP_DIR/dist/index.js"
fi

echo "Listo. Abrí 'claude' en la VM y hacé el login."
