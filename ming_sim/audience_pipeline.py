"""召对夜内 P5 时序编排（#499 / PRD #497 接缝义务②）。

场面编排 own 全部夜内 LLM 调用时序：
- 大臣回话流式呈现
- 读心依赖回话必串但流水线化（回话先展示、读心在玩家阅读期后台生成、就绪即浮现）
- 不依赖回话输出的调用（回奏等）并行发出

严禁为省 DB 写次数把可并行调用串行化。后台完成后的 DB 写走同一把
write_gate（与月末并发 extractor / 后台召对 worker 同纪律）。

本模块是时序 seam，不负责旁白措辞或呈现壳（#491/#492 产内容，
#478/#458 管呈现）。生产入口（WebGame.chat_stream）必须完整走本状态机，
禁止绕过公开方法私改内部标志。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Mapping, Optional


class AudienceTurnPipeline:
    """P5 读心尾随状态机——回话必串于回话之后、后台生成、写锁串行化。

    1. `stream_reply(produce)` —— 跑流式回话 producer，返回完整回话正文
    2. `persist_reply(fn)` —— 回话落库；读心闸门只在此后打开
       或 `accept_persisted_reply(text)` —— 生产路径已落库后接管状态
    3. `issue_mindreading(fn)` —— 仅在 2 之后；fn 必须接收本轮完整回话（投毒防护）
    4. `write_under_gate(fn)` —— 后台结果落库走 write_gate

    不依赖回话输出的独立调用（动作意图分类等）在各自 executor 上先于回话发出、
    跨越回话流式在飞、回话后消费一次——由生产入口直接编排，不经本状态机。
    """

    def __init__(
        self,
        *,
        write_gate: Optional[threading.Lock] = None,
        executor: Optional[ThreadPoolExecutor] = None,
    ) -> None:
        self._write_gate = write_gate if write_gate is not None else threading.Lock()
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="audience-p5",
        )
        self._reply_text: Optional[str] = None
        self._reply_persisted = False
        self._mindreading_future: Optional[Future] = None
        self._closed = False

    # ── minister reply streaming ────────────────────────────────────────

    def stream_reply(
        self,
        produce: Callable[[Callable[[str], None]], str],
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """跑回话流式 producer，返回完整回话正文。"""
        if self._closed:
            raise RuntimeError("pipeline 已关闭")

        def _emit(delta: str) -> None:
            if on_delta is not None:
                on_delta(delta)

        reply = str(produce(_emit) or "")
        self._reply_text = reply
        return reply

    # ── persist ─────────────────────────────────────────────────────────

    def persist_reply(self, persist_fn: Callable[[str], Any]) -> Any:
        """回话完成后持久化。读心闸门只在此后打开。"""
        if self._reply_text is None:
            raise RuntimeError("回话尚未完成，不能持久化")
        result = self.write_under_gate(lambda: persist_fn(self._reply_text or ""))
        self._reply_persisted = True
        return result

    def accept_persisted_reply(self, reply: str) -> None:
        """生产路径已完成流式+落库后，把完整回话交给本状态机（公开 API，非私改字段）。"""
        text = str(reply or "")
        if not text.strip():
            raise ValueError("读心输入必须含该轮完整回话；回话正文为空")
        self._reply_text = text
        self._reply_persisted = True

    @property
    def reply_text(self) -> Optional[str]:
        return self._reply_text

    @property
    def reply_persisted(self) -> bool:
        return self._reply_persisted

    # ── mindreading pipeline (serial after reply, non-blocking display) ─

    def issue_mindreading(
        self,
        job: Callable[[str], Any],
        *,
        minister_reply: Optional[str] = None,
    ) -> Future:
        """在回话完成并持久化之后发出读心请求。

        投毒防护：
        - 回话未完成/未持久化 → RuntimeError
        - 显式传入的 minister_reply 必须与本轮完整回话一致（防只喂问句）
        """
        if self._reply_text is None:
            raise RuntimeError("读心请求不得早于大臣回话完成：回话尚未完成")
        if not self._reply_persisted:
            raise RuntimeError("读心请求不得早于大臣回话持久化：回话尚未落库")
        reply = self._reply_text
        if minister_reply is not None and minister_reply != reply:
            raise ValueError(
                "读心输入必须含该轮完整回话；"
                f"传入正文与本轮回话不一致（got_len={len(minister_reply)} "
                f"expected_len={len(reply)}）"
            )
        if not str(reply).strip():
            raise ValueError("读心输入必须含该轮完整回话；回话正文为空")

        self._mindreading_future = self._executor.submit(job, reply)
        return self._mindreading_future

    # ── thread-safe DB write ────────────────────────────────────────────

    def write_under_gate(self, fn: Callable[[], Any]) -> Any:
        """后台生成完成后的 DB 写走 write_gate，防并发写锁冲突。"""
        with self._write_gate:
            return fn()

    # ── lifecycle ───────────────────────────────────────────────────────

    def close(self, wait: bool = False) -> None:
        self._closed = True
        if self._owns_executor:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def __enter__(self) -> "AudienceTurnPipeline":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def mindreading_eligible(
    db: Any,
    content_characters: Mapping[str, Any],
    minister_name: str,
) -> Optional[str]:
    """若本轮可发读心，返回读心者姓名；否则 None。

    规则：存在唯一御前近臣位，且目标不是读心者本人。
    """
    from ming_sim.mindreading import current_inner_court_attendant_name

    reader = current_inner_court_attendant_name(db)
    if not reader:
        return None
    if reader == minister_name:
        return None
    if reader not in content_characters:
        return None
    if minister_name not in content_characters:
        return None
    return reader


def run_mindreading_for_turn(
    *,
    db: Any,
    state: Any,
    content_characters: Mapping[str, Any],
    minister_name: str,
    minister_reply: str,
    llm_config: Any,
    chat_turn_id: int,
    mindreading_agent: Any = None,
    write_gate: Optional[threading.Lock] = None,
) -> Optional[Dict[str, Any]]:
    """完整读心尾随：组材料 → 调模型 → 写库。失败上抛，不回滚回话。"""
    from ming_sim.mindreading import (
        build_mindreading_materials,
        generate_mindreading_payload,
    )

    reader_name = mindreading_eligible(db, content_characters, minister_name)
    if reader_name is None:
        return None
    reader = content_characters[reader_name]
    target = content_characters[minister_name]
    materials = build_mindreading_materials(
        db, state, reader, target, minister_reply,
    )
    payload = generate_mindreading_payload(
        materials, llm_config, mindreading_agent=mindreading_agent,
    )
    if chat_turn_id:
        gate = write_gate if write_gate is not None else threading.Lock()
        with gate:
            # 撤回安全（ADR 0038）：写前校验目标轮仍存活；failed/undone 不写孤儿，
            # 也不向玩家投递未落库的孤儿读心（无稳定记录身份 → 返 None）。
            if hasattr(db, "conn"):
                row = db.conn.execute(
                    "SELECT status FROM chat_turns WHERE id=?",
                    (int(chat_turn_id),),
                ).fetchone()
                if row is not None:
                    status = str(row["status"] if hasattr(row, "keys") else row[0] or "")
                    if status in {"failed", "undone"}:
                        return None
            record_id = db.record_mindreading(int(chat_turn_id), payload)
            # 附上持久记录身份，供 SSE 投递与前端 (chat_turn_id, id) 去重/归位。
            payload = {**payload, "id": int(record_id)}
    return payload
