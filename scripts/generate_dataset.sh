VENV_DIR=".venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[WARN] No existe entorno virtual."
fi

source "$VENV_DIR/bin/activate"

# Paso 1: Organizar dataset
echo "[STEP 1/2] Organizando dataset..."
python src/organize_dataset.py

echo ""
# Paso 2: Procesar dataset
echo "[STEP 2/2] Procesando dataset..."
python src/process_dataset.py

echo ""
echo "[OK] Dataset generado correctamente."
