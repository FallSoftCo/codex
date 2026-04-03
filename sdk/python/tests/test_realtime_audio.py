from __future__ import annotations

import base64
import io
import wave

import pytest

from codex_app_server.realtime_audio import (
    iter_pcm16le_audio_chunks,
    iter_wav_audio_bytes_chunks,
    pcm16le_audio_chunk,
)


def test_pcm16le_audio_chunk_encodes_metadata_and_payload() -> None:
    chunk = pcm16le_audio_chunk(
        b"\x01\x00\x02\x00",
        sample_rate=24_000,
        num_channels=1,
    )

    assert chunk.sample_rate == 24_000
    assert chunk.num_channels == 1
    assert chunk.samples_per_channel == 2
    assert base64.b64decode(chunk.data) == b"\x01\x00\x02\x00"


def test_iter_pcm16le_audio_chunks_splits_stream_by_frame_count() -> None:
    stream = io.BytesIO(b"\x01\x00\x02\x00\x03\x00\x04\x00")

    chunks = list(
        iter_pcm16le_audio_chunks(
            stream,
            sample_rate=24_000,
            num_channels=1,
            frames_per_chunk=1,
        )
    )

    assert len(chunks) == 4
    assert [chunk.samples_per_channel for chunk in chunks] == [1, 1, 1, 1]
    assert [base64.b64decode(chunk.data) for chunk in chunks] == [
        b"\x01\x00",
        b"\x02\x00",
        b"\x03\x00",
        b"\x04\x00",
    ]


def test_iter_pcm16le_audio_chunks_rejects_partial_frames() -> None:
    stream = io.BytesIO(b"\x01\x00\x02")

    with pytest.raises(ValueError, match="mid-frame"):
        list(
            iter_pcm16le_audio_chunks(
                stream,
                sample_rate=24_000,
                num_channels=1,
            )
        )


def test_iter_wav_audio_bytes_chunks_reads_pcm16_wav() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x01\x00\x02\x00\x03\x00\x04\x00")

    chunks = list(iter_wav_audio_bytes_chunks(buffer.getvalue(), frames_per_chunk=2))

    assert len(chunks) == 2
    assert [chunk.sample_rate for chunk in chunks] == [16_000, 16_000]
    assert [chunk.samples_per_channel for chunk in chunks] == [2, 2]
    assert [base64.b64decode(chunk.data) for chunk in chunks] == [
        b"\x01\x00\x02\x00",
        b"\x03\x00\x04\x00",
    ]
