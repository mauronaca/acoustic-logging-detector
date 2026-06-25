import csv
import argparse
from pathlib import Path
import shutil
from typing import Dict
import re

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# ---------------------------------------------------------------------------
# Configuración de clases
# ---------------------------------------------------------------------------

ILLEGAL_CLASSES = {"Axe", "Chainsaw", "Handsaw", "TreeFalling", "WoodChop"}

LABEL_ILLEGAL = "illegal"
LABEL_LEGAL = "legal"


def map_to_binary(class_name: str) -> str:
    """Mapea el nombre de clase original a 'illegal' o 'legal'."""
    if class_name.strip() in ILLEGAL_CLASSES:
        return LABEL_ILLEGAL
    return LABEL_LEGAL


# ---------------------------------------------------------------------------
# Lectura de anotaciones
# ---------------------------------------------------------------------------

def collect_label_mapping(raw_root: Path) -> Dict[str, str]:
    """
    Recorre recursivamente raw_root, lee todos los CSV/XLS/XLSX que encuentre
    y arma un dict filename -> binary_label ('illegal' o 'legal').
    """
    mapping: Dict[str, str] = {}

    for path in raw_root.rglob("*"):
        suffix = path.suffix.lower()

        # CSV
        if suffix == ".csv":
            print(f"[INFO] Leyendo anotaciones desde CSV: {path}")
            with path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    class_name = row.get("Class Name")
                    if class_name is None:
                        continue

                    class_name = class_name.strip()
                    if not class_name:
                        continue

                    binary_label = map_to_binary(class_name)

                    for col in ("Source File Name", "Dataset File Name"):
                        fname = row.get(col)
                        if not fname:
                            continue

                        fname = fname.strip()
                        if fname and fname not in mapping:
                            mapping[fname] = binary_label

        # Excel
        elif suffix in (".xlsx", ".xls"):
            if not HAS_PANDAS:
                print(
                    f"[WARN] Encontrado {path} pero pandas no está instalado. "
                    f"No se procesará este archivo de anotaciones."
                )
                continue

            print(f"[INFO] Leyendo anotaciones desde Excel: {path}")
            try:
                df = pd.read_excel(path)
            except Exception as e:
                print(f"[ERROR] No se pudo leer {path}: {e}")
                continue

            cols = {str(c).strip(): c for c in df.columns}

            if "Class Name" not in cols:
                print(f"[WARN] El archivo {path} no tiene columna 'Class Name'. Se ignora.")
                continue

            for _, row in df.iterrows():
                val_class = row[cols["Class Name"]]
                if pd.isna(val_class):
                    continue

                class_name = str(val_class).strip()
                if not class_name:
                    continue

                binary_label = map_to_binary(class_name)

                for logical_col in ("Source File Name", "Dataset File Name"):
                    if logical_col not in cols:
                        continue

                    val = row[cols[logical_col]]
                    if pd.isna(val):
                        continue

                    fname = str(val).strip()
                    if fname and fname not in mapping:
                        mapping[fname] = binary_label

    n_illegal = sum(1 for v in mapping.values() if v == LABEL_ILLEGAL)
    n_legal = sum(1 for v in mapping.values() if v == LABEL_LEGAL)
    print(f"[INFO] Mapping construido: {len(mapping)} archivos "
          f"({LABEL_ILLEGAL}={n_illegal}, {LABEL_LEGAL}={n_legal})")
    return mapping


# ---------------------------------------------------------------------------
# Organización de archivos
# ---------------------------------------------------------------------------

def organize_wavs(raw_root: Path, out_root: Path, move: bool = False) -> None:
    """
    Organiza los .wav desde raw_root hacia:
      out_root/illegal/*.wav
      out_root/legal/*.wav
      out_root/unlabeled/*.wav  (si no tiene etiqueta)
    """
    label_mapping = collect_label_mapping(raw_root)

    unlabeled_dir = out_root / "unlabeled"
    unlabeled_dir.mkdir(parents=True, exist_ok=True)

    n_total = 0
    n_unlabeled = 0
    class_counts: Dict[str, int] = {LABEL_ILLEGAL: 0, LABEL_LEGAL: 0}

    # Detalle: cuántas de cada clase original van a cada categoría
    original_class_detail: Dict[str, Dict[str, int]] = {}

    for wav_path in raw_root.rglob("*.wav"):
        # Saltar si ya estamos dentro de organized_dataset
        if out_root in wav_path.parents:
            continue

        n_total += 1
        fname = wav_path.name
        binary_label = label_mapping.get(fname)

        if binary_label is None:
            dest_dir = unlabeled_dir
            n_unlabeled += 1
        else:
            dest_dir = out_root / binary_label
            dest_dir.mkdir(parents=True, exist_ok=True)
            class_counts[binary_label] = class_counts.get(binary_label, 0) + 1

            # Intentar obtener la clase original del nombre de carpeta padre
            parent_name = wav_path.parent.name
            if parent_name not in original_class_detail:
                original_class_detail[parent_name] = {
                    LABEL_ILLEGAL: 0, LABEL_LEGAL: 0
                }
            original_class_detail[parent_name][binary_label] += 1

        dest = dest_dir / fname

        if move:
            shutil.move(str(wav_path), str(dest))
        else:
            shutil.copy2(str(wav_path), str(dest))

    print("\n[RESUMEN]")
    print(f"  Total .wav encontrados: {n_total}")
    print(f"  Sin etiqueta:           {n_unlabeled}")
    print(f"\n  Distribución binaria:")
    print(f"    {LABEL_ILLEGAL}: {class_counts[LABEL_ILLEGAL]}")
    print(f"    {LABEL_LEGAL}:   {class_counts[LABEL_LEGAL]}")

    if class_counts[LABEL_ILLEGAL] > 0:
        ratio = class_counts[LABEL_LEGAL] / class_counts[LABEL_ILLEGAL]
        print(f"    Ratio legal/illegal: {ratio:.1f}:1")

    print(f"\n  Clases ilegales incluidas: {sorted(ILLEGAL_CLASSES)}")
    print(f"  Output en: {out_root}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Organiza WAVs en dos subcarpetas (illegal/legal) "
            "según anotaciones CSV/XLSX."
        )
    )
    parser.add_argument(
        "--raw-root",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "raw_dataset"),
        help="Directorio raíz del dataset crudo (default: ../dataset/raw_dataset)",
    )
    parser.add_argument(
        "--out-root",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "organized_dataset"),
        help="Directorio raíz de salida (default: ../dataset/organized_dataset)",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Si se pasa esta flag, se MUEVEN los .wav en lugar de copiarlos.",
    )

    args = parser.parse_args()

    raw_root = Path(args.raw_root).resolve()
    out_root = Path(args.out_root).resolve()

    if not raw_root.exists():
        raise SystemExit(f"[ERROR] raw_root no existe: {raw_root}")

    out_root.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] raw_root: {raw_root}")
    print(f"[INFO] out_root: {out_root}")
    print(f"[INFO] Modo: {'MOVE' if args.move else 'COPY'}")
    print(f"[INFO] Clases ilegales: {sorted(ILLEGAL_CLASSES)}")

    organize_wavs(raw_root, out_root, move=args.move)


if __name__ == "__main__":
    main()