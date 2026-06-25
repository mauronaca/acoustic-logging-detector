from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, Optional, Tuple

import librosa
import soundfile as sf
import numpy as np
from scipy import signal

def to_mono(y: np.ndarray) -> np.ndarray:
    """
    Convert audio to mono.

    Accepts:
      - shape (n_samples,) mono
      - shape (n_samples, n_channels) (soundfile style)
      - shape (n_channels, n_samples) (sometimes happens)

    Returns:
      - shape (n_samples,) float32
    """
    y = np.asarray(y)

    if y.ndim == 1:
        mono = y
    elif y.ndim == 2:
        # Heuristic: if first dim is small (<=8) treat as (channels, samples)
        if y.shape[0] <= 8 and y.shape[1] > y.shape[0]:
            mono = np.mean(y, axis=0)
        else:
            mono = np.mean(y, axis=1)
    else:
        raise ValueError(f"Unsupported audio shape: {y.shape}")

    return mono.astype(np.float32, copy=False)

def resample_audio(
    y: np.ndarray,
    orig_sr: int,
    target_sr: int,
    *,
    res_type: str = "soxr_hq",
) -> np.ndarray:
    """
    Resample to target_sr using librosa (soxr if available).

    res_type examples: "soxr_hq", "soxr_vhq", "kaiser_best", "kaiser_fast"
    """
    if orig_sr == target_sr:
        return y.astype(np.float32, copy=False)

    y_rs = librosa.resample(y.astype(np.float32, copy=False), orig_sr=orig_sr, target_sr=target_sr, res_type=res_type)
    return y_rs.astype(np.float32, copy=False)

def highpass_filter(
    y: np.ndarray,
    sr: int,
    cutoff_hz: float = 100.0,
    *,
    order: int = 4,
    method: Literal["sosfiltfilt", "sosfilt"] = "sosfiltfilt",
) -> np.ndarray:
    """
    Butterworth high-pass.

    - sosfiltfilt: zero-phase (recommended offline)
    - sosfilt: causal-ish (streaming-ish, but you should manage filter state for true streaming)
    """
    if cutoff_hz <= 0:
        return y.astype(np.float32, copy=False)

    nyq = 0.5 * sr
    wn = cutoff_hz / nyq
    if wn >= 1.0:
        raise ValueError("cutoff_hz too high for given sr")

    sos = signal.butter(order, wn, btype="highpass", output="sos")
    y = y.astype(np.float32, copy=False)

    if method == "sosfiltfilt":
        out = signal.sosfiltfilt(sos, y)
    else:
        out = signal.sosfilt(sos, y)

    return out.astype(np.float32, copy=False)

NormalizeMethod = Literal[
    "none",
    "peak",
    "rms",
    "percentile_peak",
    "lufs_like",  # simple approximation, not ITU-R BS.1770
]

def normalize_audio(
    y: np.ndarray,
    *,
    method: NormalizeMethod = "rms",
    peak_dbfs: float = -1.0,
    target_rms: float = 0.1,
    percentile: float = 99.0,
    eps: float = 1e-9,
) -> np.ndarray:
    """
    Normalize signal amplitude.

    Methods:
      - none: no normalization
      - peak: scale so max(|y|) == 10^(peak_dbfs/20)
      - percentile_peak: scale so percentile(|y|, p) == 10^(peak_dbfs/20)
      - rms: scale so RMS == target_rms
      - lufs_like: rough loudness normalization using RMS with a mild highpass-ish weighting (approx)

    Returns float32.
    """
    y = y.astype(np.float32, copy=False)

    if method == "none":
        return y

    if method == "peak":
        peak = float(np.max(np.abs(y)))
        if peak < eps:
            return y
        target_peak = 10 ** (peak_dbfs / 20.0)
        return (y * (target_peak / peak)).astype(np.float32, copy=False)

    if method == "percentile_peak":
        p = float(np.percentile(np.abs(y), percentile))
        if p < eps:
            return y
        target_peak = 10 ** (peak_dbfs / 20.0)
        return (y * (target_peak / p)).astype(np.float32, copy=False)

    if method == "rms":
        rms = float(np.sqrt(np.mean(y * y)))
        if rms < eps:
            return y
        return (y * (target_rms / rms)).astype(np.float32, copy=False)

    if method == "lufs_like":
        # Not true LUFS. Just a better-than-nothing proxy: remove DC and apply a gentle pre-emphasis,
        # then normalize RMS on that weighted signal.
        y0 = y - float(np.mean(y))
        y_w = signal.lfilter([1.0, -0.97], [1.0], y0).astype(np.float32, copy=False)  # pre-emphasis
        rms = float(np.sqrt(np.mean(y_w * y_w)))
        if rms < eps:
            return y
        # scale original (unweighted) y0 by ratio
        return (y0 * (target_rms / rms)).astype(np.float32, copy=False)

    raise ValueError(f"Unknown normalization method: {method}")

