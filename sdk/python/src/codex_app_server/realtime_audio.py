from __future__ import annotations

import base64
import io
import wave
from collections.abc import Iterator
from typing import BinaryIO

from .generated.v2_all import ThreadRealtimeAudioChunk


def pcm16le_audio_chunk(
    pcm16le: bytes,
    *,
    sample_rate: int,
    num_channels: int,
    item_id: str | None = None,
) -> ThreadRealtimeAudioChunk:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if num_channels <= 0:
        raise ValueError("num_channels must be positive")
    frame_width = num_channels * 2
    if len(pcm16le) % frame_width != 0:
        raise ValueError(
            "pcm16le byte length must align to full sample frames "
            f"(got {len(pcm16le)} bytes for {num_channels} channel(s))"
        )
    samples_per_channel = len(pcm16le) // frame_width
    return ThreadRealtimeAudioChunk(
        data=base64.b64encode(pcm16le).decode("ascii"),
        sample_rate=sample_rate,
        num_channels=num_channels,
        samples_per_channel=samples_per_channel,
        item_id=item_id,
    )


def iter_pcm16le_audio_chunks(
    stream: BinaryIO,
    *,
    sample_rate: int,
    num_channels: int,
    frames_per_chunk: int = 480,
    item_id: str | None = None,
) -> Iterator[ThreadRealtimeAudioChunk]:
    if frames_per_chunk <= 0:
        raise ValueError("frames_per_chunk must be positive")
    chunk_size = frames_per_chunk * num_channels * 2
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        trailing = len(chunk) % (num_channels * 2)
        if trailing:
            raise ValueError(
                "pcm16le stream ended mid-frame "
                f"({len(chunk)} trailing bytes for {num_channels} channel(s))"
            )
        yield pcm16le_audio_chunk(
            chunk,
            sample_rate=sample_rate,
            num_channels=num_channels,
            item_id=item_id,
        )


def iter_wav_audio_chunks(
    stream: BinaryIO,
    *,
    frames_per_chunk: int = 480,
    item_id: str | None = None,
) -> Iterator[ThreadRealtimeAudioChunk]:
    if frames_per_chunk <= 0:
        raise ValueError("frames_per_chunk must be positive")
    with wave.open(stream, "rb") as wav_file:
        if wav_file.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV streams are supported")
        sample_rate = wav_file.getframerate()
        num_channels = wav_file.getnchannels()
        while True:
            chunk = wav_file.readframes(frames_per_chunk)
            if not chunk:
                break
            yield pcm16le_audio_chunk(
                chunk,
                sample_rate=sample_rate,
                num_channels=num_channels,
                item_id=item_id,
            )


def iter_wav_audio_file_chunks(
    path: str,
    *,
    frames_per_chunk: int = 480,
    item_id: str | None = None,
) -> Iterator[ThreadRealtimeAudioChunk]:
    with open(path, "rb") as stream:
        yield from iter_wav_audio_chunks(
            stream,
            frames_per_chunk=frames_per_chunk,
            item_id=item_id,
        )


def iter_wav_audio_bytes_chunks(
    data: bytes,
    *,
    frames_per_chunk: int = 480,
    item_id: str | None = None,
) -> Iterator[ThreadRealtimeAudioChunk]:
    yield from iter_wav_audio_chunks(
        io.BytesIO(data),
        frames_per_chunk=frames_per_chunk,
        item_id=item_id,
    )
