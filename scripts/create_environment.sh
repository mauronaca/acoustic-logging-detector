VENV_DIR=".venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[INFO] Creando entorno virtual..."
  python3 -m venv "$VENV_DIR"
fi

# Activar
source "$VENV_DIR/bin/activate"

echo "[INFO] Python activo: $(python -V)"

pip install --upgrade pip
pip install -r requirements.txt