DenoiseMethod = Literal[
    "none",
    "wiener",
    "bandpass",
    "band_limit",
    "pcen",          # produces a time-domain signal approximation (see note) OR feature-domain if you choose
    "log_floor_spec" # spectral log+floor then inverse (approx)
]


def _bandpass_sos(sr: int, low_hz: float, high_hz: float, order: int = 4):
    nyq = 0.5 * sr
    low = low_hz / nyq
    high = high_hz / nyq
    if not (0 < low < high < 1):
        raise ValueError("Invalid band limits for given sr")
    return signal.butter(order, [low, high], btype="bandpass", output="sos")


def denoise_audio(
    y: np.ndarray,
    sr: int,
    *,
    method: DenoiseMethod = "none",
    # Wiener
    wiener_mysize: Optional[int] = None,  # e.g., 29, 51... if None, scipy chooses
    # Band filtering
    band_low_hz: float = 150.0,
    band_high_hz: float = 8000.0,
    filt_order: int = 4,
    # Spectral transforms
    n_fft: int = 1024,
    hop_length: int = 256,
    win_length: Optional[int] = None,
    log_floor_db: float = -80.0,
    # PCEN params (feature-domain)
    pcen_time_constant: float = 0.4,
    pcen_gain: float = 0.98,
    pcen_bias: float = 2.0,
    pcen_power: float = 0.5,
    pcen_eps: float = 1e-6,
) -> np.ndarray:
    """
    Denoise/conditioning block.

    IMPORTANT:
    - Some "denoise" options operate naturally in the spectral/feature domain (e.g., PCEN).
    - Here we keep the function returning a time-domain signal for a uniform pipeline,
      but note that for ML it's often better to apply PCEN directly to mel spectrogram features.
    """
    y = y.astype(np.float32, copy=False)

    if method == "none":
        return y

    if method == "wiener":
        # Wiener filter in time domain (simple, can smear transients a bit)
        return signal.wiener(y, mysize=wiener_mysize).astype(np.float32, copy=False)

    if method in ("bandpass", "band_limit"):
        # band_limit is same idea: remove very low & very high; bandpass is explicit
        high = min(band_high_hz, 0.49 * sr)  # safety
        low = max(band_low_hz, 1.0)
        sos = _bandpass_sos(sr, low, high, order=filt_order)
        return signal.sosfiltfilt(sos, y).astype(np.float32, copy=False)

    if method == "log_floor_spec":
        # STFT -> mag -> dB -> floor -> reconstruct magnitude (phase kept) -> ISTFT
        S = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, win_length=win_length)
        mag = np.abs(S)
        phase = np.exp(1j * np.angle(S))

        mag_db = librosa.amplitude_to_db(mag, ref=np.max)
        mag_db = np.maximum(mag_db, log_floor_db)
        mag2 = librosa.db_to_amplitude(mag_db, ref=1.0)

        S2 = mag2 * phase
        y2 = librosa.istft(S2, hop_length=hop_length, win_length=win_length, length=len(y))
        return y2.astype(np.float32, copy=False)

    if method == "pcen":
        # Apply PCEN on mel spectrogram, then roughly invert back to waveform (approx).
        # For ML: usually you should STOP here and feed PCEN-mel as features (step 8).
        mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length, n_mels=64, power=1.0)
        pcen = librosa.pcen(
            mel,
            time_constant=pcen_time_constant,
            gain=pcen_gain,
            bias=pcen_bias,
            power=pcen_power,
            eps=pcen_eps,
        )
        # Inversion is approximate (mel inversion + Griffin-Lim)
        y2 = librosa.feature.inverse.mel_to_audio(
            pcen,
            sr=sr,
            n_fft=n_fft,
            hop_length=hop_length,
            win_length=win_length,
            power=1.0,
            n_iter=16,
        )
        # match length
        if len(y2) > len(y):
            y2 = y2[: len(y)]
        elif len(y2) < len(y):
            y2 = np.pad(y2, (0, len(y) - len(y2)))
        return y2.astype(np.float32, copy=False)

    raise ValueError(f"Unknown denoise method: {method}")

