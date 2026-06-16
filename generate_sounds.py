"""
Procedurally generate all game sound effects using numpy.

Run this once to create the .wav files under assets/sounds/.
No internet download required -- everything is synthesized locally.

Usage:
    python generate_sounds.py
"""
import os
import wave
import numpy as np

SAMPLE_RATE = 44100
SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds")


def _envelope(n, attack=0.01, release=0.2, decay_rate=None):
    """Build a simple amplitude envelope of length n samples."""
    t = np.linspace(0, n / SAMPLE_RATE, n, endpoint=False)
    if decay_rate is not None:
        return np.exp(-t * decay_rate)
    env = np.ones(n)
    a = int(attack * SAMPLE_RATE)
    r = int(release * SAMPLE_RATE)
    if a > 0:
        env[:a] = np.linspace(0, 1, a)
    if r > 0:
        env[-r:] = np.linspace(1, 0, r)
    return env


def _write_wav(name, samples):
    """Normalize and write a mono 16-bit wav file."""
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    samples = np.asarray(samples, dtype=np.float64)
    peak = np.max(np.abs(samples)) or 1.0
    samples = samples / peak * 0.9
    samples = np.clip(samples, -1.0, 1.0)
    data = (samples * 32767).astype(np.int16)
    path = os.path.join(SOUNDS_DIR, name)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data.tobytes())
    print(f"  wrote {path}  ({len(samples)/SAMPLE_RATE:.2f}s)")


def _t(duration):
    n = int(duration * SAMPLE_RATE)
    return n, np.linspace(0, duration, n, endpoint=False)


def make_shoot():
    """Tank cannon fire: low boom with a quick noisy crack and pitch drop."""
    n, t = _t(0.35)
    freq = np.linspace(220, 70, n)          # pitch slides down
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    body = np.sin(phase) * np.exp(-t * 16)
    crack = (np.random.rand(n) * 2 - 1) * np.exp(-t * 45) * 0.6
    sub = np.sin(2 * np.pi * 45 * t) * np.exp(-t * 10) * 0.5
    return body * 0.7 + crack + sub


def make_explosion():
    """Enemy explosion: filtered noise burst with low rumble."""
    n, t = _t(0.8)
    noise = np.random.randn(n)
    # cheap low-pass via cumulative smoothing
    k = 40
    kernel = np.ones(k) / k
    noise = np.convolve(noise, kernel, mode="same")
    env = np.exp(-t * 6)
    rumble = np.sin(2 * np.pi * 55 * t) * np.exp(-t * 5) * 0.6
    crackle = (np.random.rand(n) * 2 - 1) * np.exp(-t * 12) * 0.3
    return noise * env * 0.8 + rumble + crackle


def make_hit():
    """Bullet hits enemy: short bright metallic 'ting'."""
    n, t = _t(0.18)
    s = np.sin(2 * np.pi * 950 * t) * np.exp(-t * 28)
    s += np.sin(2 * np.pi * 1500 * t) * np.exp(-t * 38) * 0.5
    return s


def make_player_hurt():
    """Player takes damage: low descending warning buzz."""
    n, t = _t(0.45)
    freq = np.linspace(420, 130, n)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    tone = np.sin(phase) * _envelope(n, attack=0.005, release=0.2)
    grit = np.sign(np.sin(phase * 0.5)) * 0.2 * np.exp(-t * 6)
    return tone + grit


def make_ui_click():
    """Menu button click: short clean blip."""
    n, t = _t(0.09)
    s = np.sin(2 * np.pi * 660 * t) * np.exp(-t * 40)
    return s


def make_game_over():
    """Game over: short descending three-note motif."""
    notes = [330, 247, 165]
    parts = []
    for f in notes:
        n, t = _t(0.32)
        tone = np.sin(2 * np.pi * f * t) * _envelope(n, attack=0.01, release=0.18)
        tone += np.sin(2 * np.pi * f * 2 * t) * 0.25 * np.exp(-t * 6)
        parts.append(tone)
    return np.concatenate(parts)


def make_background():
    """Simple looping electronic bass groove for in-game music."""
    bpm = 100
    beat = 60.0 / bpm
    bass_seq = [55.0, 55.0, 73.42, 65.41]   # A1 A1 D2 C2 pattern
    bars = 4
    pattern = []
    for _ in range(bars):
        for f in bass_seq:
            n, t = _t(beat)
            env = _envelope(n, attack=0.01, release=beat * 0.4)
            note = np.sin(2 * np.pi * f * t) * env
            note += np.sin(2 * np.pi * f * 2 * t) * 0.3 * env
            # soft hi-hat tick at the start of each beat
            hat = (np.random.rand(n) * 2 - 1) * np.exp(-t * 60) * 0.12
            pattern.append(note * 0.6 + hat)
    track = np.concatenate(pattern)
    # gentle pulsing pad underneath
    n = len(track)
    t = np.linspace(0, n / SAMPLE_RATE, n, endpoint=False)
    pad = np.sin(2 * np.pi * 110 * t) * (0.12 + 0.06 * np.sin(2 * np.pi * 0.5 * t))
    return track + pad


def main():
    np.random.seed(7)
    print(f"Generating sound effects into: {SOUNDS_DIR}")
    _write_wav("shoot.wav", make_shoot())
    _write_wav("explosion.wav", make_explosion())
    _write_wav("hit.wav", make_hit())
    _write_wav("player_hurt.wav", make_player_hurt())
    _write_wav("ui_click.wav", make_ui_click())
    _write_wav("game_over.wav", make_game_over())
    _write_wav("background.wav", make_background())
    print("Done. All sound effects generated.")


if __name__ == "__main__":
    main()
