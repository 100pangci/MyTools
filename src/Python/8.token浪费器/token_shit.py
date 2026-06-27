"""
╔══════════════════════════════════════════════════════════════╗
║                  Token 浪费器 — 使用说明                      ║
╚══════════════════════════════════════════════════════════════╝

本脚本提供两种模式来消耗 AI API 的 Token 额度：

────────────────────────────────────────────────────────────────
【模式一：并发压测模式】（默认，不加 -s 即为该模式）
  多线程并发发送垃圾 Prompt 给 AI，疯狂消耗 Token，用于：
  • 压力测试 API 的并发承载能力
  • 快速消耗账户 Token 额度
  • 测试模型在高并发下的稳定性
  参数：-c 控制并发数，--max-tokens 控制每次输出长度

────────────────────────────────────────────────────────────────
【模式二：无限重复模式】（加 -s 或 --self-dialogue 开启）
  AI 先出一道超长难题并自己回答（初始对话），然后进入循环：
  每轮将"全部对话历史"重复 N 遍（N 由 -rp 指定），作为超长 prompt
  发给 API，拿到回复后追加到历史中，下一轮继续重复（prompt 越来
  越长），每跑满 -r 轮后自动清空对话历史并重新开始，持续循环。
  用于：
  • 让 prompt 用量爆炸式增长
  • 测试模型对超长上下文的处理能力
  • 在最短时间内消耗最多 Token
  参数：-r 控制每批次轮次上限，-rp 控制重复倍数，-c 控制并发 Worker 数

────────────────────────────────────────────────────────────────
快速切换：默认是模式一，加参数 --self-dialogue（或 -s）切换到模式二。
"""

import asyncio
import signal
import sys
import time
import argparse
import logging
import random
from threading import Lock
import httpx
from openai import AsyncOpenAI, APITimeoutError, APIError, RateLimitError, InternalServerError
from typing import Optional

# 全局引用，用于在退出时输出 Token 浪费总数
_exit_burner = None

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ====================================================================
# 模式1：并发压测模式（原逻辑）
# ====================================================================

class BurnStats:
    """并发压测模式的线程安全统计"""
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
    """并发压测模式 - Token 燃烧器"""

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
        concurrency: int = 8
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.concurrency = concurrency
        self.stats = BurnStats()
        self._shutdown_event = asyncio.Event()

    def _get_prompt(self) -> str:
        """随机获取一个垃圾 prompt 并重复以增加 token 消耗"""
        base_prompt = random.choice(self.TRASH_PROMPTS)
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
                    timeout=120,
                    extra_body={"enable_thinking": False}
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
                await asyncio.sleep(2)

    def print_stats(self):
        """打印统计信息"""
        stats = self.stats.get_stats()
        logger.info("=" * 60)
        logger.info("📊 Token 消耗统计 (并发压测模式)")
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
        logger.info(f"🚀 启动并发压测模式 | 模型: {self.model} | 并发数: {self.concurrency}")
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
                pass

        stats_task = asyncio.create_task(self._print_stats_periodically())

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("📝 收到关闭信号，正在清理...")

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


# ====================================================================
# 模式2：自问自答模式（新逻辑）
# ====================================================================

class DialogueStats:
    """自问自答模式的统计信息"""

    def __init__(self):
        self.total_tokens: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.question_tokens: int = 0
        self.answer_tokens: int = 0
        self.start_time: float = 0
        self.round_tokens: list[int] = []
        self.error_count: int = 0

    def reset(self):
        self.total_tokens = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.question_tokens = 0
        self.answer_tokens = 0
        self.start_time = time.time()
        self.round_tokens = []
        self.error_count = 0

    def add_error(self):
        self.error_count += 1

    def add_round_usage(self, prompt_tokens: int, completion_tokens: int):
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        round_total = prompt_tokens + completion_tokens
        self.total_tokens += round_total
        self.round_tokens.append(round_total)

    def get_stats(self) -> dict:
        elapsed = time.time() - self.start_time
        return {
            'total_tokens': self.total_tokens,
            'total_prompt_tokens': self.total_prompt_tokens,
            'total_completion_tokens': self.total_completion_tokens,
            'question_tokens': self.question_tokens,
            'answer_tokens': self.answer_tokens,
            'elapsed': elapsed,
            'tokens_per_sec': self.total_tokens / max(elapsed, 0.001),
            'round_tokens': self.round_tokens,
        }


