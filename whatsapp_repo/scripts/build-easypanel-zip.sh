#!/usr/bin/env bash
# Gera ZIPs prontos para deploy no Easypanel (backend e dashboard separados).
# Uso:
#   ./scripts/build-easypanel-zip.sh              # gera os dois
#   ./scripts/build-easypanel-zip.sh backend
#   ./scripts/build-easypanel-zip.sh dashboard

set -euo pipefail

TARGET="${1:-all}"
OUTPUT_DIR="${OUTPUT_DIR:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$REPO_ROOT/dist/easypanel"
fi

if [[ "$TARGET" != "backend" && "$TARGET" != "dashboard" && "$TARGET" != "all" ]]; then
  echo "Uso: $0 [backend|dashboard|all]" >&2
  exit 1
fi

EXCLUDES=(
  "node_modules"
  ".next"
  "__pycache__"
  ".venv"
  ".git"
  "dist"
  "backups"
  "admin_files"
  ".env"
  "*.pyc"
  "*.pyo"
  "*.log"
  ".DS_Store"
  "Thumbs.db"
)

write_backend_guide() {
  local dest="$1"
  cat > "$dest/EASYPANEL.txt" <<'EOF'
GastoZap - Deploy no Easypanel (Backend API)
============================================

1. No Easypanel: Add Service > App > Source: Upload (ZIP)
2. Envie este arquivo ZIP
3. Build method: Dockerfile (na raiz do ZIP)
4. Proxy port: 8000

Variaveis de ambiente obrigatorias:

- DATABASE_URL=postgresql+asyncpg://user:pass@nome-servico-postgres:5432/gastozap
- EVOLUTION_API_URL=https://sua-evolution-api
- EVOLUTION_API_KEY=...
- EVOLUTION_INSTANCE=gastozap
- WEBHOOK_SECRET=...
- OPENAI_API_KEY=sk-...
- ALLOWED_PHONE_NUMBERS=5511999999999
- DASHBOARD_USERNAME=admin
- DASHBOARD_PASSWORD=...
- CORS_ORIGINS=https://seu-dashboard.easypanel.host
- API_SECRET_KEY=...

Observacoes:
- Webhook Evolution: POST https://seu-backend/webhook/evolution
- Header: x-webhook-secret = WEBHOOK_SECRET

PostgreSQL: crie um servico PostgreSQL separado no mesmo projeto.
Use a connection string interna do painel em DATABASE_URL.
EOF
}

write_dashboard_guide() {
  local dest="$1"
  cat > "$dest/EASYPANEL.txt" <<'EOF'
GastoZap - Deploy no Easypanel (Dashboard Web)
==============================================

1. No Easypanel: Add Service > App > Source: Upload (ZIP)
2. Envie este arquivo ZIP
3. Build method: Dockerfile (na raiz do ZIP)
4. Proxy port: 3000

Variaveis de ambiente obrigatorias:

- NEXT_PUBLIC_API_URL=https://seu-backend.easypanel.host

Observacoes:
- NEXT_PUBLIC_API_URL e usada no build do Next.js.
- Defina a variavel antes do deploy e refaca o build ao mudar a URL.
EOF
}

build_zip() {
  local service_key="$1"
  local source_dir="$2"
  local zip_prefix="$3"
  local guide_writer="$4"

  local timestamp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  local staging_root
  staging_root="$(mktemp -d "/tmp/gastozap-easypanel-${service_key}-XXXXXX")"
  local staging_dir="$staging_root/app"
  local zip_name="${zip_prefix}-${timestamp}.zip"
  local zip_path="$OUTPUT_DIR/$zip_name"

  mkdir -p "$staging_dir" "$OUTPUT_DIR"

  if [[ ! -d "$source_dir" ]]; then
    echo "Diretorio de origem nao encontrado: $source_dir" >&2
    exit 1
  fi

  echo ""
  echo "[$service_key] Preparando pacote..."

  local rsync_args=(-a)
  for pattern in "${EXCLUDES[@]}"; do
    rsync_args+=(--exclude "$pattern")
  done

  rsync "${rsync_args[@]}" "$source_dir/" "$staging_dir/"

  if [[ ! -f "$staging_dir/Dockerfile" ]]; then
    echo "Dockerfile nao encontrado em $source_dir" >&2
    exit 1
  fi

  "$guide_writer" "$staging_dir"

  rm -f "$zip_path"
  (
    cd "$staging_dir"
    zip -qr "$zip_path" .
  )

  local size_mb
  size_mb="$(du -m "$zip_path" | awk '{print $1}')"
  echo "[$service_key] ZIP gerado: $zip_path (${size_mb} MB)"

  rm -rf "$staging_root"
}

mkdir -p "$OUTPUT_DIR"

if [[ "$TARGET" == "backend" || "$TARGET" == "all" ]]; then
  build_zip \
    "backend" \
    "$REPO_ROOT/backend" \
    "gastozap-backend-easypanel" \
    write_backend_guide
fi

if [[ "$TARGET" == "dashboard" || "$TARGET" == "all" ]]; then
  build_zip \
    "dashboard" \
    "$REPO_ROOT/dashboard" \
    "gastozap-dashboard-easypanel" \
    write_dashboard_guide
fi

echo ""
echo "Concluido. ZIPs em: $OUTPUT_DIR"
echo ""
echo "Proximo passo no Easypanel:"
echo "  1. Crie PostgreSQL (servico nativo)"
echo "  2. Crie App Backend com o ZIP do backend (porta 8000)"
echo "  3. Crie App Dashboard com o ZIP do dashboard (porta 3000)"
