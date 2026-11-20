import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
cues = json.loads((HERE / "cues.json").read_text())["cues"]
vid = next((HERE / "raw").glob("*.webm"))
out = HERE.parents[1] / "docs" / "demo" / "asset-copilot-walkthrough.mp4"
out.parent.mkdir(parents=True, exist_ok=True)
trim = max(0.0, cues[0][1] - 1.0)
cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{trim:.2f}", "-i", str(vid)]
for i, _ in cues:
    cmd += ["-i", str(HERE / f"n{i:02d}.wav")]
parts = []
for k, (i, start) in enumerate(cues, start=1):
    ms = int((start - trim) * 1000)
    parts.append(f"[{k}:a]adelay={ms}|{ms},volume=1.0[a{k}]")
mix = "".join(f"[a{k}]" for k in range(1, len(cues) + 1))
parts.append(f"{mix}amix=inputs={len(cues)}:normalize=0[aout]")
cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-crf", "27", "-preset", "slow", "-pix_fmt", "yuv420p", "-r", "25",
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-movflags", "+faststart", "-shortest", str(out)]
subprocess.run(cmd, check=True)
print(out, out.stat().st_size // 1024, "KB")
