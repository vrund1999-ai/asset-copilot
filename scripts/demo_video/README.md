# Walkthrough video

Builds `docs/demo/asset-copilot-walkthrough.mp4`: a screen recording of the real app with a visible
cursor and a synthetic voiceover. Nothing is mocked; the questions run against the live API and model.

Needs: the API and Streamlit running, Chrome, `ffmpeg` on PATH, Windows (the voice is the built-in
Windows speech engine), and `pip install playwright`.

```bash
powershell -File scripts/demo_video/tts.ps1 -Json scripts/demo_video/narration.json -OutDir scripts/demo_video
python scripts/demo_video/record.py     # records, writes raw/ and cues.json
python scripts/demo_video/mux.py        # adds the narration and encodes the MP4
```

`narration.json` is the script. Each clip starts when its step starts and the next step waits for it
to end, so edits to the text keep the audio and the actions in sync. The recording saves ratings
through the real feedback button, so delete the rows it creates in `feedback` afterwards.
