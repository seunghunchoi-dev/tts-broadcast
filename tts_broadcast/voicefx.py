"""음성 후처리: 음높이(반음) · 빠르기 · 음량 (numpy, 오프라인).

엔진이 직접 지원하지 않는 조절을 합성된 음성에 적용합니다.
  - 음높이: 길이를 유지한 채 음높이만 변경 (WSOLA 늘이기 + 재표본화)
  - 음량  : 최대 음량을 -1dBFS 로 맞춘 뒤 배율 적용.
            100% 초과는 부드러운 압축으로 최대치는 유지하면서 체감 음량만 키움(찢어짐 방지)
"""
from __future__ import annotations

import wave
from pathlib import Path

PEAK = 0.89  # -1 dBFS


def ratio(semitones: float) -> float:
    return 2.0 ** (float(semitones) / 12.0)


def time_stretch(x, factor: float, sr: int):
    """길이를 factor 배로 (음높이 유지). WSOLA."""
    import numpy as np

    n = int(sr * 0.04) // 2 * 2
    if abs(factor - 1.0) < 1e-3 or len(x) < n * 2:
        return x
    hop = n // 2
    tol = n // 4
    win = np.hanning(n)
    out_len = int(len(x) * factor)
    xp = np.concatenate([np.zeros(tol), x, np.zeros(n * 2 + tol)])
    y = np.zeros(out_len + n)
    wsum = np.zeros(out_len + n)
    prev = None
    pos = 0
    while pos < out_len:
        nominal = int(round(pos / factor)) + tol
        if nominal + n + tol > len(xp):
            break
        if prev is None:
            best = nominal
        else:
            # 앞 조각의 자연스러운 다음 부분과 가장 닮은 위치를 찾아 이어 붙임 (2배 솎아서 계산)
            natural = xp[prev + hop: prev + hop + n: 2]
            seg = xp[nominal - tol: nominal + tol + n: 2]
            best = nominal - tol + 2 * int(np.argmax(np.correlate(seg, natural, "valid")))
        y[pos: pos + n] += xp[best: best + n] * win
        wsum[pos: pos + n] += win
        prev = best
        pos += hop
    y = y[:out_len]
    w = wsum[:out_len]
    return np.where(w > 1e-3, y / np.maximum(w, 1e-3), 0.0)


def resample(x, r: float):
    """r 배 빠르게 재생한 것과 같음 (음높이 r 배, 길이 1/r 배)."""
    import numpy as np

    if abs(r - 1.0) < 1e-4:
        return x
    return np.interp(np.arange(0, len(x) - 1, r), np.arange(len(x)), x)


def pitch_shift(x, semitones: float, sr: int):
    r = ratio(semitones)
    return resample(time_stretch(x, r, sr), r)


def loudness(x, volume: float):
    """최대 음량 정규화 + 배율 (100% 초과 = 부드러운 압축)."""
    import numpy as np

    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak < 1e-6:
        return x
    x = x / peak * PEAK
    v = max(0.0, float(volume))
    if v <= 1.0:
        return x * v
    drive = 1.0 + (v - 1.0) * 1.5
    return np.tanh(x * drive) / np.tanh(PEAK * drive) * PEAK


def read_wav(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("16bit WAV 만 지원")
        ch, sr = w.getnchannels(), w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def write_wav(path: Path, x, sr: int) -> None:
    import numpy as np

    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())


def process_file(path: Path, pitch: float = 0.0, volume: float | None = None) -> None:
    """WAV 파일에 음높이/음량 적용 (변경 없으면 그대로)."""
    if not pitch and volume is None:
        return
    x, sr = read_wav(path)
    if pitch:
        x = pitch_shift(x, pitch, sr)
    if volume is not None:
        x = loudness(x, volume)
    write_wav(path, x, sr)
