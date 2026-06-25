import argparse
import shutil
import random
from pathlib import Path
from typing import List, Tuple, Dict, Optional

import numpy as np
import librosa
from sklearn.model_selection import train_test_split, GridSearchCV, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    accuracy_score,
    make_scorer,
    f1_score,
    precision_score,
    recall_score,
)

try:
    from joblib import dump
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False


LABEL_ILLEGAL = "illegal"
LABEL_LEGAL = "legal"


# ---------------------------------------------------------------------------
# VAD
# ---------------------------------------------------------------------------

def vad_mask(y: np.ndarray, sr: int, frame_length: int = 2048,
             hop_length: int = 512, threshold_db: float = -40.0,
             min_active_frames: int = 3) -> np.ndarray:
    rms = librosa.feature.rms(y=y, frame_length=frame_length,
                               hop_length=hop_length)[0]
    if rms.max() < 1e-10:
        return np.ones(len(rms), dtype=bool)

    rms_db = librosa.amplitude_to_db(rms, ref=rms.max())
    mask = rms_db > threshold_db

    if mask.sum() < min_active_frames:
        return np.ones(len(rms), dtype=bool)

    return mask


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

N_FEATURES = 130

def extract_features(path: Optional[Path] = None,
                     y_preloaded: Optional[np.ndarray] = None,
                     sr_preloaded: Optional[int] = None,
                     apply_vad: bool = True) -> np.ndarray:
    """
    130 features: 20 MFCCs + 20 delta + 20 delta2 + 5 spectral,
    cada uno con mean + std sobre frames activos (post-VAD).
    """
    if y_preloaded is not None and sr_preloaded is not None:
        y, sr = y_preloaded, sr_preloaded
    else:
        y, sr = librosa.load(path, sr=None, mono=True)

    if y.size == 0:
        return np.zeros(N_FEATURES, dtype=np.float32)

    hop_length = 512
    n_fft = 2048

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20,
                                 n_fft=n_fft, hop_length=hop_length)
    delta_mfcc = librosa.feature.delta(mfcc)
    delta2_mfcc = librosa.feature.delta(mfcc, order=2)

    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=n_fft,
                                                  hop_length=hop_length)
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, n_fft=n_fft,
                                                    hop_length=hop_length)
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, n_fft=n_fft,
                                                hop_length=hop_length)
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=n_fft,
                                              hop_length=hop_length)
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop_length)

    all_features = np.vstack([
        mfcc, delta_mfcc, delta2_mfcc,
        centroid, bandwidth, rolloff, zcr, rms,
    ])

    if apply_vad:
        mask = vad_mask(y, sr, frame_length=n_fft, hop_length=hop_length)
        min_len = min(all_features.shape[1], len(mask))
        all_features = all_features[:, :min_len]
        mask = mask[:min_len]
        if mask.sum() > 0:
            all_features = all_features[:, mask]

    feat_mean = all_features.mean(axis=1)
    feat_std = all_features.std(axis=1)

    return np.concatenate([feat_mean, feat_std]).astype(np.float32)


# ---------------------------------------------------------------------------
# Data augmentation
# ---------------------------------------------------------------------------

