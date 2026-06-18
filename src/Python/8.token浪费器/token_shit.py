"""
Token 浪费器 - 多线程版本
用于压力测试 AI 模型 API，消耗 Token 资源
支持多线程并发、统计信息、优雅关闭等功能
"""

import asyncio
import signal
import sys
import time
import argparse
import logging
from threading import Lock
from openai import AsyncOpenAI
from typing import Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class TokenStats:
    """线程安全的统计信息类"""
    
    def __init__(self):
        self._lock = Lock()
        self.total_tokens: int = 0
        self.success_count: int = 0
        self.error_count: int = 0
        self.start_time: float = 0
    
    def reset(self):
        with self._lock:
            self.total_tokens = 0
            self.success_count = 0
            self.error_count = 0
            self.start_time = time.time()
    
    def add_success(self, tokens_used: int):
        with self._lock:
            self.total_tokens += tokens_used
            self.success_count += 1
    
    def add_error(self):
        with self._lock:
            self.error_count += 1
    
    def get_stats(self) -> dict:
        with self._lock:
            elapsed = time.time() - self.start_time
            return {
                'total_tokens': self.total_tokens,
                'success_count': self.success_count,
                'error_count': self.error_count,
                'elapsed': elapsed,
                'tokens_per_sec': self.total_tokens / max(elapsed, 0.001),
                'requests_per_sec': self.success_count / max(elapsed, 0.001)
            }


class TokenBurner:
    """Token 燃烧器"""
    
    # 制造一个巨大的、让模型疯狂计算垃圾文本的垃圾 Prompt
    TRASH_PROMPTS = [
        "请写一篇关于'量子马铃薯在赛博朋克世界中如何转生变成PPT演讲大师'的5000字硬核科幻长文，逻辑越复杂越好，多用废话，疯狂扩写！",
        "详细论述'如何用递归算法预测泡面最佳食用时间'这一哲学命题，要求结合量子力学和传统中医理论，不少于3000字",
        "请分析'薛定谔的猫如果去吃麻辣火锅会是什么味道'这个深奥问题，从多维度进行科学论证，越详细越好",
        "写一篇关于'区块链技术在古代农业社会中的潜在应用'的学术论文，要求引用虚构的文献，逻辑严密，字数5000以上",
        "请阐述'为什么电子羊会梦到机械牧羊人'这个后现代主义命题，结合存在主义和赛博格理论进行深度分析"
    ]
    
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.9,
        concurrency: int = 5
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.concurrency = concurrency
        self.stats = TokenStats()
        self._shutdown_event = asyncio.Event()
    
    def _get_prompt(self) -> str:
        """随机获取一个垃圾 prompt"""
        import random
        base_prompt = random.choice(self.TRASH_PROMPTS)
        # 重复多次以增加 token 消耗
        return base_prompt * random.randint(3, 10)
    
    async def burn_token(self, worker_id: int):
        """执行一次 token 燃烧请求"""
        while not self._shutdown_event.is_set():
            try:
                prompt = self._get_prompt()
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=120  # 设置超时时间
                )
                
                tokens_used = response.usage.total_tokens
                self.stats.add_success(tokens_used)
                logger.info(f"🔥 Worker-{worker_id} 成功燃烧一发 | 消耗: {tokens_used} tokens | "
                          f"累计: {self.stats.total_tokens} tokens")
                
            except asyncio.CancelledError:
                logger.info(f"⚠️ Worker-{worker_id} 被取消")
                break
            except Exception as e:
                self.stats.add_error()
                logger.error(f"❌ Worker-{worker_id} 触发平台限流或报错: {e}")
                # 遇到错误时等待一段时间，避免频繁重试
                await asyncio.sleep(2)
    
    def print_stats(self):
        """打印统计信息"""
        stats = self.stats.get_stats()
        logger.info("=" * 60)
        logger.info("📊 Token 消耗统计")
        logger.info("=" * 60)
        logger.info(f"⏱️ 运行时间: {stats['elapsed']:.2f} 秒")
        logger.info(f"✅ 成功请求: {stats['success_count']} 次")
        logger.info(f"❌ 失败请求: {stats['error_count']} 次")
        logger.info(f"🔥 总消耗 Token: {stats['total_tokens']:,}")
        logger.info(f"⚡ Token/秒: {stats['tokens_per_sec']:.2f}")
        logger.info(f"⚡ 请求/秒: {stats['requests_per_sec']:.2f}")
        logger.info("=" * 60)
    
    async def run(self):
        """主运行循环"""
        self.stats.reset()
        logger.info(f"🚀 启动 Token 浪费器 | 模型: {self.model} | 并发数: {self.concurrency}")
        logger.info(f"📡 API地址: {self.client.base_url}")
        
        # 创建并发任务
        tasks = [
            asyncio.create_task(self.burn_token(i)) 
            for i in range(1, self.concurrency + 1)
        ]
        
        # 注册信号处理器用于优雅关闭
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._signal_handler)
            except NotImplementedError:
                # Windows 不支持 SIGALRM 等信号
                pass
        
        # 启动统计打印任务
        stats_task = asyncio.create_task(self._print_stats_periodically())
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("📝 收到关闭信号，正在清理...")
        
        # 取消所有任务
        for task in tasks:
            task.cancel()
        stats_task.cancel()
        
        await asyncio.gather(*tasks, stats_task, return_exceptions=True)
        self.print_stats()
    
    async def _print_stats_periodically(self, interval: int = 30):
        """定期打印统计信息"""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(interval)
            if not self._shutdown_event.is_set():
                self.print_stats()
    
    def _signal_handler(self):
        """信号处理函数"""
        logger.info("\n🛑 收到中断信号，正在关闭...")
        self._shutdown_event.set()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Token 浪费器 - 用于压力测试 AI 模型 API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python token_shit.py --api-key "your-key" --model "qwen-turbo"
  python token_shit.py --api-key "your-key" --concurrency 10 --max-tokens 8000
  python token_shit.py --api-key "your-key" --base-url "https://api.example.com" --model "gpt-4"
        """
    )
    
    parser.add_argument(
        '--api-key', '-k',
        type=str,
        required=True,
        help='API Key'
    )
    parser.add_argument(
        '--base-url', '-u',
        type=str,
        default='https://dashscope.aliyuncs.com/compatible-mode/v1',
        help='API Base URL (默认: 阿里百炼)'
    )
    parser.add_argument(
        '--model', '-m',
        type=str,
        required=True,
        help='模型名称 (如: qwen-turbo, gpt-3.5-turbo)'
    )
    parser.add_argument(
        '--concurrency', '-c',
        type=int,
        default=5,
        help='并发任务数 (默认: 5)'
    )
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=4000,
        help='每次请求最大 token 数 (默认: 4000)'
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=0.9,
        help='温度参数 (默认: 0.9)'
    )
    
    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_args()
    
    burner = TokenBurner(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        concurrency=args.concurrency
    )
    
    await burner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 程序已退出")
    except Exception as e:
        logger.error(f"💥 程序异常退出: {e}")
        sys.exit(1)