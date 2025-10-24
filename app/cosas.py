from openai import AsyncOpenAI
import asyncio, os
async def test():
    c = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    r = await c.images.generate(model="gpt-image-1", prompt="ok", size="256x256")
    print("ok:", bool(r.data))
asyncio.run(test())