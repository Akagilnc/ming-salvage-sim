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
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

# ── timeline event names（测试 / 时序日志真源）──────────────────────────
EVT_PARALLEL_ISSUED = "parallel_issued"
EVT_REPLY_FIRST_TOKEN = "reply_first_token"
EVT_REPLY_COMPLETE = "reply_complete"
EVT_REPLY_PERSISTED = "reply_persisted"
EVT_REPLY_VISIBLE = "reply_visible"
EVT_MINDREADING_ISSUED = "mindreading_issued"
EVT_MINDREADING_COMPLETE = "mindreading_complete"
EVT_MINDREADING_FAILED = "mindreading_failed"
EVT_PARALLEL_COMPLETE = "parallel_complete"
EVT_DB_WRITE = "db_write"

# 近臣回奏触发词（与 session._audience_prompt_for_message 同口径）
RETURN_REPORT_KEYWORDS = (
    "官缺", "巡抚", "总督", "督抚", "欠饷", "军情", "敌情", "流寇", "贼情", "查访",
)


@dataclass
class TimelineEvent:
    name: str
    t: float
    detail: Dict[str, Any] = field(default_factory=dict)


class PipelineTimeline:
    """Append-only 时序日志。测试用它断言先后与并发。"""

    def __init__(self) -> None:
        self._events: List[TimelineEvent] = []
        self._lock = threading.Lock()

    def log(self, name: str, **detail: Any) -> None:
        with self._lock:
            self._events.append(TimelineEvent(name=name, t=time.monotonic(), detail=dict(detail)))

    @property
    def events(self) -> List[TimelineEvent]:
        with self._lock:
            return list(self._events)

    def names(self) -> List[str]:
        return [e.name for e in self.events]

    def first(self, name: str) -> Optional[TimelineEvent]:
        for event in self.events:
            if event.name == name:
                return event
        return None

    def all(self, name: str) -> List[TimelineEvent]:
        return [e for e in self.events if e.name == name]


