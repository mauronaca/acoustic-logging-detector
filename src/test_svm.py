import argparse
from pathlib import Path
from typing import Tuple

import numpy as np
import librosa
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

try:
    from joblib import load
except ImportError:
    load = None


LABEL_ILLEGAL = "illegal"
LABEL_LEGAL = "legal"


# ---------------------------------------------------------------------------
# VAD + Features (idénticas a v3)
# ---------------------------------------------------------------------------

def vad_mask(y, sr, frame_length=2048, hop_length=512,
             threshold_db=-40.0, min_active_frames=3):
    rms = librosa.feature.rms(y=y, frame_length=frame_length,
                               hop_length=hop_length)[0]
    if rms.max() < 1e-10:
        return np.ones(len(rms), dtype=bool)
    rms_db = librosa.amplitude_to_db(rms, ref=rms.max())
    mask = rms_db > threshold_db
    if mask.sum() < min_active_frames:
        return np.ones(len(rms), dtype=bool)
    return mask


def extract_features(path: Path, apply_vad: bool = True) -> np.ndarray:
    y, sr = librosa.load(path, sr=None, mono=True)

    if y.size == 0:
        return np.zeros(130, dtype=np.float32)

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
# Evaluación
# ---------------------------------------------------------------------------

def build_features_and_labels(dataset_root: Path, split_name: str,
                               apply_vad: bool = True):
    split_root = dataset_root / split_name
    if not split_root.exists():
        raise RuntimeError(f"No existe: {split_root}")

    X_list, y_list = [], []

    for wav_path in split_root.rglob("*.wav"):
        label = wav_path.parent.name
        feat = extract_features(wav_path, apply_vad=apply_vad)
        X_list.append(feat)
        y_list.append(label)

    if not X_list:
        raise RuntimeError(f"No se encontraron .wav en {split_root}")

    X = np.stack(X_list, axis=0)
    y = np.array(y_list)

    unique, counts = np.unique(y, return_counts=True)
    print(f"[INFO] Split '{split_name}': {X.shape[0]} muestras, "
          f"{X.shape[1]} features")
    for u, c in zip(unique, counts):
        print(f"       {u}: {c}")

    return X, y


def evaluate_model(model_path: Path, dataset_root: Path,
                   split_name: str, apply_vad: bool = True):
    if load is None:
        raise RuntimeError("joblib no instalado.")
    if not model_path.exists():
        raise RuntimeError(f"Modelo no existe: {model_path}")

    print(f"[INFO] Cargando modelo: {model_path}")
    clf = load(model_path)

    X, y_true = build_features_and_labels(dataset_root, split_name,
                                           apply_vad=apply_vad)

    y_pred = clf.predict(X)

    acc = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred, pos_label=LABEL_ILLEGAL)
    prec = precision_score(y_true, y_pred, pos_label=LABEL_ILLEGAL,
                           zero_division=0)
    rec = recall_score(y_true, y_pred, pos_label=LABEL_ILLEGAL,
                       zero_division=0)

    print(f"\n{'='*50}")
    print(f"  Evaluación en split: {split_name}")
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


def main():
    parser = argparse.ArgumentParser(
        description="Evalúa el modelo SVM binario v3."
    )
    parser.add_argument(
        "--dataset-root", type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "dataset_for_training"),
    )
    parser.add_argument("--split", type=str, default="test",
                        choices=["train", "val", "test"])
    parser.add_argument(
        "--model-path", type=str,
        default=str(Path(__file__).resolve().parents[1] / "models" / "svm_illegal_logging_v3.joblib"),
    )
    parser.add_argument("--no-vad", action="store_true")

    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    model_path = Path(args.model_path).resolve()

    if not dataset_root.exists():
        raise SystemExit(f"[ERROR] No existe: {dataset_root}")

    print(f"[INFO] dataset_root: {dataset_root}")
    print(f"[INFO] split:        {args.split}")
    print(f"[INFO] model_path:   {model_path}")
    print(f"[INFO] VAD:          {'ON' if not args.no_vad else 'OFF'}")

    evaluate_model(model_path, dataset_root, args.split,
                   apply_vad=not args.no_vad)


if __name__ == "__main__":
    main()