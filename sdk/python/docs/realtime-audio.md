# Realtime Audio

The app-server protocol already supports thread-scoped realtime audio input through
`thread/realtime/appendAudio`. The Python SDK exposes that surface directly so a
remote client can stream audio into an active realtime session without depending on
local microphone capture.

## Start realtime and stream PCM16 audio

```python
from codex_app_server import Codex, iter_pcm16le_audio_chunks

PROMPT = "You are the spoken control layer for Codex."

with Codex() as codex:
    thread = codex.thread_start(model="gpt-5")
    thread.realtime_start(PROMPT)

    with open("audio.pcm", "rb") as stream:
        for chunk in iter_pcm16le_audio_chunks(
            stream,
            sample_rate=24_000,
            num_channels=1,
            frames_per_chunk=480,
        ):
            thread.realtime_append_audio(chunk)

    thread.realtime_stop()
```

`iter_pcm16le_audio_chunks(...)` expects little-endian signed 16-bit PCM. Each yielded
chunk is already base64-encoded and shaped for `thread/realtime/appendAudio`.

## Stream WAV audio

```python
from codex_app_server import Codex, iter_wav_audio_file_chunks

with Codex() as codex:
    thread = codex.thread_start(model="gpt-5")
    thread.realtime_start("Speak briefly and naturally.")

    for chunk in iter_wav_audio_file_chunks("speech.wav", frames_per_chunk=480):
        thread.realtime_append_audio(chunk)

    thread.realtime_stop()
```

Only 16-bit PCM WAV input is accepted by the helper.

## Notes

- The helper functions do not resample. They preserve the input sample rate and channel count.
- Use `frames_per_chunk` to control latency. `480` frames is a reasonable default for
  low-latency speech streaming.
- If you already have encoded realtime chunks, call `thread.realtime_append_audio(...)`
  directly with a `ThreadRealtimeAudioChunk`.