def augment_with_ambient(
    illegal_paths: List[Path],
    legal_dir: Path,
    sr: int = 16000,
    snr_levels_db: List[float] = [0, 3, 5, 10, 15, 20],
    max_augmented_per_original: int = 4,
    seed: int = 42,
) -> List[Tuple[np.ndarray, int]]:
    """
    Mezcla cada muestra ilegal con sonidos de la carpeta legal/
    a distintos SNR para generar variantes augmentadas.
    """
    rng = np.random.RandomState(seed)

    ambient_files = list(legal_dir.glob("*.wav"))
    if not ambient_files:
        print("[WARN] No se encontraron archivos en legal/ para augmentation.")
        return []

    print(f"[INFO] Augmentation: {len(illegal_paths)} ilegales x "
          f"hasta {max_augmented_per_original} variantes")
    print(f"[INFO] Pool de archivos ambient (legal/): {len(ambient_files)}")

    augmented = []

    for ill_path in illegal_paths:
        y_ill, _ = librosa.load(ill_path, sr=sr, mono=True)
        if y_ill.size == 0:
            continue

        n_variants = min(max_augmented_per_original, len(snr_levels_db))
        chosen_snrs = rng.choice(snr_levels_db, size=n_variants, replace=False)

        for snr_db in chosen_snrs:
            amb_path = ambient_files[rng.randint(len(ambient_files))]
            y_amb, _ = librosa.load(amb_path, sr=sr, mono=True)
            if y_amb.size == 0:
                continue

            if len(y_amb) < len(y_ill):
                y_amb = np.tile(y_amb, (len(y_ill) // len(y_amb)) + 1)
            y_amb = y_amb[:len(y_ill)]

            rms_ill = np.sqrt(np.mean(y_ill ** 2)) + 1e-10
            rms_amb = np.sqrt(np.mean(y_amb ** 2)) + 1e-10
            target_rms_amb = rms_ill / (10 ** (snr_db / 20.0))
            gain = target_rms_amb / rms_amb

            y_mix = y_ill + gain * y_amb
            peak = np.max(np.abs(y_mix))
            if peak > 1.0:
                y_mix = y_mix / peak

            augmented.append((y_mix, sr))

    print(f"[INFO] Augmentation generó {len(augmented)} muestras adicionales.")
    return augmented


# ---------------------------------------------------------------------------
# Listado y split
# ---------------------------------------------------------------------------

def list_audio_files(audio_root: Path) -> List[Tuple[Path, str]]:
    """
    Lee audio_root/illegal/*.wav y audio_root/legal/*.wav.
    """
    pairs: List[Tuple[Path, str]] = []

    for label in [LABEL_ILLEGAL, LABEL_LEGAL]:
        label_dir = audio_root / label
        if not label_dir.exists():
            print(f"[WARN] No existe: {label_dir}")
            continue
        wavs = list(label_dir.glob("*.wav"))
        for w in wavs:
            pairs.append((w, label))

    if not pairs:
        raise RuntimeError(f"No se encontraron .wav en {audio_root}")

    n_ill = sum(1 for _, l in pairs if l == LABEL_ILLEGAL)
    n_leg = sum(1 for _, l in pairs if l == LABEL_LEGAL)

    print(f"[INFO] Total archivos: {len(pairs)}")
    print(f"       {LABEL_ILLEGAL}: {n_ill}")
    print(f"       {LABEL_LEGAL}:   {n_leg}")
    if n_ill > 0:
        print(f"       Ratio legal/illegal: {n_leg / n_ill:.1f}:1")

    return pairs


def split_dataset(
    pairs: List[Tuple[Path, str]],
    train_size: float, val_size: float, test_size: float,
    seed: int = 42,
) -> Dict[str, List[Tuple[Path, str]]]:

    labels = [lbl for _, lbl in pairs]
    stratify = labels if len(set(labels)) > 1 else None

    remaining, test = train_test_split(
        pairs, test_size=test_size, random_state=seed, stratify=stratify,
    )
    splits = {"test": test}

    if val_size > 0.0:
        val_ratio = val_size / (train_size + val_size)
        labels_rem = [lbl for _, lbl in remaining]
        stratify_rem = labels_rem if len(set(labels_rem)) > 1 else None
        train, val = train_test_split(
            remaining, test_size=val_ratio, random_state=seed,
            stratify=stratify_rem,
        )
        splits["train"] = train
        splits["val"] = val
    else:
        splits["train"] = remaining
        splits["val"] = []

    print("[INFO] Split:")
    for name in ["train", "val", "test"]:
        items = splits.get(name, [])
        n_ill = sum(1 for _, l in items if l == LABEL_ILLEGAL)
        n_leg = sum(1 for _, l in items if l == LABEL_LEGAL)
        print(f"  {name}: {len(items)} "
              f"({LABEL_ILLEGAL}={n_ill}, {LABEL_LEGAL}={n_leg})")

    return splits


def copy_splits(splits: Dict[str, List[Tuple[Path, str]]],
                dataset_root: Path) -> None:
    for split_name, items in splits.items():
        for src_path, label in items:
            dest_dir = dataset_root / split_name / label
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_dir / src_path.name)
    print(f"[INFO] Dataset creado en: {dataset_root}")


# ---------------------------------------------------------------------------
# Build features
# ---------------------------------------------------------------------------

def build_features_and_labels(
    dataset_root: Path,
    split_name: str,
    apply_vad: bool = True,
    augment: bool = False,
    sr: int = 16000,
) -> Tuple[np.ndarray, np.ndarray]:

    split_root = dataset_root / split_name
    if not split_root.exists():
        raise RuntimeError(f"No existe: {split_root}")

    X_list = []
    y_list = []
    illegal_paths = []

    for wav_path in split_root.rglob("*.wav"):
        label = wav_path.parent.name
        feat = extract_features(path=wav_path, apply_vad=apply_vad)
        X_list.append(feat)
        y_list.append(label)

        if label == LABEL_ILLEGAL:
            illegal_paths.append(wav_path)

    if not X_list:
        raise RuntimeError(f"No se encontraron .wav en {split_root}")

    # Augmentation solo en train (moderada: ~2x illegal, no más)
    if augment and illegal_paths:
        legal_dir = split_root / LABEL_LEGAL
        if legal_dir.exists():
            aug_samples = augment_with_ambient(
                illegal_paths, legal_dir, sr=sr,
                snr_levels_db=[3, 6, 10, 15],
                max_augmented_per_original=2,
            )
            for y_audio, sr_audio in aug_samples:
                feat = extract_features(
                    y_preloaded=y_audio, sr_preloaded=sr_audio,
                    apply_vad=apply_vad,
                )
                X_list.append(feat)
                y_list.append(LABEL_ILLEGAL)

    X = np.stack(X_list, axis=0)
    y = np.array(y_list)

    unique, counts = np.unique(y, return_counts=True)
    print(f"[INFO] Split '{split_name}': {X.shape[0]} muestras, "
          f"{X.shape[1]} features")
    for u, c in zip(unique, counts):
        print(f"       {u}: {c}")

    return X, y


# ---------------------------------------------------------------------------
# Entrenamiento
# ---------------------------------------------------------------------------

def train_and_evaluate(
    dataset_root: Path,
    use_validation: bool = True,
    model_output: Optional[Path] = None,
    apply_vad: bool = True,
    augment_train: bool = True,
    do_grid_search: bool = True,
) -> None:

    X_train, y_train = build_features_and_labels(
        dataset_root, "train",
        apply_vad=apply_vad, augment=augment_train,
    )

    if do_grid_search:
        print("\n[INFO] Ejecutando GridSearchCV...")
        param_grid = {
            "svc__C": [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0],
            "svc__gamma": ["scale", "auto", 0.0001, 0.001, 0.01, 0.1],
            "svc__class_weight": ["balanced",
                                {LABEL_ILLEGAL: 5, LABEL_LEGAL: 1},
                                {LABEL_ILLEGAL: 8, LABEL_LEGAL: 1},
                                {LABEL_ILLEGAL: 12, LABEL_LEGAL: 1}],
        }

        pipe = make_pipeline(
            StandardScaler(),
            SVC(kernel="rbf", random_state=42),
        )

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        grid = GridSearchCV(
            pipe, param_grid, cv=cv,
            scoring=make_scorer(f1_score, pos_label="illegal"),
            n_jobs=-1, verbose=1,
            error_score=0.0,  # evita NaN: si un fold falla, cuenta como 0
        )
        grid.fit(X_train, y_train)

        print(f"\n[INFO] Mejores hiperparámetros: {grid.best_params_}")
        print(f"[INFO] Mejor F1 (CV): {grid.best_score_:.4f}")

        # Top 5 combinaciones
        results = grid.cv_results_
        sorted_idx = np.argsort(results["mean_test_score"])[::-1]
        print("\n[INFO] Top 5 combinaciones:")
        for i in sorted_idx[:5]:
            print(f"  F1={results['mean_test_score'][i]:.4f} "
                  f"(±{results['std_test_score'][i]:.4f}) "
                  f"params={results['params'][i]}")

        clf = grid.best_estimator_
    else:
        clf = make_pipeline(
            StandardScaler(),
            SVC(kernel="rbf", C=10.0, gamma="scale",
                class_weight="balanced", random_state=42),
        )
        clf.fit(X_train, y_train)

    svc = clf.named_steps["svc"]
    sv_ratio = svc.n_support_.sum() / X_train.shape[0]
    print(f"\n[INFO] Entrenamiento completo.")
    print(f"[INFO] Vectores soporte: {svc.n_support_} "
          f"(total: {svc.n_support_.sum()} de {X_train.shape[0]}, "
          f"{sv_ratio:.1%})")
    if sv_ratio > 0.5:
        print(f"[WARN] Ratio de vectores soporte muy alto ({sv_ratio:.1%}). "
              f"El modelo puede no estar generalizando bien.")

    # --- Helper de evaluación ---
    def evaluate(X, y_true, name):
        y_pred = clf.predict(X)
        acc = accuracy_score(y_true, y_pred)
        f1 = f1_score(y_true, y_pred, pos_label=LABEL_ILLEGAL)
        prec = precision_score(y_true, y_pred, pos_label=LABEL_ILLEGAL,
                               zero_division=0)
        rec = recall_score(y_true, y_pred, pos_label=LABEL_ILLEGAL,
                           zero_division=0)

        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"{'='*50}")
        print(f"  Accuracy:             {acc:.4f}")
        print(f"  F1 (illegal):         {f1:.4f}")
        print(f"  Precision (illegal):  {prec:.4f}")
        print(f"  Recall (illegal):     {rec:.4f}")
        print(f"\n{classification_report(y_true, y_pred, zero_division=0)}")

        cm = confusion_matrix(y_true, y_pred,
                              labels=[LABEL_ILLEGAL, LABEL_LEGAL])
        tp, fn = cm[0]
        fp, tn = cm[1]
        print(f"  Matriz de confusión:")
        print(f"                    Pred illegal  Pred legal")
        print(f"  Real illegal      {tp:>8}      {fn:>8}")
        print(f"  Real legal        {fp:>8}      {tn:>8}")
        print(f"\n  Falsos negativos (illegal no detectado): {fn}")
        print(f"  Falsos positivos (legal como illegal):   {fp}")

    # Train (sanity check)
    y_pred_train = clf.predict(X_train)
    acc_train = accuracy_score(y_train, y_pred_train)
    f1_train = f1_score(y_train, y_pred_train, pos_label=LABEL_ILLEGAL)
    print(f"\n--- Train (sanity) ---")
    print(f"Accuracy: {acc_train:.4f}, F1: {f1_train:.4f}")

    # Validation
    if use_validation and (dataset_root / "val").exists():
        X_val, y_val = build_features_and_labels(
            dataset_root, "val", apply_vad=apply_vad, augment=False,
        )
        evaluate(X_val, y_val, "VALIDACIÓN")

    # Test
    X_test, y_test = build_features_and_labels(
        dataset_root, "test", apply_vad=apply_vad, augment=False,
    )
    evaluate(X_test, y_test, "TEST")

    # Guardar
    if model_output is not None and HAS_JOBLIB:
        model_output.parent.mkdir(parents=True, exist_ok=True)
        dump(clf, model_output)
        print(f"\n[INFO] Modelo guardado en: {model_output}")
    elif model_output is not None:
        print("[WARN] joblib no instalado, no se pudo guardar.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Entrena SVM binario (illegal vs legal) para detección de tala ilegal."
    )
    parser.add_argument(
        "--audio-root", type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "processed_dataset"),
    )
    parser.add_argument(
        "--dataset-root", type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "dataset_for_training"),
    )
    parser.add_argument("--train-size", type=float, default=0.7)
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--model-output", type=str,
        default=str(Path(__file__).resolve().parents[1] / "models" / "svm_illegal_logging_v3.joblib"),
    )
    parser.add_argument("--no-val", action="store_true")
    parser.add_argument("--no-augment", action="store_true")
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--no-grid-search", action="store_true")
    parser.add_argument(
        "--clean", action="store_true",
        help="Borra dataset_root antes de crear el nuevo split.",
    )

    args = parser.parse_args()

    audio_root = Path(args.audio_root).resolve()
    dataset_root = Path(args.dataset_root).resolve()

    if not audio_root.exists():
        raise SystemExit(f"[ERROR] No existe: {audio_root}")

    random.seed(args.seed)
    np.random.seed(args.seed)

    print(f"[INFO] audio_root:   {audio_root}")
    print(f"[INFO] dataset_root: {dataset_root}")
    print(f"[INFO] VAD:          {'ON' if not args.no_vad else 'OFF'}")
    print(f"[INFO] Augmentation: {'ON' if not args.no_augment else 'OFF'}")
    print(f"[INFO] GridSearch:   {'ON' if not args.no_grid_search else 'OFF'}")

    # 1) Listar archivos (ya vienen como illegal/ y legal/)
    pairs = list_audio_files(audio_root)

    # 2) Split
    splits = split_dataset(
        pairs,
        train_size=args.train_size,
        val_size=0.0 if args.no_val else args.val_size,
        test_size=args.test_size,
        seed=args.seed,
    )

    # 3) Limpiar y copiar
    if args.clean and dataset_root.exists():
        shutil.rmtree(dataset_root)
        print(f"[INFO] Limpiado: {dataset_root}")
    dataset_root.mkdir(parents=True, exist_ok=True)
    copy_splits(splits, dataset_root)

    # 4) Entrenar y evaluar
    train_and_evaluate(
        dataset_root,
        use_validation=not args.no_val,
        model_output=Path(args.model_output),
        apply_vad=not args.no_vad,
        augment_train=not args.no_augment,
        do_grid_search=not args.no_grid_search,
    )


if __name__ == "__main__":
    main()