# Walkthrough video

Builds `docs/demo/asset-copilot-walkthrough.mp4`: a screen recording of the real app with a visible
cursor and a synthetic neural voiceover (Piper, run locally). Nothing is mocked; the questions run against the live API and model.

Needs: the API and Streamlit running, Chrome, `ffmpeg` on PATH, and `pip install playwright piper-tts`.
The voice model (about 110 MB, from the public `rhasspy/piper-voices` repository) is downloaded once
and is not committed; speech is generated locally with no network.

```bash
python -m piper.download_voices en_US-lessac-high --download-dir scripts/demo_video/voices
python scripts/demo_video/tts_piper.py   # narration.json -> n00.wav ...
python scripts/demo_video/record.py      # records, writes raw/ and cues.json
python scripts/demo_video/mux.py         # adds the narration and encodes the MP4
```

`narration.json` is the script. Each clip starts when its step starts and the next step waits for it
to end, so edits to the text keep the audio and the actions in sync. The recording saves ratings
through the real feedback button, so delete the rows it creates in `feedback` afterwards.