class AudienceTurnPipeline:
    """P5 时序调度器——生产与测试共用的状态机。

    1. `start_parallel(jobs)` —— 不依赖回话输出的调用立刻并发发出
    2. `stream_reply(produce)` —— 流式回话；首 token 先于读心
    3. `persist_reply(fn)` —— 回话落库；此后才允许发读心
       或 `accept_persisted_reply(text)` —— 生产路径已落库后接管状态
    4. `mark_reply_visible()` —— 回话对玩家可见（done；不等读心）
    5. `issue_mindreading(fn)` —— 仅在 3 之后；fn 必须接收完整回话
    6. `write_under_gate(fn)` —— 后台结果落库走写锁
    """

    def __init__(
        self,
        *,
        write_gate: Optional[threading.Lock] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        timeline: Optional[PipelineTimeline] = None,
    ) -> None:
        self.timeline = timeline or PipelineTimeline()
        self._write_gate = write_gate if write_gate is not None else threading.Lock()
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="audience-p5",
        )
        self._reply_text: Optional[str] = None
        self._reply_persisted = False
        self._parallel_futures: Dict[str, Future] = {}
        self._mindreading_future: Optional[Future] = None
        self._closed = False

    # ── parallel independent calls ──────────────────────────────────────

    def start_parallel(self, jobs: Mapping[str, Callable[[], Any]]) -> Dict[str, Future]:
        """并发发出不依赖回话输出的调用；时序日志记每条 issued。"""
        if self._closed:
            raise RuntimeError("pipeline 已关闭")
        for name, job in jobs.items():
            self.timeline.log(EVT_PARALLEL_ISSUED, job=name)
            self._parallel_futures[name] = self._executor.submit(self._run_parallel_job, name, job)
        return dict(self._parallel_futures)

    def _run_parallel_job(self, name: str, job: Callable[[], Any]) -> Any:
        try:
            return job()
        finally:
            self.timeline.log(EVT_PARALLEL_COMPLETE, job=name)

    def wait_job(self, name: str, timeout: Optional[float] = None) -> Any:
        if name not in self._parallel_futures:
            raise KeyError(f"无并行任务：{name}")
        return self._parallel_futures[name].result(timeout=timeout)

    def collect_parallel(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, fut in self._parallel_futures.items():
            out[name] = fut.result(timeout=timeout)
        return out

    # ── minister reply streaming ────────────────────────────────────────

    def stream_reply(
        self,
        produce: Callable[[Callable[[str], None]], str],
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """跑回话流式 producer。首 token 记入时序；返回完整回话正文。"""
        if self._closed:
            raise RuntimeError("pipeline 已关闭")
        first = {"seen": False}

        def _emit(delta: str) -> None:
            if not first["seen"] and str(delta or ""):
                first["seen"] = True
                self.timeline.log(EVT_REPLY_FIRST_TOKEN, delta=str(delta)[:32])
            if on_delta is not None:
                on_delta(delta)

        reply = str(produce(_emit) or "")
        self._reply_text = reply
        self.timeline.log(EVT_REPLY_COMPLETE, length=len(reply))
        return reply

    # ── persist + visible ───────────────────────────────────────────────

    def persist_reply(self, persist_fn: Callable[[str], Any]) -> Any:
        """回话完成后持久化。读心闸门只在此后打开。"""
        if self._reply_text is None:
            raise RuntimeError("回话尚未完成，不能持久化")
        result = self.write_under_gate(lambda: persist_fn(self._reply_text or ""))
        self._reply_persisted = True
        self.timeline.log(EVT_REPLY_PERSISTED, length=len(self._reply_text or ""))
        return result

    def accept_persisted_reply(self, reply: str) -> None:
        """生产路径已完成流式+落库后，把完整回话交给本状态机（公开 API，非私改字段）。"""
        text = str(reply or "")
        if not text.strip():
            raise ValueError("读心输入必须含该轮完整回话；回话正文为空")
        self._reply_text = text
        self._reply_persisted = True
        self.timeline.log(EVT_REPLY_COMPLETE, length=len(text), source="accept_persisted")
        self.timeline.log(EVT_REPLY_PERSISTED, length=len(text), source="accept_persisted")

    def mark_reply_visible(self) -> None:
        """回话对玩家可见——不等读心。消除「为读心黑屏」。"""
        if not self._reply_persisted:
            raise RuntimeError("回话尚未持久化，不能标记可见")
        self.timeline.log(EVT_REPLY_VISIBLE)

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

        def _run() -> Any:
            self.timeline.log(EVT_MINDREADING_ISSUED, reply_len=len(reply))
            try:
                result = job(reply)
            except Exception as exc:
                self.timeline.log(EVT_MINDREADING_FAILED, error=str(exc))
                raise
            self.timeline.log(EVT_MINDREADING_COMPLETE)
            return result

        self._mindreading_future = self._executor.submit(_run)
        return self._mindreading_future

    # ── thread-safe DB write ────────────────────────────────────────────

    def write_under_gate(self, fn: Callable[[], Any]) -> Any:
        """后台生成完成后的 DB 写走 write_gate，防并发写锁冲突。"""
        with self._write_gate:
            self.timeline.log(EVT_DB_WRITE)
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


def return_report_applicable(character: object, message: str) -> bool:
    """回奏是否适用本轮问话（不依赖回话输出 → 可并行发出）。"""
    from ming_sim.mindreading import is_inner_court_attendant

    text = str(message or "")
    return bool(
        is_inner_court_attendant(character)
        and any(word in text for word in RETURN_REPORT_KEYWORDS)
    )


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
    timeline: Optional[PipelineTimeline] = None,
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
            if timeline is not None:
                timeline.log(EVT_DB_WRITE, kind="mindreading")
            # 撤回安全（ADR 0038）：写前校验目标轮仍存活；failed/undone 不写孤儿
            if hasattr(db, "conn"):
                row = db.conn.execute(
                    "SELECT status FROM chat_turns WHERE id=?",
                    (int(chat_turn_id),),
                ).fetchone()
                if row is not None:
                    status = str(row["status"] if hasattr(row, "keys") else row[0] or "")
                    if status in {"failed", "undone"}:
                        return payload
            db.record_mindreading(int(chat_turn_id), payload)
    return payload


def assert_p5_order(timeline: PipelineTimeline) -> None:
    """测试助手：校验 P5 不可违背的先后。"""
    names = timeline.names()
    if EVT_MINDREADING_ISSUED in names:
        if EVT_REPLY_COMPLETE not in names:
            raise AssertionError("读心发出时回话尚未完成")
        if EVT_REPLY_PERSISTED not in names:
            raise AssertionError("读心发出时回话尚未持久化")
        reply_t = timeline.first(EVT_REPLY_COMPLETE)
        persist_t = timeline.first(EVT_REPLY_PERSISTED)
        mind_t = timeline.first(EVT_MINDREADING_ISSUED)
        assert reply_t is not None and persist_t is not None and mind_t is not None
        if mind_t.t < reply_t.t:
            raise AssertionError("读心请求早于回话完成")
        if mind_t.t < persist_t.t:
            raise AssertionError("读心请求早于回话持久化")
    if EVT_REPLY_FIRST_TOKEN in names and EVT_MINDREADING_ISSUED in names:
        first = timeline.first(EVT_REPLY_FIRST_TOKEN)
        mind = timeline.first(EVT_MINDREADING_ISSUED)
        assert first is not None and mind is not None
        if mind.t < first.t:
            raise AssertionError("读心不得先于回话首 token")
    if EVT_REPLY_VISIBLE in names and EVT_REPLY_PERSISTED in names:
        vis = timeline.first(EVT_REPLY_VISIBLE)
        per = timeline.first(EVT_REPLY_PERSISTED)
        assert vis is not None and per is not None
        if vis.t < per.t:
            raise AssertionError("可见标记不得早于持久化")
