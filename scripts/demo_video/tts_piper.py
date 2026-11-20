"""Synthesise narration.json with a local Piper neural voice (no network at run time).

    python -m piper.download_voices en_US-lessac-high --download-dir scripts/demo_video/voices
    python scripts/demo_video/tts_piper.py
"""
import json
import sys
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

HERE = Path(__file__).parent
VOICE = sys.argv[1] if len(sys.argv) > 1 else "en_US-lessac-high"
voice = PiperVoice.load(HERE / "voices" / f"{VOICE}.onnx")
cfg = SynthesisConfig(length_scale=1.08, noise_scale=0.6, noise_w_scale=0.7)
for i, line in enumerate(json.loads((HERE / "narration.json").read_text(encoding="utf-8"))):
    with wave.open(str(HERE / f"n{i:02d}.wav"), "wb") as wav:
        voice.synthesize_wav(line, wav, syn_config=cfg)
print("wrote", i + 1, "files")
