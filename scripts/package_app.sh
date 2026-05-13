#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="$(python3 -c "import json, pathlib; p=pathlib.Path('$ROOT_DIR/manifest.json'); print(json.loads(p.read_text())['name'] if p.exists() else pathlib.Path('$ROOT_DIR').name)")"
APP_VERSION="$(python3 -c "import json, pathlib; p=pathlib.Path('$ROOT_DIR/manifest.json'); print(json.loads(p.read_text()).get('version', '0.1.0') if p.exists() else '0.1.0')")"
OUT_DIR="${1:-$ROOT_DIR/tmp/dist}"
OUT_FILE="${2:-$APP_NAME-$APP_VERSION.zip}"

if [[ "$OUT_DIR" != /* ]]; then
  OUT_DIR="$ROOT_DIR/$OUT_DIR"
fi

mkdir -p "$OUT_DIR"

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${APP_NAME}.stage.XXXXXX")"
cleanup() { rm -rf "$STAGE_DIR"; }
trap cleanup EXIT

rsync -a \
  \
  `# ── control de versiones ──` \
  --exclude '.git/' \
  --exclude '.git' \
  --exclude '**/.git' \
  --exclude '**/.git/' \
  --exclude '.gitignore' \
  --exclude '.gitkeep' \
  --exclude '.github/' \
  \
  `# ── IDEs y OS ──` \
  --exclude '.DS_Store' \
  --exclude '.idea/' \
  --exclude '.vscode/' \
  --exclude 'Thumbs.db' \
  \
  `# ── entornos locales (nunca al zip) ──` \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude '.env.*.local' \
  \
  `# ── temporales y salidas del build ──` \
  --exclude 'tmp/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude 'coverage/' \
  --exclude '*.log' \
  --exclude '*.log.*' \
  \
  `# ── Python ──` \
  --exclude 'backend/.venv/' \
  --exclude 'backend/.ruff_cache/' \
  --exclude 'backend/.pytest_cache/' \
  --exclude 'backend/.mypy_cache/' \
  --exclude 'backend/**/__pycache__/' \
  --exclude 'backend/**/*.pyc' \
  --exclude 'backend/**/*.pyo' \
  --exclude 'backend/**/*.egg-info/' \
  \
  `# ── datos de usuario (se recrean en primera ejecución) ──` \
  --exclude 'backend/data/*.sqlite' \
  --exclude 'backend/data/*.sqlite-*' \
  --exclude 'backend/data/*.db' \
  --exclude 'backend/data/*.backup*' \
  \
  `# ── Node / frontend ──` \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'frontend/.vite/' \
  --exclude 'frontend/*.tsbuildinfo' \
  \
  `# ── scripts de empaquetado (se excluyen a sí mismos) ──` \
  --exclude 'scripts/' \
  \
  "$ROOT_DIR/" "$STAGE_DIR/$APP_NAME/"

# Segunda pasada: limpieza defensiva por si rsync no aplica globs anidados
find "$STAGE_DIR/$APP_NAME"          -name '.git'                 -exec rm -rf {} + 2>/dev/null || true
find "$STAGE_DIR/$APP_NAME/backend"  -type d -name '__pycache__'   -exec rm -rf {} + 2>/dev/null || true
find "$STAGE_DIR/$APP_NAME/backend"  -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$STAGE_DIR/$APP_NAME/backend"  -type d -name '*.egg-info'    -exec rm -rf {} + 2>/dev/null || true
find "$STAGE_DIR/$APP_NAME/backend/data" -type f \
  \( -name '*.sqlite' -o -name '*.sqlite-*' -o -name '*.db' -o -name '*.backup*' \) \
  -delete 2>/dev/null || true
find "$STAGE_DIR/$APP_NAME/frontend" -type d -name 'node_modules'  -exec rm -rf {} + 2>/dev/null || true
find "$STAGE_DIR/$APP_NAME/frontend" -type d \( -name 'dist' -o -name '.vite' \) -exec rm -rf {} + 2>/dev/null || true

# Asegura que backend/data/ exista vacía (para que la app pueda escribir en primera ejecución)
mkdir -p "$STAGE_DIR/$APP_NAME/backend/data"

ZIP_PATH="$OUT_DIR/$OUT_FILE"
rm -f "$ZIP_PATH"
(
  cd "$STAGE_DIR"
  zip -qr "$ZIP_PATH" "$APP_NAME"
)

SIZE="$(du -sh "$ZIP_PATH" | cut -f1)"
echo "✓ $ZIP_PATH ($SIZE)"
