"""关系摘要层 S5：月末增量重酿腿（#636，ADR 0080/0083 一脉）。

两段式摘要＝奠基段（机械保留、只增不改）＋近况段（每次增量重酿整段重写）。
本模块只负责选中判据、酿制输入/输出契约与持久化编排；不解析 LLM 自由散文的
语义（ADR 0142）——结构化后果只走显式 JSON 契约通道；对产出零裁剪零 clamp
（庭裁 r1 F2），长度约束只走 prompt 正向输入契约。

编排约束：
- 选中判据＝该 settled 年月新增边事件（id > 水位）∨ 存在 pending（庭裁 r1 F1）——
  历史月份的未酿旧事件不得选中无本月新事件的关系（「本月新增」总判据）。
- 认领先行（庭裁 r2/r3 F1）：入选关系在酿造开始前先作 durable claim（pending 落盘）
  ——生产路径在结算事务内与本月边事件同生共死；任意缝崩溃→pending 在册→下次
  结算补酿。pending 不靠失败后 catch 补记。
- 输入依赖边界（ID-10）：本月边事件集定型后方启酿；腿内批内条目无依赖必并行（P5）；
  生产路径由 settle_with_delta 把 brew() 放进唯一一条受管 Future，使 LLM 等待与无
  依赖的 chapter/ending 等后处理重叠，摘要持久化前 join、异常路排空丢弃。
- 异常边界（ADR 0005/0008）：prepare/persist 两段是 DB 相——claim/apply/mark 的
  DB/schema/程序错误响亮上抛，绝不降级。brew() 段按**结构位置**分界而非异常类型：
  LLM 调用缝只收其声明类型 LLMUnavailable；解析/shape 校验缝只收输出结构化契约
  违约（LLMContractError/ValueError）；两段各自降级留痕（保旧摘要＋事件已在流水
  ＋认领已在册，不阻塞结算）。缝外的程序逻辑异常——含 _brew_fn 自身抛出的裸
  ValueError——一律响亮上抛，不用异常类型猜语义。
- 成功路径＝摘要写入与 pending 清除同一 DB 事务原子落定（庭裁 r2 F1）。
- settled 年月快照由 decree 在 next_period 之前取定并传入；一律不得直读 state 年月
  落款（直调路径回落调用时的 state——此时 state 仍指被结算的那个月）。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from ming_sim.agents import parse_agent_json
from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.models import GameState
from ming_sim.relations import EMPEROR_NODE
from ming_sim.token_stats import tlog

DIMENSION_JUNXIN = "君臣"
DIMENSION_DACHEN = "大臣"

# 酿制输出契约字段（显式结构化契约，非散文解析）。
FOUNDINGS_KEY = "new_foundings"
RECENT_KEY = "recent_segment"


def relation_dimension(source: str, target: str) -> str:
    """维度标记：任一端为皇帝节点即君臣边，否则大臣边。"""
    return DIMENSION_JUNXIN if EMPEROR_NODE in (source, target) else DIMENSION_DACHEN


def select_brew_targets(db: Any, *, year: int, period: int) -> List[Dict[str, Any]]:
    """选中判据（庭裁 r1 F1）：该 settled 年月新增边事件 ∨ pending。

    「本月新增」双条件：事件落在 settled 年月内、且 id 在该关系摘要水位之上——
    历史月份的旧事件不得把无本月新事件的关系选中。崩溃缝里本月已落库但未酿的
    事件（庭裁 r3 F1② fresh claim→durable pending 缝）重启后仍是新事件，仍被
    选中。既无本月新事件又无 pending 的关系不入选（TD-3 无事不变）。"""
    summaries = {
        (row["source"], row["target"]): row for row in db.get_relation_summaries()
    }
    pending = {
        (row["source"], row["target"]): row for row in db.get_relation_brew_pending()
    }
    latest_event_id: Dict[Tuple[str, str], int] = {}
    for row in db.conn.execute(
        "SELECT source, target, MAX(id) AS max_id FROM relation_edge_events "
        "WHERE year = ? AND period = ? GROUP BY source, target",
        (int(year), int(period)),
    ).fetchall():
        latest_event_id[(row["source"], row["target"])] = int(row["max_id"])

    targets: List[Dict[str, Any]] = []
    for pair in sorted(set(latest_event_id) | set(pending)):
        summary = summaries.get(pair)
        watermark = int(summary["last_event_id"]) if summary is not None else 0
        has_new_events = latest_event_id.get(pair, 0) > watermark
        has_pending = pair in pending
        if not (has_new_events or has_pending):
            continue
        targets.append({
            "source": pair[0],
            "target": pair[1],
            "dimension": relation_dimension(pair[0], pair[1]),
            "summary": summary,
            "watermark": watermark,
            "has_new_events": has_new_events,
            "has_pending": has_pending,
        })
    return targets


def collect_new_edge_events(db: Any, *, source: str, target: str, watermark: int) -> List[Dict[str, Any]]:
    """水位之上的新边事件（TD-4：重酿输入必含新事件；翻转可回溯的依据）。"""
    return [
        row
        for row in db.get_relation_edge_events(source=source, target=target)
        if int(row["id"]) > int(watermark)
    ]


def build_brew_input(
    *,
    source: str,
    target: str,
    dimension: str,
    year: int,
    period: int,
    summary: Optional[Dict[str, Any]],
    new_events: List[Dict[str, Any]],
    has_pending: bool,
) -> Dict[str, Any]:
    """单条关系的酿制输入（旧摘要＋新边事件＋当前年月，ADR 0083 口径）。"""
    return {
        "source": source,
        "target": target,
        "dimension": dimension,
        "year": int(year),
        "period": int(period),
        "founding_segment": str(summary["founding_segment"]) if summary else "",
        "recent_segment": str(summary["recent_segment"]) if summary else "",
        "new_events": [
            {
                "event_kind": event["event_kind"],
                "context": event["context"],
                "origin": event["origin"],
                "year": int(event["year"]),
                "period": int(event["period"]),
            }
            for event in new_events
        ],
        "has_pending_failure": bool(has_pending),
    }


def render_brew_user_payload(brew_input: Dict[str, Any]) -> str:
    """酿制 user payload：JSON 序列化的确定性输入（供 extractor 式缓存前缀复用）。"""
    return json.dumps(brew_input, ensure_ascii=False, sort_keys=False)


def parse_brew_output(raw: str, stage: str = "关系酿制") -> Dict[str, Any]:
    """酿制输出契约：{"new_foundings": [...], "recent_segment": "..."}。

    只验形不验义、零长度管辖（庭裁 r1 F2/r3 F2）：recent_segment 原样存储，
    不截断不 clamp；new_foundings 逐句原样追加。"""
    parsed = parse_agent_json(raw, stage)
    if not isinstance(parsed, dict):
        raise ValueError(f"{stage}: 酿制输出顶层不是 object")
    recent = parsed.get(RECENT_KEY)
    if not isinstance(recent, str):
        raise ValueError(f"{stage}: {RECENT_KEY} 缺失或不是字符串")
    foundings = parsed.get(FOUNDINGS_KEY, [])
    if not isinstance(foundings, list) or any(
        not isinstance(line, str) for line in foundings
    ):
        raise ValueError(f"{stage}: {FOUNDINGS_KEY} 必须是字符串列表")
    return {FOUNDINGS_KEY: list(foundings), RECENT_KEY: recent}


def merge_founding_segment(old_founding: str, new_foundings: List[str]) -> str:
    """奠基段机械只增不改（ID-9；P6/ADR 0142 零删改）：零解析零推断的合并。

    对旧段不做任何拆行/滤空/集合推断——「按行拆分＋候选各行都已在段内即判重」
    会把整条多行候选误删（机械反例：旧段 '甲\\n中\\n乙' 配候选 '甲\\n乙'，候选的
    每一行各自都在段内，行集合推断即把整条候选吞掉）。唯一两种机械操作：
    跨轮去重按庭裁 r5 收窄，唯一两种机械操作：①候选与整个旧段或本批已追加条目
    严格字节全等才跳过（补酿整段原样重报不重复记账）；②其余候选连同其内部换行、
    首尾空白逐字完整追加（以单个换行符接在段尾）——旧段内某个精确历史条目被再次
    报出时如实追加，接受有界重复噪声（酿制 LLM 读面自行消化），禁止条目级拆解去重。
    禁对任何字节做改写：空行、末尾换行、首尾空白全部原样。
    空字符串条目是结构空操作，跳过。"""
    old = str(old_founding)
    known = {old} if old else set()
    parts = [old] if old else []
    for item in new_foundings:
        text = str(item)
        if not text or text in known:
            continue
        known.add(text)
        parts.append(text)
    return "\n".join(parts)


class MonthEndRelationBrewLeg:
    """月末增量重酿腿的三段生命周期对象（ID-10/P5；settle_with_delta 单点编排）。

    prepare()＝DB 相（主线程、可在结算事务内运行）：选中、认领、备料。brew()＝LLM
    相（零 DB 访问，可放进 Future 与 chapter/ending 重叠跑）。persist()＝DB 相
    （主线程、必须在结算事务提交之后）：apply/mark 落定。异常边界（ADR 0005/0008）：
    DB/schema/程序错误在任何一段都响亮上抛；只有 brew() 内单条 LLM 调用或其结构化
    输出契约失败降级留痕。brew_fn(rendered_payload) -> LLM 原始文本（生产＝
    run_agent_text 闭包；测试注入确定性假手）。

    settled_turn/year/period＝被结算月份的快照（decree 在 next_period 之前取定
    传入）；None 时回落当前 state（直调路径，state 尚未推进）。"""

    def __init__(
        self,
        db: Any,
        state: GameState,
        brew_fn: Callable[[str], str],
        *,
        settled_turn: Optional[int] = None,
        settled_year: Optional[int] = None,
        settled_period: Optional[int] = None,
        max_workers: int = 4,
        parallel: bool = True,
    ) -> None:
        self._db = db
        self._brew_fn = brew_fn
        self._parallel = bool(parallel)
        self._max_workers = int(max_workers)
        # settled 年月快照：生产路径由 decree 在 next_period 之前取定传入；直调
        # （测试/探针）回落构造时的 state——此时 state 仍指被结算的那个月。
        self.turn = int(settled_turn) if settled_turn is not None else int(state.turn)
        self.year = int(settled_year) if settled_year is not None else int(state.year)
        self.period = int(settled_period) if settled_period is not None else int(state.period)
        self.jobs: List[Dict[str, Any]] = []
        self.outcomes: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[Exception]]] = []
        self.report: Dict[str, Any] = {
            "selected": 0,
            "brewed": [],
            "degraded": [],
            "skipped_events": 0,
        }

    def prepare(self) -> bool:
        """DB 相：选中＋认领先行＋备料。有入选关系返回 True（可启酿），否则 False。

        认领先行（庭裁 r2/r3 F1）：入选关系在酿造开始前先把 pending 落盘——生产
        路径在结算事务内与本月边事件同生共死；任意缝崩溃→pending 在册→下次结算
        补酿；pending 不靠失败后 catch 补记。本相任何 DB/schema/程序错误响亮上抛
        （ADR 0005/0008）：无 durable claim 就开酿会让失败月失去恢复凭据，宁可不酿。"""
        targets = select_brew_targets(self._db, year=self.year, period=self.period)
        self.report["selected"] = len(targets)
        if not targets:
            return False
        self._db.claim_relation_brew_targets(year=self.year, period=self.period)
        # 输入先串行备好（纯计算、确定性，不含 LLM 调用），brew() 才能零 DB 并行。
        jobs: List[Dict[str, Any]] = []
        for item in targets:
            new_events = collect_new_edge_events(
                self._db, source=item["source"], target=item["target"],
                watermark=item["watermark"],
            )
            jobs.append({
                **item,
                "new_events": new_events,
                "input": build_brew_input(
                    source=item["source"], target=item["target"],
                    dimension=item["dimension"], year=self.year, period=self.period,
                    summary=item["summary"], new_events=new_events,
                    has_pending=item["has_pending"],
                ),
            })
        self.jobs = jobs
        return True

    def _brew_one(self, job: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[Exception]]:
        # payload 备制是纯程序逻辑：其错误属代码侧错（ADR 0005），不在降级面内，
        # 响亮上抛。降级面按**结构位置**拆成两段独立 try（判词残留项：同一 try 包住
        # 调用与解析并捕裸 ValueError，会把 _brew_fn 自身的程序性 ValueError 吞成
        # 降级）——每段只收该结构位置可能合法产生的声明类型：
        # - LLM 调用缝：只收 LLMUnavailable（LLM 调用/接口失败的 typed 声明）；
        #   该段的 KeyError/TypeError/裸 ValueError 等属程序错，响亮上抛。
        # - 解析/shape 校验缝：只收输出结构化契约违约 LLMContractError（JSON 层）
        #   与 ValueError（shape 层，parse_brew_output 的声明类型）。
        payload = render_brew_user_payload(job["input"])
        try:
            raw = self._brew_fn(payload)
        except LLMUnavailable as exc:
            return job, None, exc
        try:
            parsed = parse_brew_output(raw)
        except (LLMContractError, ValueError) as exc:
            return job, None, exc
        return job, parsed, None

    def brew(self) -> None:
        """LLM 相：批内条目间无依赖必并行（P5）。零 DB 访问——可在 Future 中与
        chapter/ending 等无依赖后处理重叠（ID-10）；结果存 self.outcomes 待 persist。"""
        if not self.jobs:
            self.outcomes = []
            return
        if self._parallel and len(self.jobs) > 1:
            workers = max(1, min(int(self._max_workers), len(self.jobs)))
            tlog(f"[relation-brew] 批内并行酿制 {len(self.jobs)} 条关系（workers={workers}）")
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="relation-brew") as pool:
                self.outcomes = list(pool.map(self._brew_one, self.jobs))
        else:
            self.outcomes = [self._brew_one(job) for job in self.jobs]

    def persist(self) -> Dict[str, Any]:
        """DB 相（结算提交后）：逐条落定/降级留痕，返回机械报告。

        apply/mark 是摘要与 pending 真源的 DB 写——失败响亮上抛（ADR 0005/0008），
        绝不伪装成 LLM 单条失败；认领先行下 pending 凭据已持久，落定失败由外层
        响亮处置而非就地吞掉。"""
        report = self.report
        for job, parsed, exc in self.outcomes:
            source, target = job["source"], job["target"]
            if exc is not None or parsed is None:
                reason = str(exc) if exc is not None else "空结果"
                tlog(f"[relation-brew] {source}→{target} 酿制失败降级（保旧摘要）：{reason}")
                # 认领先行下 pending 已持久在册（不靠此处补记）；本写只刷新失败原因。
                self._db.mark_relation_brew_pending(
                    source=source, target=target, year=self.year, period=self.period,
                    reason=reason,
                )
                report["degraded"].append({"source": source, "target": target, "reason": reason})
                continue
            # 成功路径：摘要写入＋pending 清除同事务原子落定（庭裁 r2 F1）。
            # 奠基段只增不改在此拼定；近况段覆盖式幂等；水位推进到本批最大事件 id。
            last_event_id = max(
                [int(event["id"]) for event in job["new_events"]] + [int(job["watermark"])]
            )
            self._db.apply_relation_brew_result(
                source=source, target=target, dimension=job["dimension"],
                founding_segment=merge_founding_segment(
                    str(job["summary"]["founding_segment"]) if job["summary"] else "",
                    parsed[FOUNDINGS_KEY],
                ),
                recent_segment=parsed[RECENT_KEY],
                last_event_id=last_event_id,
                turn=self.turn, year=self.year, period=self.period,
            )
            report["brewed"].append({"source": source, "target": target})
            tlog(f"[relation-brew] {source}→{target} 酿制落定（pending 同事务清除）")
        return report


def run_month_end_relation_brew(
    db: Any,
    state: GameState,
    brew_fn: Callable[[str], str],
    *,
    max_workers: int = 4,
    parallel: bool = True,
    settled_turn: Optional[int] = None,
    settled_year: Optional[int] = None,
    settled_period: Optional[int] = None,
) -> Dict[str, Any]:
    """月末增量重酿腿（三段顺序合跑：prepare→brew→persist，直调/测试便利入口）。

    生产路径不经此函数：settle_with_delta 持有 Leg 三段生命周期，把 brew() 放进
    受管 Future 与 chapter/ending 重叠。返回机械报告。"""
    leg = MonthEndRelationBrewLeg(
        db, state, brew_fn,
        settled_turn=settled_turn,
        settled_year=settled_year,
        settled_period=settled_period,
        max_workers=max_workers,
        parallel=parallel,
    )
    if not leg.prepare():
        return leg.report
    leg.brew()
    return leg.persist()
