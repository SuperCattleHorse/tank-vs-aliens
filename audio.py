"""Sound helper -- loads and plays the locally generated .wav effects."""
from pathlib import Path

from ursina import Audio

SOUND_DIR = Path(__file__).resolve().parent / "assets" / "sounds"


def play_sound(name, volume=0.8, loop=False, autoplay=True, auto_destroy=True):
    """Play a sound effect by name (without extension). Returns the Audio or None."""
    f = SOUND_DIR / f"{name}.wav"
    if not f.exists():
        return None
    return Audio(
        f.as_posix(),
        volume=volume,
        loop=loop,
        autoplay=autoplay,
        auto_destroy=auto_destroy,
    )