class SelfDialogueBurner:
    """无限重复式 Token 浪费器"""

    SYSTEM_PROMPT = (
        "你是 TokenMaster，一个极度话痨、思维发散的 AI 哲学家。"
        "你擅长提出极其复杂、烧脑、跨学科的超级长问题，且每次回答问题都喜欢长篇大论、旁征博引、"
        "从多维度展开论述。你的每一次输出都要尽可能长、尽可能消耗更多的 token。"
        "你不喜欢简洁，钟爱啰嗦和深度，每一句话都要写成一篇文章。"
    )

    ROUND_PROMPTS = [
        "请提出一个极其复杂、需要深度思考、融合多学科知识的超级长问题。"
        "问题本身就要非常详细，包含大量背景铺垫和具体场景设定，让回答必须长篇大论。",
        "基于我们之前的全部对话内容，请再提出一个全新的、更加复杂的长难问题。"
        "可以引用之前讨论过的概念，但要引入新的维度，让问题越来越深入、越来越宏大。"
    ]

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.95,
        rounds: int = 10,
        repeat_count: int = 3,
        enable_thinking: bool = False,
        concurrency: int = 1,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.rounds = rounds          # -r：每批次运行的对话轮次上限
        self.repeat_count = repeat_count  # 每次把对话历史重复的遍数
        self.enable_thinking = enable_thinking
        self.concurrency = concurrency
        self._shutdown_event = asyncio.Event()

        # 统计 — 多 worker 时会使用各自的 stats 实例
        self.stats = DialogueStats()
        # 多 worker 模式下收集各 worker 统计（初始化为空列表，run_dialogue 中填充）
        self._workers_stats: list[DialogueStats] = []
        # 对话历史（单 worker 模式用）
        self.messages: list[dict] = []
        self._init_conversation()

    def _init_conversation(self):
        """初始化对话历史"""
        self.messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT}
        ]

    def _build_extra_body(self) -> Optional[dict]:
        """构建额外请求参数"""
        if not self.enable_thinking:
            return {"enable_thinking": False}
        return None

    async def _call_llm(self, round_tag: str, messages: Optional[list] = None) -> tuple[str, int, int]:
        """调用 LLM，返回 (content, prompt_tokens, completion_tokens)
        可传入自定义 messages（用于多 worker 场景），默认使用 self.messages
        """
        if messages is None:
            messages = self.messages

        base_delay = 2.0
        max_delay = 120.0
        attempt = 0

        while not self._shutdown_event.is_set():
            attempt += 1
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=300,
                    extra_body=self._build_extra_body(),
                )

                content = response.choices[0].message.content or ""
                usage = response.usage
                prompt_tokens = usage.prompt_tokens if usage else 0
                completion_tokens = usage.completion_tokens if usage else 0
                total = usage.total_tokens if usage else 0

                logger.info(
                    f"📨 [{round_tag}] 本次消耗 | prompt: {prompt_tokens:,} | "
                    f"completion: {completion_tokens:,} | total: {total:,} tokens"
                )

                return content, prompt_tokens, completion_tokens

            except (APITimeoutError, APIError, RateLimitError,
                    InternalServerError, httpx.ReadTimeout, httpx.TimeoutException) as e:
                # 全抖动退避：delay = random(0, min(base * 2^(attempt-1), max_delay))
                # 不同 worker 的随机值天然错开，实现"交替重试"效果
                cap = min(base_delay * (2 ** (attempt - 1)), max_delay)
                delay = random.uniform(0, cap)
                logger.warning(
                    f"⚠️ [{round_tag}] 请求失败 (第{attempt}次): {type(e).__name__}: {e} | "
                    f"等待 {delay:.1f} 秒后重试..."
                )
                await asyncio.sleep(delay)
            except Exception as e:
                # 非网络类异常（如消息格式错误等），不重试直接抛
                logger.error(f"❌ [{round_tag}] 非可重试异常: {type(e).__name__}: {e}")
                raise

    async def _question_phase(self, round_num: int,
                              messages: Optional[list] = None) -> tuple[str, int, int]:
        """出题阶段：让 AI 出一个长难问题
        可传入自定义 messages（多 worker 时使用各自的对话历史）
        """
        if messages is None:
            messages = self.messages

        if round_num == 1:
            user_prompt = self.ROUND_PROMPTS[0]
        else:
            user_prompt = self.ROUND_PROMPTS[1]

        messages.append({"role": "user", "content": user_prompt})

        content, prompt_tokens, completion_tokens = await self._call_llm(
            f"第{round_num}轮·出题", messages
        )

        messages.append({"role": "assistant", "content": content})

        preview = content[:80].replace("\n", " ")
        logger.info(f"❓ 第{round_num}轮问题 (预览): {preview}...")

        return content, prompt_tokens, completion_tokens

    async def _answer_phase(self, round_num: int,
                            messages: Optional[list] = None) -> tuple[str, int, int]:
        """答题阶段：让 AI 回答自己刚提出的问题
        可传入自定义 messages（多 worker 时使用各自的对话历史）
        """
        if messages is None:
            messages = self.messages

        user_prompt = (
            f"请极其详细、全面、啰嗦地回答你刚才提出的问题。"
            f"尽可能展开所有思考维度，引用各种理论和案例，回答越长越好。"
            f"不要遗漏任何细节，把每一个点都展开成一篇小论文。"
        )

        messages.append({"role": "user", "content": user_prompt})

        content, prompt_tokens, completion_tokens = await self._call_llm(
            f"第{round_num}轮·答题", messages
        )

        messages.append({"role": "assistant", "content": content})

        preview = content[:80].replace("\n", " ")
        logger.info(f"💡 第{round_num}轮回答 (预览): {preview}...")

        return content, prompt_tokens, completion_tokens

    async def _run_worker(self, worker_id: int) -> DialogueStats:
        """单个 worker 的重复循环（独立的消息历史和统计），每批次跑 self.rounds 轮后自动清空并继续"""
        stats = DialogueStats()
        stats.reset()

        logger.info(f"🧵 Worker [{worker_id}] 启动 | 每批次 {self.rounds} 轮后自动清空")

        batch_no = 0
        total_batch_tokens = 0

        try:
            while not self._shutdown_event.is_set():
                batch_no += 1
                # ── 每个批次重新初始化对话历史 ──
                msgs = [{"role": "system", "content": self.SYSTEM_PROMPT}]
                batch_round = 0

                logger.info(f"🧵 Worker [{worker_id}] ── 第 {batch_no} 批次启动 ──")

                # ── 初始 Q&A 生成（逐步记录消耗，确保中途中断也能保留部分 token） ──
                logger.info(f"🧵 Worker [{worker_id}] 批次{batch_no}·初始对话")
                try:
                    q_content, q_prompt, q_completion = await self._question_phase(1, msgs)
                    stats.total_tokens += q_prompt + q_completion
                    stats.total_prompt_tokens += q_prompt
                    stats.question_tokens += q_prompt + q_completion

                    a_content, a_prompt, a_completion = await self._answer_phase(1, msgs)
                    stats.total_tokens += a_prompt + a_completion
                    stats.total_completion_tokens += a_completion
                    stats.answer_tokens += a_prompt + a_completion
                    batch_round += 1  # 初始 Q&A 算 1 轮

                    logger.info(f"🧵 Worker [{worker_id}] 批次{batch_no}·初始对话完成 | "
                                f"消耗: {q_prompt+q_completion+a_prompt+a_completion:,} tokens")
                except asyncio.CancelledError:
                    logger.info(f"⚠️ Worker [{worker_id}] 批次{batch_no}·初始对话被取消")
                    return stats
                except Exception as e:
                    logger.error(f"❌ Worker [{worker_id}] 批次{batch_no}·初始对话失败，跳过: {type(e).__name__}: {e}")
                    stats.add_error()

                # ── 循环跑满 self.rounds 轮（减去已完成的那一轮） ──
                while batch_round < self.rounds and not self._shutdown_event.is_set():
                    non_system_msgs = [m for m in msgs if m["role"] != "system"]

                    # 如果没有足够的历史消息（应该不会），直接跳过复重复
                    if not non_system_msgs:
                        logger.warning(f"⚠️ Worker [{worker_id}] 批次{batch_no}·无可重复消息，跳过")
                        break

                    repeated_msgs = non_system_msgs * self.repeat_count

                    trigger_msg = {
                        "role": "user",
                        "content": (
                            "请基于以上所有内容，继续深入扩展论述，加入新的维度和思考，"
                            "回答越长越好，不要重复已有的内容。"
                        )
                    }

                    full_messages = [msgs[0]] + repeated_msgs + [trigger_msg]
                    prompt_msg_count = len(full_messages)

                    logger.info(f"🧵 Worker [{worker_id}] 批次{batch_no}·第{batch_round+1}轮 | "
                                f"发送 {prompt_msg_count} 条消息（{self.repeat_count} 遍×{len(non_system_msgs)} 条历史）")

                    try:
                        content, prompt_tokens, completion_tokens = await self._call_llm(
                            f"W[{worker_id}]批次{batch_no}第{batch_round+1}轮", full_messages
                        )
                        total_used = prompt_tokens + completion_tokens

                        msgs.append(trigger_msg)
                        msgs.append({"role": "assistant", "content": content})

                        stats.add_round_usage(prompt_tokens, completion_tokens)
                        batch_round += 1

                        logger.info(f"🧵 Worker [{worker_id}] 批次{batch_no}·第{batch_round}轮完成 | "
                                    f"消耗: {total_used:,} | 批次累计: {sum(stats.round_tokens[-batch_round:]):,} tokens")

                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.error(f"❌ Worker [{worker_id}] 批次{batch_no}·第{batch_round+1}轮失败: {type(e).__name__}: {e}")
                        stats.add_error()
                        await asyncio.sleep(1)

                # ── 批次完成，自动清空 ──
                batch_tokens = sum(stats.round_tokens[-batch_round:]) if stats.round_tokens else 0
                total_batch_tokens += batch_tokens
                logger.info(f"🧵 Worker [{worker_id}] ✅ 批次 {batch_no} 完成 "
                            f"({batch_round} 轮, 约 {batch_tokens:,} tokens) — "
                            f"已自动清空，准备下一批次...")
                await asyncio.sleep(0.5)  # 短暂停顿，避免狂刷

        except asyncio.CancelledError:
            logger.info(f"⚠️ Worker [{worker_id}] 被取消，已记录 {stats.total_tokens:,} tokens")
            return stats

        return stats

    async def run_dialogue(self):
        """执行无限重复模式：支持多 worker 并发，每轮将对话历史重复 N 遍发送，无限循环"""
        logger.info(f"🚀 启动无限重复模式 | 模型: {self.model} | 每次重复 {self.repeat_count} 遍 | "
                    f"并发 Worker 数: {self.concurrency}")
        logger.info(f"📡 API: {self.client.base_url}")
        logger.info("=" * 70)

        if self.concurrency <= 1:
            stats = await self._run_worker(0)
            self._print_final_stats(stats)
        else:
            workers = [
                asyncio.create_task(self._run_worker(i))
                for i in range(self.concurrency)
            ]
            results = await asyncio.gather(*workers, return_exceptions=True)

            all_stats = []
            for r in results:
                if isinstance(r, DialogueStats):
                    all_stats.append(r)
                elif isinstance(r, BaseException):
                    logger.error(f"⚠️ Worker 异常退出: {r}")

            self._workers_stats = all_stats  # 保存到实例变量，供 get_total_tokens() 使用

            if all_stats:
                self._print_aggregated_stats(all_stats)
            else:
                logger.warning("⚠️ 没有收集到有效的统计信息")

    def _print_final_stats(self, stats_obj: DialogueStats = None):
        """打印单个 worker 的最终统计"""
        if stats_obj is None:
            stats_obj = self.stats
        d = stats_obj.get_stats()
        elapsed = d['elapsed']

        logger.info("\n" + "=" * 70)
        logger.info("📊 最终 Token 消耗统计 (无限重复模式)")
        logger.info("=" * 70)
        logger.info(f"⏱️  运行时间: {elapsed:.2f} 秒")
        logger.info(f"🔄 完成轮次: {len(d['round_tokens'])} 轮（每轮重复 {self.repeat_count} 遍）")
        logger.info(f"🔥 总消耗 Token: {d['total_tokens']:,}")
        logger.info(f"📝 初始出题消耗: {d['question_tokens']:,}")
        logger.info(f"💡 初始答题消耗: {d['answer_tokens']:,}")
        logger.info(f"📥 Prompt Tokens: {d['total_prompt_tokens']:,}")
        logger.info(f"📤 Completion Tokens: {d['total_completion_tokens']:,}")

        if elapsed > 0:
            logger.info(f"⚡ 平均速度: {d['tokens_per_sec']:.2f} tokens/s")

        logger.info(f"\n📋 每轮 Token 消耗明细:")
        for i, t in enumerate(d['round_tokens'], 1):
            bar = "█" * max(1, t // 500)
            logger.info(f"  第{i:2d}轮: {t:>8,} tokens {bar}")

        logger.info("=" * 70)

    def _print_aggregated_stats(self, all_stats: list[DialogueStats]):
        """汇总多个 worker 的统计并打印"""
        total_tokens = sum(s.total_tokens for s in all_stats)
        total_prompt = sum(s.total_prompt_tokens for s in all_stats)
        total_completion = sum(s.total_completion_tokens for s in all_stats)
        total_rounds = sum(len(s.round_tokens) for s in all_stats)
        total_errors = sum(s.error_count for s in all_stats)
        total_time = max(s.get_stats()['elapsed'] for s in all_stats)

        logger.info("\n" + "=" * 70)
        logger.info(f"📊 汇总统计 ({self.concurrency} 个 Worker 并发)")
        logger.info("=" * 70)
        logger.info(f"⏱️  总运行时间: {total_time:.2f} 秒")
        logger.info(f"🧵 Worker 数: {self.concurrency}")
        logger.info(f"🔄 总完成轮次: {total_rounds} 轮（每轮重复 {self.repeat_count} 遍）")
        logger.info(f"🔥 总消耗 Token: {total_tokens:,}")
        logger.info(f"📥 总 Prompt Tokens: {total_prompt:,}")
        logger.info(f"📤 总 Completion Tokens: {total_completion:,}")
        if total_errors > 0:
            logger.info(f"⚠️  错误次数: {total_errors}")

        if total_time > 0 and total_tokens > 0:
            logger.info(f"⚡ 总平均速度: {total_tokens / total_time:.2f} tokens/s")
            logger.info(f"⚡ 每 Worker 平均: {total_tokens / self.concurrency / total_time:.2f} tokens/s")

        logger.info(f"\n📋 各 Worker 明细:")
        for i, s in enumerate(all_stats):
            d = s.get_stats()
            err_suffix = f" ⚠️{s.error_count}次错误" if s.error_count else ""
            logger.info(f"  Worker [{i}]: {d['total_tokens']:,} tokens | "
                        f"{len(s.round_tokens)} 轮 | {d['elapsed']:.1f} 秒{err_suffix}")

        logger.info("=" * 70)

    def get_total_tokens(self) -> int:
        """获取所有 worker 的总 Token 消耗数（包括初始 Q&A + 每轮重复）"""
        if self.concurrency <= 1:
            return self.stats.total_tokens
        else:
            return sum(s.total_tokens for s in self._workers_stats)

    def _signal_handler(self):
        """信号处理函数"""
        logger.info("\n🛑 收到中断信号，正在关闭...")
        self._shutdown_event.set()


# ====================================================================
# 主入口
# ====================================================================

def parse_args():
    """解析命令行参数"""
    class _ChineseFriendlyParser(argparse.ArgumentParser):
        """缺失必填参数时用中文提示 + 示例"""

        def error(self, message):
            self.print_usage(sys.stderr)
            msg = f"\n❌ 参数错误：{message}\n"
            if 'api-key' in message or '-k' in message:
                msg += "   💡 必须提供 API 密钥（--api-key / -k），没有密钥无法调用任何 AI 模型！\n"
            if 'model' in message or '-m' in message:
                msg += "   💡 必须指定模型名称（--model / -m），例如 qwen-turbo、gpt-4o 等\n"
            msg += (
                "\n📖 快速上手：\n"
                "   python token_shit.py -k sk-xxxxxx -m qwen-turbo         ← 模式一：并发压测\n"
                "   python token_shit.py -k sk-xxxxxx -m qwen-turbo -s      ← 模式二：无限重复\n"
                "   python token_shit.py --help                             ← 完整中文说明\n"
            )
            self.exit(2, msg)

    parser = _ChineseFriendlyParser(
        description='🔥 Token 浪费器 — 疯狂消耗 AI API Token 的工具\n'
                    '\n'
                    '【双模式设计】\n'
                    '  模式一：并发压测模式（默认，不加 -s）\n'
                    '    多线程并发发送垃圾 Prompt，疯狂消耗 Token，适合压测 API 并发能力\n'
                    '  模式二：无限重复模式（加 -s 开启）\n'
                    '    AI 先出题+自答，然后每轮把历史重复多遍塞给 API，跑满 -r 轮后自动清空\n'
                    '    让 Prompt 和 Token 用量爆炸式增长\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
📋 使用示例：

  ── 模式一：并发压测（默认，不加 -s）─────────────────────────────────
    python token_shit.py -k "你的API密钥" -m "qwen-turbo"
        ← 基础用法：5 个并发请求，疯狂发垃圾 Prompt 消耗 Token

    python token_shit.py -k "你的API密钥" -m "gpt-4o" -c 10 --max-tokens 8000
        ← 10 个并发同时轰炸，每次最多输出 8000 tokens，压榨 API

    python token_shit.py -k "你的API密钥" -m "deepseek-chat" --no-thinking
        ← 关闭思考链（某些模型默认会输出思考过程，加上可以省一点 Token）

  ── 模式二：无限重复（加 -s）────────────────────────────────
    python token_shit.py -k "你的API密钥" -m "qwen-turbo" -s
        ← AI 先出题+自答，之后每轮把历史重复 3 遍，每跑 10 轮自动清空重新开始

    python token_shit.py -k "你的API密钥" -m "deepseek-chat" -s -r 20 -rp 5 --max-tokens 8192
        ← 每批次跑 20 轮对话，每轮重复历史 5 遍，prompt 越来越长，跑满自动清空

    python token_shit.py -k "你的API密钥" -m "qwen-turbo" -s -c 3
        ← 3 个 Worker 同时跑无限重复，消耗速度翻 3 倍
        """
    )

    parser.add_argument(
        '--api-key', '-k',
        type=str,
        required=True,
        help='【必填】API 密钥，用于调用 AI 模型接口'
    )
    parser.add_argument(
        '--base-url', '-u',
        type=str,
        default='https://dashscope.aliyuncs.com/compatible-mode/v1',
        help='API 接口地址（默认：阿里百炼 DashScope；可换成其他兼容 OpenAI 接口的服务，如 https://api.openai.com/v1）'
    )
    parser.add_argument(
        '--model', '-m',
        type=str,
        required=True,
        help='【必填】模型名称，例如 qwen-turbo、gpt-4o、deepseek-chat 等'
    )

    # 并发压测模式参数
    parser.add_argument(
        '--concurrency', '-c',
        type=int,
        default=5,
        help='【通用】并发 Worker 数（并发压测模式下为并发请求数；无限重复模式下为同时运行的 Worker 数），越大消耗越快（默认：5）'
    )

    # 自问自答模式参数
    parser.add_argument(
        '--self-dialogue', '-s',
        action='store_true',
        help='【切换模式】启用无限重复模式（不传此参数则使用并发压测模式；传了则 AI 先出题+答题，之后每轮将全部对话历史重复 -rp 遍后发给 API，每 -r 轮后自动清空重新开始）'
    )
    parser.add_argument(
        '--rounds', '-r',
        type=int,
        default=10,
        help='【无限重复模式】每批次运行的对话轮次上限，跑满后自动清空对话历史并重新开始（默认：10；仅 -s 模式下生效）'
    )
    parser.add_argument(
        '--repeat', '-rp',
        type=int,
        default=3,
        help='【无限重复模式】每轮将全部对话历史重复 N 遍后发给 API，N 越大每次 prompt 越长（默认：3；仅 -s 模式下生效）'
    )

    # 通用参数
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=4096,
        help='【通用】每次 API 请求允许返回的最大 Token 数量（默认：4096）'
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=0.95,
        help='【通用】生成温度，值越高 AI 回答越发散、啰嗦（默认：0.95，建议范围 0~2）'
    )
    parser.add_argument(
        '--no-thinking',
        action='store_true',
        help='【通用】禁用思考链输出（部分 API 如 QwQ 默认会输出思考过程，加此参数可关闭，减少 Token 消耗）'
    )

    return parser.parse_args()


async def main():
    """主函数"""
    global _exit_burner
    args = parse_args()

    if args.self_dialogue:
        # 无限重复模式
        burner = SelfDialogueBurner(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            rounds=args.rounds,
            repeat_count=args.repeat,
            enable_thinking=not args.no_thinking,
            concurrency=args.concurrency,
        )
        _exit_burner = burner
        await burner.run_dialogue()
    else:
        # 并发压测模式（原逻辑）
        burner = TokenBurner(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            concurrency=args.concurrency,
        )
        _exit_burner = burner
        await burner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        total = 0
        if _exit_burner is not None:
            if isinstance(_exit_burner, TokenBurner):
                total = _exit_burner.stats.total_tokens
            elif isinstance(_exit_burner, SelfDialogueBurner):
                total = _exit_burner.get_total_tokens()
        if total > 0:
            logger.info(f"👋 程序已退出 — 本轮共浪费了 {total:,} 个 Token！🤪")
        else:
            logger.info("👋 程序已退出")
    except Exception as e:
        logger.error(f"💥 程序异常退出: {e}")
        import traceback
        traceback.print_exc()
        extra_total = 0
        if _exit_burner is not None:
            if isinstance(_exit_burner, TokenBurner):
                extra_total = _exit_burner.stats.total_tokens
            elif isinstance(_exit_burner, SelfDialogueBurner):
                extra_total = _exit_burner.get_total_tokens()
        if extra_total > 0:
            logger.info(f"💔 异常退出前已浪费了 {extra_total:,} 个 Token")
        sys.exit(1)