def process_audio(
    in_path: Path,
    out_path: Path,
    target_sr: int,
    *,
    apply_hp_filter: bool = True,
    apply_denoise: bool = True,
    apply_normalize: bool = True,
    hp_cutoff_hz: float = 100.0,
    denoise_method: Literal["none", "wiener", "bandpass", "band_limit", "pcen", "log_floor_spec"] = "pcen",
) -> None:
    """
    Carga un WAV, lo procesa (mono/resample/highpass/normalize/denoise) y lo guarda como WAV continuo.
    El ventaneo NO se guarda; se usa para features (entrenamiento/inferencia).
    """

    # Cargá sin forzar mono, así to_mono() controla todas las variantes
    y, sr = sf.read(in_path, always_2d=False)

    # 1) Mono (unifica forma)
    y = to_mono(y)

    # 2) Resample
    y = resample_audio(y, orig_sr=sr, target_sr=target_sr)

    # 3) Filtro pasa altos
    if apply_hp_filter:
        y = highpass_filter(y, sr=target_sr, cutoff_hz=hp_cutoff_hz)

    # 4) Normalización
    if apply_normalize:
        y = normalize_audio(y, method="rms")

    # 5) Denoise / conditioning
    if apply_denoise and denoise_method != "none":
        y = denoise_audio(y, sr=target_sr, method=denoise_method)

    # Guardar
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_path, y, target_sr)

    print(
        f"[INFO] {in_path} -> {out_path} "
        f"(sr {sr} -> {target_sr}, hp filter={apply_hp_filter}, denoise={apply_denoise}:{denoise_method}, normalize={apply_normalize})"
    )


def process_dataset(in_root: Path, out_root: Path, target_sr: int,
                    apply_hp_filter: bool = True,
                    apply_denoise: bool = True,
                    apply_normalize: bool = True) -> None:
    """
    Recorre recursivamente in_root, busca todos los .wav y los guarda
    remuestreados en out_root respetando la estructura de subdirectorios.
    """
    wav_paths = list(in_root.rglob("*.wav"))
    if not wav_paths:
        print(f"[WARN] No se encontraron .wav en {in_root}")
        return

    print(f"[INFO] Encontrados {len(wav_paths)} archivos .wav en {in_root}")
    print(f"[INFO] Frecuencia de destino: {target_sr} Hz")
    print(f"[INFO] Filtro pasa altos: {'ON' if apply_hp_filter else 'OFF'}")
    print(f"[INFO] Filtrado de ruido: {'ON' if apply_denoise else 'OFF'}")
    print(f"[INFO] Normalización: {'ON' if apply_normalize else 'OFF'}")
    print(f"[INFO] Salida en: {out_root}")

    for in_path in wav_paths:
        rel_path = in_path.relative_to(in_root)
        out_path = out_root / rel_path

        try:
            process_audio(
                in_path,
                out_path,
                target_sr,
                apply_hp_filter=apply_hp_filter,
                apply_denoise=apply_denoise,
                apply_normalize=apply_normalize,
            )
        except Exception as e:
            print(f"[ERROR] Falló {in_path}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Downsample de WAVs con filtrado de ruido y normalización, "
            "manteniendo estructura de subcarpetas."
        )
    )

    parser.add_argument(
        "--in-root",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "organized_dataset"),
        help="Directorio raíz de entrada (default: ../dataset/organized_dataset)",
    )

    parser.add_argument(
        "--out-root",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "processed_dataset"),
        help="Directorio raíz de salida (default: ../dataset/processed_dataset)",
    )

    parser.add_argument(
        "--sr",
        type=int,
        default=16000,
        help="Frecuencia de muestreo objetivo (default: 16000 Hz)",
    )

    parser.add_argument(
        "--no-denoise",
        action="store_true",
        help="Desactiva el filtrado de ruido (por defecto está ACTIVADO).",
    )

    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Desactiva la normalización (por defecto está ACTIVADA).",
    )

    args = parser.parse_args()

    in_root = Path(args.in_root).resolve()
    out_root = Path(args.out_root).resolve()
    target_sr = args.sr
    apply_denoise = not args.no_denoise
    apply_normalize = not args.no_normalize

    if not in_root.exists():
        raise SystemExit(f"[ERROR] El directorio de entrada no existe: {in_root}")

    out_root.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] in_root:  {in_root}")
    print(f"[INFO] out_root: {out_root}")

    process_dataset(
        in_root,
        out_root,
        target_sr,
        apply_denoise=apply_denoise,
        apply_normalize=apply_normalize,
    )


if __name__ == "__main__":
    main()
