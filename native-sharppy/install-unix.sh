#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="sharppy-btv"
DS_DIR="$HOME/.sharppy/datasources"
command -v conda >/dev/null 2>&1 || { echo "Install Miniforge/Miniconda first." >&2; exit 1; }
mkdir -p "$DS_DIR"
conda create -y -n "$ENV_NAME" -c conda-forge python=3.10 sharppy=1.4.0 pyside2 requests python-dateutil
read -r -p "Enter Worker hostname (for example btv-sharppy-bufkit.your-subdomain.workers.dev): " WORKER_HOST
[[ -n "$WORKER_HOST" && "$WORKER_HOST" != *"/"* && "$WORKER_HOST" != *" "* ]] || { echo "Enter only the hostname, without https://" >&2; exit 1; }
sed "s/BTV_WORKER_HOST/$WORKER_HOST/g" "$ROOT/btv_cwa.xml" > "$DS_DIR/btv_cwa.xml"
cp "$ROOT/btv_cwa.csv" "$DS_DIR/btv_cwa.csv"
echo "Installed. Launch with: conda run -n $ENV_NAME sharppy"
