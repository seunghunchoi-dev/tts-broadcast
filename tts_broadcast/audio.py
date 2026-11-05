"""오디오 재생(winsound, 표준 라이브러리) 및 차임벨 합성.

차임벨은 외부 음원을 쓰지 않고 직접 합성하므로 저작권 문제 없이 상업적으로 사용할 수 있습니다.
(비브라폰/벨 계열 배음 + 타건음 + 음 겹침 여운 + 스테레오 잔향, 44.1kHz 16bit 스테레오)
고객사 고유 차임을 쓰려면 config.json 의 broadcast.chime_start_file / chime_end_file 에
WAV(PCM) 파일 경로를 지정하면 됩니다.
"""
from __future__ import annotations

import array
import math
import threading
import time
import wave
import winsound
from pathlib import Path

SAMPLE_RATE = 44100

# 음 높이(Hz), 음 간격(초), 마지막 음 여운(초)
CHIME_PRESETS = {
    "4tone_up":   {"notes": [392.00, 493.88, 587.33, 783.99], "gap": 0.44, "tail": 2.1},  # 솔시레솔 ↑
    "4tone_down": {"notes": [783.99, 587.33, 493.88, 392.00], "gap": 0.44, "tail": 2.1},  # 솔레시솔 ↓
    "3tone_up":   {"notes": [523.25, 659.25, 783.99], "gap": 0.42, "tail": 2.1},          # 도미솔 ↑
    "3tone_down": {"notes": [783.99, 659.25, 523.25], "gap": 0.42, "tail": 2.1},          # 솔미도 ↓
    "2tone":      {"notes": [659.25, 523.25], "gap": 0.65, "tail": 2.0},                  # 딩-동
}

# (배음 비율, 크기, 감쇠 배수) — 비브라폰/튜블러 벨 계열 음색
_PARTIALS = [(1.0, 1.0, 1.0), (2.0, 0.22, 1.7), (3.0, 0.08, 2.5), (4.0, 0.12, 2.2),
             (5.43, 0.03, 4.5), (8.93, 0.015, 8.0)]
_STRIKE = (12.6, 0.02, 45.0)  # 말렛 타건음 (아주 짧게)


def _note(freq: float, seconds: float) -> list[float]:
    n = int(SAMPLE_RATE * seconds)
    out = [0.0] * n
    attack = int(SAMPLE_RATE * 0.006)
    base_decay = 1.25 + freq / 1400.0  # 높은 음일수록 조금 빨리 사라짐
    two_pi_dt = 2.0 * math.pi / SAMPLE_RATE
    for ratio, amp, mult in _PARTIALS + [_STRIKE]:
        f = freq * ratio
        if f > SAMPLE_RATE / 2.2:
            continue
        w = two_pi_dt * f
        k = math.exp(-base_decay * mult / SAMPLE_RATE)
        env = amp
        sin = math.sin
        for i in range(n):
            out[i] += env * sin(w * i)
            env *= k
            if env < 1e-5:
                break
    # 부드러운 어택 + 은은한 트레몰로(비브라폰 모터 느낌)
    trem_w = two_pi_dt * 5.0
    for i in range(n):
        a = 0.5 - 0.5 * math.cos(math.pi * i / attack) if i < attack else 1.0
        out[i] *= a * (1.0 + 0.05 * math.sin(trem_w * i))
    return out


def _comb(x, delay, feedback, damp):
    buf = [0.0] * delay
    out = [0.0] * len(x)
    idx = 0
    store = 0.0
    for i, v in enumerate(x):
        y = buf[idx]
        store = y * (1.0 - damp) + store * damp
        buf[idx] = v + store * feedback
        idx += 1
        if idx == delay:
            idx = 0
        out[i] = y
    return out


def _allpass(x, delay, feedback=0.5):
    buf = [0.0] * delay
    out = [0.0] * len(x)
    idx = 0
    for i, v in enumerate(x):
        b = buf[idx]
        out[i] = b - v
        buf[idx] = v + b * feedback
        idx += 1
        if idx == delay:
            idx = 0
    return out


def _reverb(x, spread=0):
    combs = [_comb(x, d + spread, 0.80, 0.30) for d in (1116, 1277, 1422, 1617)]
    y = [sum(vals) * 0.25 for vals in zip(*combs)]
    for d in (556, 341):
        y = _allpass(y, d + spread)
    return y


def generate_chime(path: Path, preset: str = "4tone_up") -> Path:
    p = CHIME_PRESETS[preset]
    notes, gap, tail = p["notes"], p["gap"], p["tail"]
    pre = int(SAMPLE_RATE * 0.03)
    total = pre + int(SAMPLE_RATE * (gap * (len(notes) - 1) + tail + 0.3))
    left = [0.0] * total
    right = [0.0] * total
    for i, freq in enumerate(notes):
        sig = _note(freq, gap * (len(notes) - 1 - i) + tail)
        pan = -0.2 + 0.4 * i / max(1, len(notes) - 1)  # 음마다 좌→우로 살짝 이동
        gl, gr = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        start = pre + int(SAMPLE_RATE * gap * i)
        for j, v in enumerate(sig):
            left[start + j] += v * gl
            right[start + j] += v * gr
    rev_l = _reverb(left)
    rev_r = _reverb(right, spread=23)
    mix_l = [d * 0.82 + r * 0.30 for d, r in zip(left, rev_l)]
    mix_r = [d * 0.82 + r * 0.30 for d, r in zip(right, rev_r)]
    # 끝부분 페이드아웃 후 -3dBFS 로 정규화
    fade = int(SAMPLE_RATE * 0.5)
    for i in range(fade):
        g = 0.5 + 0.5 * math.cos(math.pi * i / fade)
        mix_l[total - fade + i] *= g
        mix_r[total - fade + i] *= g
    peak = max(max(map(abs, mix_l)), max(map(abs, mix_r))) or 1.0
    gain = 0.708 * 32767 / peak
    frames = array.array("h", [0]) * (total * 2)
    frames[0::2] = array.array("h", (int(v * gain) for v in mix_l))
    frames[1::2] = array.array("h", (int(v * gain) for v in mix_r))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames.tobytes())
    return path


# 긴급 경보음은 alerts.py (소방 사이렌·비상벨, numpy 로 합성)
from .alerts import ALERT_PRESETS, generate_alert  # noqa: E402,F401

BUILTIN_CHIMES = set(CHIME_PRESETS) | set(ALERT_PRESETS)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


_play_lock = threading.Lock()


def play_wav(path: Path, stop_event: threading.Event) -> bool:
    """WAV 재생. 끝까지 재생하면 True, stop_event 로 중단되면 False.
    출력 장치는 Windows 기본 재생 장치(방송 앰프에 연결된 장치로 지정)입니다."""
    duration = wav_duration(path)
    with _play_lock:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
        end = time.monotonic() + duration + 0.15
        while time.monotonic() < end:
            if stop_event.wait(0.05):
                winsound.PlaySound(None, 0)
                return False
    return True


if __name__ == "__main__":
    # python -m tts_broadcast.audio  → assets/chimes 에 기본 차임 생성
    out_dir = Path(__file__).resolve().parent.parent / "assets" / "chimes"
    for name in CHIME_PRESETS:
        t = time.time()
        generate_chime(out_dir / f"{name}.wav", name)
        print(f"{name}.wav  ({time.time() - t:.1f}s)")
    for name in ALERT_PRESETS:
        t = time.time()
        generate_alert(out_dir / f"{name}.wav", name)
        print(f"{name}.wav  ({time.time() - t:.1f}s)")
