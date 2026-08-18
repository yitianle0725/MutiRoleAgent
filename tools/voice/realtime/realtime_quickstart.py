import asyncio
import base64
import json
import os
import pyaudio
import websockets

API_KEY = os.environ["DASHSCOPE_API_KEY"]
# 以下为华北2（北京）地域的WebSocket URL，调用时请将{WorkspaceId}（含花括号）替换为真实的业务空间ID，各地域的URL不同。
URL = "wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus"

pya = pyaudio.PyAudio()
mic = pya.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True)
spk = pya.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)

async def main():
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with websockets.connect(URL, additional_headers=headers) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": "longanqian",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": 800
                }
            }
        }))

        async def send_audio():
            while True:
                data = await asyncio.to_thread(mic.read, 3200, False)
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(data).decode()
                }))
                await asyncio.sleep(0.02)

        async def recv_events():
            async for msg in ws:
                event = json.loads(msg)
                t = event["type"]
                if t == "response.audio.delta":
                    audio = base64.b64decode(event["delta"])
                    await asyncio.to_thread(spk.write, audio)
                elif t == "conversation.item.input_audio_transcription.completed":
                    print(f"[You] {event['transcript']}")
                elif t == "response.audio_transcript.done":
                    print(f"[AI] {event['transcript']}")
                elif t == "error":
                    print(f"[Error] {event['error']['message']}")

        await asyncio.gather(send_audio(), recv_events())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        mic.close()
        spk.close()
        pya.terminate()
        print("\n对话结束")