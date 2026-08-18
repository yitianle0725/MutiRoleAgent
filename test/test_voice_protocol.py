from tools.voice.asr.ali_qwen_asr import AliRealtimeAsr
from tools.voice.tts.ali_qwen_tts import AliStreamTts


def test_ali_asr_builds_pcm_start_message():
    service = AliRealtimeAsr(api_key="test-key")

    start = service._build_start_message("task-1", 16000)
    finish = service._build_finish_message("task-1")

    assert start["payload"]["task"] == "asr"
    assert start["header"]["streaming"] == "duplex"
    assert start["payload"]["input"] == {}
    assert start["payload"]["parameters"]["sample_rate"] == 16000
    assert finish["header"]["streaming"] == "duplex"
    assert finish["payload"]["input"] == {}


def test_ali_tts_builds_streaming_messages():
    service = AliStreamTts(api_key="test-key")

    start = service._build_start_message("task-1")
    text = service._build_text_message("task-1", "你好")
    finish = service._build_finish_message("task-1")

    assert start["payload"]["task"] == "tts"
    assert start["payload"]["input"] == {}
    assert start["header"]["streaming"] == "duplex"
    assert start["payload"]["parameters"]["format"] == "mp3"
    assert text["header"]["streaming"] == "duplex"
    assert text["payload"]["input"]["text"] == "你好"
    assert finish["header"]["streaming"] == "duplex"
    assert finish["payload"]["input"] == {}
