from tools.voice.voice_state import VoiceState, VoiceStateMachine


def test_voice_state_machine_follows_conversation_order():
    machine = VoiceStateMachine()

    machine.move_to(VoiceState.LISTENING)
    machine.move_to(VoiceState.THINKING)
    machine.move_to(VoiceState.SPEAKING)

    assert machine.state is VoiceState.SPEAKING


def test_voice_state_machine_rejects_invalid_transition():
    machine = VoiceStateMachine()

    try:
        machine.move_to(VoiceState.SPEAKING)
    except ValueError as error:
        assert "不支持的语音状态迁移" in str(error)
    else:
        raise AssertionError("IDLE 不应直接进入 SPEAKING")


def test_voice_state_machine_records_recoverable_error():
    machine = VoiceStateMachine()
    machine.fail("网络超时")

    assert machine.state is VoiceState.ERROR
    assert machine.error_message == "网络超时"

    machine.reset()
    assert machine.state is VoiceState.IDLE
