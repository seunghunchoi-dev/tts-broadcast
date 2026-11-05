"""긴급 방송 경보음 합성 (소방차 사이렌 · 화재 비상벨). 직접 합성한 소리라 저작권 문제 없음.

일상에서 듣는 사이렌에 가깝게 만드는 요소:
  - 전자 사이렌 신호(네모파)를 나팔형 사이렌 스피커에 통과시킨 음색
    (500Hz 아래·5kHz 위는 약하고 1.5kHz·2.7kHz 부근이 강한 '앵~' 소리)
  - 실제와 같은 속도: 웨일은 한 번 오르내리는 데 약 3.5초, 옐프는 초당 약 3.5회
  - 사이렌은 한 대, 길거리에서 조금 떨어져 듣는 거리감(고음 감소)과 건물 반사 메아리
민방위 경보(공습·재난)와 비슷한 소리는 실제 경보로 오인될 수 있어 만들지 않습니다.
실제 사이렌을 직접 녹음한 WAV 가 있으면 assets\\chimes 에 넣고 [시설 설정]에서 고를 수 있습니다.
"""
from __future__ import annotations

import wave
from pathlib import Path

SR = 44100
PEAK = 0.89  # -1 dBFS


def _np():
    import numpy as np
    return np


def _square(freq):
    """음높이가 시간마다 바뀌는 네모파 (배음을 나이퀴스트 아래로 제한)."""
    np = _np()
    phase = np.cumsum(2 * np.pi * freq / SR)
    out = np.zeros_like(freq)
    limit = SR / 2.2
    for k in range(1, 40, 2):
        mask = (freq * k) < limit
        if not mask.any():
            break
        out += np.sin(k * phase) * mask / k
    return np.tanh(out * 1.3)  # 모서리를 살짝 둥글게 (실제 앰프 출력처럼)


def _horn(x):
    """나팔형 사이렌 스피커 + 조금 떨어진 거리의 주파수 특성 (FFT 필터)."""
    np = _np()
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    hp = (f / 500.0) ** 4 / (1 + (f / 500.0) ** 4)            # 500Hz 아래 약하게
    lp = 1 / (1 + (f / 4200.0) ** 4)                           # 고음은 거리에서 감소
    res = 1 + 1.4 * np.exp(-((f - 1500) / 450) ** 2) + 0.8 * np.exp(-((f - 2700) / 550) ** 2)
    return np.fft.irfft(spec * hp * lp * res, len(x))


def _street(x, seed: int):
    """길거리 메아리: 건물에 반사된 늦은 소리 몇 개 + 짧은 잔향."""
    np = _np()
    rng = np.random.default_rng(seed)
    tail = int(SR * 0.9)
    out = np.concatenate([x, np.zeros(tail)])
    for delay, gain in ((0.083, 0.32), (0.157, 0.22), (0.241, 0.14), (0.37, 0.08)):
        d = int(SR * (delay + rng.uniform(-0.006, 0.006)))
        out[d:d + len(x)] += x * gain
    n = int(SR * 0.7)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * 0.15))
    ir /= np.sqrt((ir ** 2).sum())
    size = len(out) + n
    wet = np.fft.irfft(np.fft.rfft(out, size) * np.fft.rfft(ir, size), size)[: len(out)]
    return out + wet * 0.12


def _env(n: int, attack: float, release: float):
    np = _np()
    e = np.ones(n)
    a, r = int(SR * attack), int(SR * release)
    e[:a] = np.linspace(0, 1, a)
    e[-r:] = np.linspace(1, 0, r)
    return e


def _render(path: Path, freq, attack=0.08, release=0.35) -> Path:
    np = _np()
    x = _horn(_square(freq)) * _env(len(freq), attack, release)
    left, right = _street(x, 1), _street(x, 2)  # 좌우 메아리를 조금 다르게 → 넓게
    return _write(path, left, right)


def _write(path: Path, left, right) -> Path:
    np = _np()
    n = max(len(left), len(right))
    left, right = np.pad(left, (0, n - len(left))), np.pad(right, (0, n - len(right)))
    fade = int(SR * 0.1)
    left[-fade:] *= np.linspace(1, 0, fade)
    right[-fade:] *= np.linspace(1, 0, fade)
    peak = max(np.abs(left).max(), np.abs(right).max()) or 1.0
    st = np.empty(n * 2)
    st[0::2], st[1::2] = left / peak * PEAK, right / peak * PEAK
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    return path


def _wail_cycle(lo, hi, rise, fall):
    """한 번 '애애앵~' : 비교적 빨리 올라가고 천천히 내려옴."""
    np = _np()
    r = np.arange(int(SR * rise)) / (SR * rise)
    up = lo + (hi - lo) * (1 - (1 - r) ** 2)
    d = np.arange(int(SR * fall)) / (SR * fall)
    down = hi - (hi - lo) * d ** 1.6
    return np.concatenate([up, down])


