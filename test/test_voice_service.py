import io
import wave

import pytest

from tools.voice.service import VoiceInputError, decode_wav_to_pcm16


def _make_wav(sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        frame_bytes = sample_rate * channels * sample_width // 10
        writer.writeframes(b"\x00" * frame_bytes)
    return output.getvalue()


def test_decode_wav_extracts_pcm16_audio():
    pcm = decode_wav_to_pcm16(_make_wav())

    assert pcm.sample_rate == 16000
    assert len(pcm.data) == 3200


def test_decode_wav_rejects_wrong_sample_rate():
    with pytest.raises(VoiceInputError, match="16 kHz"):
        decode_wav_to_pcm16(_make_wav(sample_rate=44100))
