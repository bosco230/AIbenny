import asyncio
from openmimicry.voice.tts.qwen3 import Qwen3TTSAdapter

async def main():
    adapter = Qwen3TTSAdapter()
    text = "唔該啦，我今日係電腦裡度過啦，不過都唔錯啦！"
    async for chunk in adapter._sentence_stream(text):
        print(repr(chunk), len(chunk))

asyncio.run(main())