def fire_siren(path: Path) -> Path:
    """소방차 사이렌 (웨일): '애애앵~ 애애앵~' 천천히 오르내리기 2번."""
    np = _np()
    lo, hi = 640.0, 1380.0
    cyc = _wail_cycle(lo, hi, 1.35, 2.15)
    return _render(path, np.concatenate([cyc, cyc]), attack=0.15, release=0.4)


def fire_yelp(path: Path) -> Path:
    """소방차 사이렌 (옐프): 교차로를 지날 때 쓰는 빠른 '위용위용위용'."""
    np = _np()
    lo, hi, rate, seconds = 700.0, 1400.0, 3.4, 4.2
    t = np.arange(int(SR * seconds)) / SR
    return _render(path, _yelp_freq(t, lo, hi, rate), attack=0.05, release=0.3)


def _yelp_freq(t, lo, hi, rate):
    """빠르게 오르고(조금 빠름) 내려오는(조금 느림) 한 번의 '위용'."""
    np = _np()
    x = (t * rate) % 1.0
    up = np.clip(x / 0.5, 0, 1) ** 0.8
    down = np.clip((x - 0.5) / 0.5, 0, 1) ** 1.2
    return np.where(x < 0.5, lo + (hi - lo) * up, hi - (hi - lo) * down)


def wail_yelp(path: Path) -> Path:
    """웨일 → 옐프: 한 번 '애애앵~' 한 뒤 빠른 '위용위용'으로 바뀜 (출동 중 소방차)."""
    np = _np()
    lo, hi = 640.0, 1380.0
    wail = _wail_cycle(lo, hi, 1.35, 1.2)[: int(SR * 1.9)]
    yelp = _yelp_freq(np.arange(int(SR * 3.0)) / SR, 700.0, 1400.0, 3.4)
    # 웨일이 내려오던 음높이에서 옐프로 자연스럽게 이어지도록 짧게 섞음
    k = int(SR * 0.08)
    yelp[:k] = np.linspace(wail[-1], yelp[k], k)
    return _render(path, np.concatenate([wail, yelp]), attack=0.12, release=0.3)


def hi_lo(path: Path) -> Path:
    """구급차형 '삐뽀삐뽀' (하이-로)."""
    np = _np()
    hi, lo, half, cycles = 960.0, 770.0, 0.42, 5
    t = np.arange(int(SR * half * 2 * cycles)) / SR
    freq = np.where((t % (half * 2)) < half, hi, lo)
    k = int(SR * 0.012)  # 음 바뀔 때 '딱' 소리 없게 아주 짧게 이어 줌
    freq = np.convolve(freq, np.ones(k) / k, mode="same")
    return _render(path, freq, attack=0.03, release=0.3)


def fire_bell(path: Path) -> Path:
    """화재 비상벨: 전기 벨의 망치가 초당 18번 종을 때리는 '따르르릉' (아파트 화재경보 느낌)."""
    np = _np()
    seconds, rate = 3.8, 18.0
    n = int(SR * seconds)
    m = int(SR * 0.25)
    tt = np.arange(m) / SR
    strike = np.zeros(m)
    for ratio, amp, dec in ((1.0, 1.0, 9), (2.76, 0.6, 14), (5.40, 0.38, 22), (8.93, 0.22, 30),
                            (13.3, 0.12, 45)):
        strike += amp * np.sin(2 * np.pi * 1180 * ratio * tt) * np.exp(-dec * tt)
    k = int(SR * 0.002)
    strike[:k] *= np.linspace(0, 1, k)
    hits = np.zeros(n)
    rng = np.random.default_rng(3)
    for i in range(int(seconds * rate)):
        at = int((i / rate + rng.uniform(-0.002, 0.002)) * SR)  # 망치가 매번 조금씩 다르게 때림
        if 0 <= at < n:
            hits[at] = rng.uniform(0.8, 1.0)
    ring = np.fft.irfft(np.fft.rfft(hits, n + m) * np.fft.rfft(strike, n + m), n + m)[:n]
    t = np.arange(n) / SR
    clatter = rng.standard_normal(n) * 0.08 * (0.5 + 0.5 * np.sin(2 * np.pi * rate * t) ** 8)
    x = np.tanh((ring + clatter) * 1.8) * _env(n, 0.005, 0.05)
    return _write(path, _street(x, 3), _street(x, 4))


# 파일 이름 → (만드는 함수, 화면 표시 이름)
ALERT_PRESETS = {
    "emergency": (fire_siren, "소방차 사이렌 (애애앵~)"),
    "emergency_wailyelp": (wail_yelp, "소방차 출동 (애앵~ → 위용위용)"),
    "emergency_yelp": (fire_yelp, "빠른 사이렌 (위용위용)"),
    "emergency_hilo": (hi_lo, "구급차형 (삐뽀삐뽀)"),
    "emergency_bell": (fire_bell, "화재 비상벨 (따르르릉)"),
}


def generate_alert(path: Path, preset: str = "emergency") -> Path:
    return ALERT_PRESETS[preset][0](path)
