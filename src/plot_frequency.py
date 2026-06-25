"""
plot_frequency.py

Compara el espectro de frecuencia de muestras ilegales y legales,
mostrando tanto la versión original (organized_dataset) como la
procesada (processed_dataset) lado a lado.

Layout: 4 columnas x 3 filas
  Columnas: Illegal Original | Illegal Procesada | Legal Original | Legal Procesada
  Filas:    Forma de onda | Espectro FFT | Espectrograma Mel

Uso:
  python3 src/plot_frequency.py
  python3 src/plot_frequency.py --save plots/frequency_comparison.png
"""

import argparse
from pathlib import Path

import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt


def find_first_wav(directory: Path) -> Path:
    """Busca el primer .wav en un directorio."""
    wavs = sorted(directory.glob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"No se encontraron .wav en {directory}")
    return wavs[0]


def find_matching_wav(filename: str, search_dir: Path) -> Path:
    """
    Busca un .wav con el mismo nombre en otro directorio.
    Si no lo encuentra, devuelve el primero disponible.
    """
    match = search_dir / filename
    if match.exists():
        return match
    # Buscar por nombre parcial
    wavs = sorted(search_dir.glob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"No se encontraron .wav en {search_dir}")
    print(f"[WARN] No se encontró {filename} en {search_dir}, "
          f"usando {wavs[0].name}")
    return wavs[0]


def plot_column(axes, col, y, sr, title, color):
    """Dibuja los 3 gráficos (waveform, FFT, spectrogram) en una columna."""

    # 1. Forma de onda
    t = np.arange(len(y)) / sr
    axes[0, col].plot(t, y, color=color, linewidth=0.3)
    axes[0, col].set_title(title, fontsize=10, fontweight="bold")
    axes[0, col].set_xlabel("Tiempo (s)", fontsize=8)
    axes[0, col].set_ylabel("Amplitud", fontsize=8)
    axes[0, col].set_xlim([0, t[-1]])
    axes[0, col].set_ylim([-1.1, 1.1])  # Misma escala para comparar
    axes[0, col].tick_params(labelsize=7)

    # 2. Espectro de frecuencia (FFT)
    fft_vals = np.abs(np.fft.rfft(y))
    fft_db = 20 * np.log10(fft_vals + 1e-10)
    freqs = np.fft.rfftfreq(len(y), d=1.0 / sr)

    axes[1, col].plot(freqs, fft_db, color=color, linewidth=0.5)
    axes[1, col].set_title("Espectro FFT", fontsize=9)
    axes[1, col].set_xlabel("Frecuencia (Hz)", fontsize=8)
    axes[1, col].set_ylabel("Magnitud (dB)", fontsize=8)
    axes[1, col].set_xlim([0, sr / 2])
    axes[1, col].grid(True, alpha=0.3)
    axes[1, col].tick_params(labelsize=7)

    # 3. Espectrograma Mel
    S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128, n_fft=2048)
    S_db = librosa.power_to_db(S, ref=np.max)
    img = librosa.display.specshow(S_db, sr=sr, x_axis="time",
                                    y_axis="mel", ax=axes[2, col], cmap="magma")
    axes[2, col].set_title("Espectrograma Mel", fontsize=9)
    axes[2, col].tick_params(labelsize=7)

    return img


def plot_comparison(
    ill_raw_path: Path, ill_proc_path: Path,
    leg_raw_path: Path, leg_proc_path: Path,
    save_path: Path = None,
):
    # Cargar los 4 audios
    y_ill_raw, sr_ill_raw = librosa.load(ill_raw_path, sr=None, mono=True)
    y_ill_proc, sr_ill_proc = librosa.load(ill_proc_path, sr=None, mono=True)
    y_leg_raw, sr_leg_raw = librosa.load(leg_raw_path, sr=None, mono=True)
    y_leg_proc, sr_leg_proc = librosa.load(leg_proc_path, sr=None, mono=True)

    print(f"[INFO] Illegal original:   {ill_raw_path.name} "
          f"(sr={sr_ill_raw}, dur={len(y_ill_raw)/sr_ill_raw:.2f}s)")
    print(f"[INFO] Illegal procesada:  {ill_proc_path.name} "
          f"(sr={sr_ill_proc}, dur={len(y_ill_proc)/sr_ill_proc:.2f}s)")
    print(f"[INFO] Legal original:     {leg_raw_path.name} "
          f"(sr={sr_leg_raw}, dur={len(y_leg_raw)/sr_leg_raw:.2f}s)")
    print(f"[INFO] Legal procesada:    {leg_proc_path.name} "
          f"(sr={sr_leg_proc}, dur={len(y_leg_proc)/sr_leg_proc:.2f}s)")

    # Crear figura 3 filas x 4 columnas
    fig, axes = plt.subplots(3, 4, figsize=(22, 12))
    fig.suptitle(
        "Comparación espectral: Original vs Procesada  |  Illegal vs Legal",
        fontsize=16, fontweight="bold",
    )

    # Columna 0: Illegal original
    img0 = plot_column(axes, 0, y_ill_raw, sr_ill_raw,
                        f"ILLEGAL - Original\n({ill_raw_path.name})", "red")

    # Columna 1: Illegal procesada
    img1 = plot_column(axes, 1, y_ill_proc, sr_ill_proc,
                        f"ILLEGAL - Procesada\n({ill_proc_path.name})", "darkred")

    # Columna 2: Legal original
    img2 = plot_column(axes, 2, y_leg_raw, sr_leg_raw,
                        f"LEGAL - Original\n({leg_raw_path.name})", "green")

    # Columna 3: Legal procesada
    img3 = plot_column(axes, 3, y_leg_proc, sr_leg_proc,
                        f"LEGAL - Procesada\n({leg_proc_path.name})", "darkgreen")

    # Colorbars para los espectrogramas
    for col, img in enumerate([img0, img1, img2, img3]):
        fig.colorbar(img, ax=axes[2, col], format="%+2.0f dB", shrink=0.8)

    plt.tight_layout()

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[INFO] Gráfico guardado en: {save_path}")

    plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Compara espectro original vs procesado, illegal vs legal."
    )
    parser.add_argument(
        "--organized-root", type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "organized_dataset"),
        help="Directorio del dataset organizado (original).",
    )
    parser.add_argument(
        "--processed-root", type=str,
        default=str(Path(__file__).resolve().parents[1] / "dataset" / "processed_dataset"),
        help="Directorio del dataset procesado.",
    )
    parser.add_argument(
        "--save", type=str, default=None,
        help="Ruta para guardar el gráfico (e.g. plots/comparison.png).",
    )

    args = parser.parse_args()
    organized = Path(args.organized_root).resolve()
    processed = Path(args.processed_root).resolve()

    # Buscar muestras en organized_dataset
    ill_raw = find_first_wav(organized / "illegal")
    leg_raw = find_first_wav(organized / "legal")

    # Buscar las mismas muestras en processed_dataset
    ill_proc = find_matching_wav(ill_raw.name, processed / "illegal")
    leg_proc = find_matching_wav(leg_raw.name, processed / "legal")

    save_path = Path(args.save).resolve() if args.save else None
    plot_comparison(ill_raw, ill_proc, leg_raw, leg_proc, save_path=save_path)


if __name__ == "__main__":
    main()