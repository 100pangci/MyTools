import asyncio
from openai import AsyncOpenAI

# 1. 填入你想干废的那个平台的 Base URL 和你的 Key
client = AsyncOpenAI(
    api_key="你的垃圾模型API-KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1" # 这里以阿里百炼为例
)

# 制造一个巨大的、让模型疯狂计算垃圾文本的垃圾 Prompt
TRASH_PROMPT = "请写一篇关于'量子马铃薯在赛博朋克世界中如何转生变成PPT演讲大师'的5000字硬核科幻长文，逻辑越复杂越好，多用废话，疯狂扩写！" * 10

async def burn_token():
    while True:
        try:
            # 2. 换成你想烧的垃圾模型 ID，比如 qwen-turbo
            response = await client.chat.completions.create(
                model="qwen-turbo", 
                messages=[{"role": "user", "content": TRASH_PROMPT}],
                max_tokens=4000, # 让它每次尽可能多吐字
                temperature=0.9
            )
            print(f"🔥 成功烧掉一发！消耗 Token 数: {response.usage.total_tokens}")
        except Exception as e:
            print(f"❌ 触发平台限流或报错: {e}，正在重试...")
            await asyncio.sleep(1)

async def main():
    # 3. 控制并发数（并行任务数），如果是轻量模型，开 5-10 个并发足矣
    tasks = [burn_token() for _ in range(5)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())