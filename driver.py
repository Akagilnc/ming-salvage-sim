"""探针 driver —— 确定性结算入口（step1）。

形态(1) 我在对话里直接当 runtime+LLM：自产邸报叙事 + 中文 schema 形态的稀疏 delta，
driver 负责把 delta 规范化后跑引擎的确定性结算核（pre_settle + settle_with_delta），
绕过引擎自带的 extractor / 章节记忆 LLM 步。真实流程与本 driver 共用同一结算核（ADR 0004）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ming_sim.applier import Provenance
from ming_sim.context import bind_content
from ming_sim.decree import (
    atomic_and_reload,
    persist_resolve_context,
    pre_settle,
    settle_with_delta,
)
import ming_sim.issues as issues_mod
from ming_sim.issues import apply_score_extraction, validate_delta_shape as _validate_delta_shape
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.models import LLMConfig
from ming_sim.simulation import canonicalize_extraction
from ming_sim.token_stats import tlog

# 绝对路径锚 repo 的 data/probe.db：相对路径会按 cwd 解析，从非 repo 根跑 driver 时静默开错/
# 新建空库（codex-P2d，#17）。用 __file__ 锚定，cwd 无关。
DEFAULT_DB = str(Path(__file__).resolve().parent / "data" / "probe.db")

# 探针 driver 显式确定性(#54 / ADR-0004):对话里的我已是 LLM、自产完整 delta,落库核绝不该
# 再 spawn 第二个 LLM 做 issue/office enrichment。传 channel=api 空配置 → cli_backend_active
# 恒 False(见其首个分支),屏蔽所有 CLI-gated LLM 调用,**含 legacy MING_SIM_LLM_BACKEND env
# 回落**;且不触发任何 API 调用(enrichment/office 推断纯 CLI-gated,api 通道直接跳过)。
_DETERMINISTIC_LLM = LLMConfig(api_key="", base_url="", model="", channel="api")

# delta 容器/二级类型处理的单一真源已抽到 ming_sim.issues.validate_delta_shape/sanitize_delta_shape(#57/#63):
# driver 在 pre_settle 前只让不可拆形状（顶层非 dict/未知顶层字段）响亮失败；
# 可拆坏项由 persist_resolve_context 逐项拒收留痕并保存净化版，apply_score_extraction 自身也兜底。
# 注:真实流的 delta 由 extractor 在 pre_settle 之后才产出,故 apply 内的校验拦不住 pre_settle 那段
# 财政 tick 的半落库——那段的彻底原子化属事务边界(原 issue #3,已由 ADR 0008 落地,见
# applier.atomic / 下方 run_settle 的 atomic_and_reload),非本校验能廉价覆盖。


def open_game(db_path: str = DEFAULT_DB):
    """打开存档：load content + bind + GameDB + load_state。返回 (db, state, content)。

    缺库响亮失败：driver 只在既有探针存档上结算，绝不静默 sqlite3.connect 新建空库——否则
    load_state 得退化盘面、玩家不知开错档（codex-P2d，#17）。新开局走正式建档路径，非本工具。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"存档不存在：{db_path}（driver 只在既有探针存档上结算，不静默新建空库；"
            f"从 repo 根运行或用 --db 指向真实存档）"
        )
    # 存在但非真存档（空文件/非 SQLite/缺 game_state id=1/静态盘面空）也须响亮失败：否则 GameDB.
    # init_schema + load_state 会把它静默补成退化新局，玩家不知开错档（codex-P2d / R1 medium）。
    # 只看 game_state id=1 不够：旧 bug 在空库上调过 load_state 会写 id=1，但静态盘面（regions/
    # characters）只在 GameSession.seed_static_data 路径写——这种退化库仍须拒（codex R1 P2）。
    # 只读(mode=ro)探一下，不 mutate：需 game_state id=1 且 regions 表有数据。
    import sqlite3 as _sqlite3
    # 路径经 as_uri() 正确百分号编码再拼 query：裸 f"file:{db_path}?mode=ro" 遇路径含 ?/#/空格 等
    # URI 特殊字符会误解析（codex R2 P3）。as_uri 要求绝对路径，先 resolve。
    _ro_uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    try:
        _probe = _sqlite3.connect(_ro_uri, uri=True)
        try:
            _has_save = bool(
                _probe.execute("SELECT 1 FROM game_state WHERE id=1").fetchone()
                and _probe.execute("SELECT 1 FROM regions LIMIT 1").fetchone()
            )
        finally:
            _probe.close()
    except _sqlite3.Error:
        _has_save = False
    if not _has_save:
        raise ValueError(
            f"{db_path} 不是有效探针存档（缺 game_state id=1 或静态盘面 regions 为空）：driver 不在"
            f"空库/非存档/退化 SQLite 上结算。新开局走正式建档（GameSession），非本工具。"
        )
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    db = GameDB(db_path, content)
    state = db.load_state()
    return db, state, content


def _print_state(state) -> None:
    print(f"回合 turn={state.turn}  纪年={state.year}年{state.period}月")
    metrics = getattr(state, "metrics", None) or {}
    if metrics:
        print("国势：" + "  ".join(f"{k}={v}" for k, v in metrics.items()))


def _dump_board(db, state) -> None:
    """盘面快照：当前回合 + 各地区民心/动乱/城防炮。"""
    _print_state(state)
    print("\n地区：")
    rows = db.conn.execute(
        "SELECT id, public_support, unrest, cannon FROM regions ORDER BY id"
    ).fetchall()
    for r in rows:
        print(f"  {r['id']}：民心{r['public_support']} 动乱{r['unrest']} 城防炮{r['cannon']}门")


def run_settle(db, state, content, raw_delta, *, narrative="", decree_text="", registry=None,
               source: Provenance = Provenance.player_decree) -> str:
    """收一份中文 schema 形态的稀疏 delta（+ 我产的邸报 narrative / 诏书 decree_text）→
    规范化（中文 key→英文 canonical）→ pre_settle（财政 tick + auto_trigger）→
    settle_with_delta（落库→inertia→结局→推进），推进一回合。返回结算报告文本。

    source 默认 player_decree：探针每回合即皇帝下旨之结算，其落库拒收对玩家可见（邸报给一句
    in-world 提示，ADR 0008 决定 5）。纯世界推演回合可由信封传 source=system_simulation 静默。

    narrative 落 turn_logs/turn_reports 作下月前文 + 玩家邸报；canonical delta 先落
    pending_resolve_context 作重跑真源，turn_extractions.extractor_output 存 applied
    结果供玩家明细/timeline 读取。
    章节记忆 / 结局总评不注入（driver 无 llm_config），由对话里的我另行产出。
    畸形 delta 抛 `ValueError`（库语义）；CLI 由 `main()` 转退出码。
    """
    # public 边界:None 当空回合;falsy/非 dict([]/""/0/str)不静默吞成空结算照样推进(codex-P1a)。
    if raw_delta is None:
        raw_delta = {}
    if not isinstance(raw_delta, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(raw_delta).__name__}")
    extracted = canonicalize_extraction(raw_delta)
    _validate_delta_shape(extracted)  # 崩前拦畸形/未知字段,避免 pre_settle 动 DB 后半落库(RT-1/P1b)
    before_turn = state.turn
    # 与真实流程同核同位（ADR 0004/0008，引擎也在 pre_settle 后才 persist）：settle 前把
    # canonical delta 持久化为重跑真源。turn_extractions 在 settle 内部写 applied
    # 玩家可见结果；崩在 settle 内时若无 context 行，财政已落账而 delta 只活在调用方易失上下文（违 P1）。位置必须在
    # pre_settle 之后：ready=1 统一意为「前半段已提交，只剩 settle」，恢复入口直入 apply
    # 不会跳过未跑的财政 tick（cmr S2+S3 r5）。settle 尾部 clear 自然清掉。
    # 两步同事务（PR #90 R1 codex P2 同窗，与引擎 resolve_directives 同修）：崩在
    # Freeze the roster-write authority represented by this batch before settlement mutates DB.
    dossier_ids_at_input = {
        int(row["id"]) for row in db.list_decree_dossiers_for_simulation(before_turn)
    }
    # 「settling 已提交、context 未落」的窗口=违背「settling ⟹ context 可见」不变式。
    with atomic_and_reload(db, state, content=content, registry=registry):
        pre_settle(state, db)
        extracted = persist_resolve_context(
            db, before_turn, extracted,
            decree_text=decree_text, narrative=narrative,
            simulator_payload={
                "decree_dossiers": [
                    {"id": dossier_id} for dossier_id in sorted(dossier_ids_at_input)
                ],
            },
            secret_orders=[], relevant_memories=[],
            source=source,  # 持久化来源，崩溃恢复重放据此还原（#144）
        )
    report = settle_with_delta(
        state,
        db,
        extracted,
        before_turn=before_turn,
        content=content,
        registry=registry,
        narrative=narrative,
        decree_text=decree_text,
        extractor_output=json.dumps(extracted, ensure_ascii=False),
        source=source,  # 拒收来源（决定玩家面邸报提示，ADR 0008 决定 5）
        # 注入确定性 applier:落库不走 legacy env CLI enrichment,driver 纯确定性(#54)。
        delta_applier=lambda d, s, ex, ct, rg: apply_score_extraction(
            d, s, ex, content=ct, registry=rg, llm_config=_DETERMINISTIC_LLM,
            dossier_ids_at_input=dossier_ids_at_input,
        ),
    )
    # settle 成功推进后才记审计：driver 不注入 chapter_recorder（无 llm_config，章节记忆由对话方另产），
    # 留一条痕迹便于事后查「哪回合没记起居注」（忘补=静默缺口，#19）。须在 settle 成功之后——
    # 若 settle 中途 SettlementAbort/ValueError，回合未推进、可重试，不该误记一条「已跳章节记忆」
    # 的未完成回合（codex PR#133 P3）。
    tlog(f"[driver] 跳过章节记忆(driver 模式)，turn {before_turn}→{before_turn + 1}（章节记忆由对话方另产）")
    return report


def main(argv=None, *, game=None) -> int:
    """CLI 入口：state（打印盘面）/ settle --delta <json>（注入 delta 结算）/ dump（盘面快照）。

    game=(db,state,content) 可注入（测试用）；否则按 --db 打开存档。
    库层校验抛 ValueError，CLI 在此 catch、打到 stderr、返回退出码 1（不让 ValueError 透到用户）。
    """
    parser = argparse.ArgumentParser(prog="driver", description="探针确定性结算 driver")
    parser.add_argument("--db", default=DEFAULT_DB, help="存档路径")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state", help="打印当前盘面（回合/纪年/国势）")
    p_settle = sub.add_parser("settle", help="注入 delta JSON 跑确定性结算并推进一回合")
    p_settle.add_argument("--delta", required=True, help="中文 schema delta 的 JSON 文件路径")
    sub.add_parser("dump", help="盘面快照（回合 + 各地区民心/动乱/城防炮）")
    args = parser.parse_args(argv)

    db, state, content = game if game is not None else open_game(args.db)

    if args.cmd == "state":
        _print_state(state)
        return 0
    if args.cmd == "settle":
        with open(args.delta, encoding="utf-8") as f:
            obj = json.load(f)
        # 信封形态 {narrative, decree_text, delta, source?}（我每回合的完整产出）;否则裸 delta（兼容）。
        source = Provenance.player_decree
        if isinstance(obj, dict) and "delta" in obj:
            raw_delta = obj["delta"]
            narrative = str(obj.get("narrative") or "")
            decree_text = str(obj.get("decree_text") or "")
            # 信封可显式标来源（纯世界推演回合传 system_simulation 静默拒收提示）；非法值回落默认。
            _raw_src = str(obj.get("source") or "").strip()
            if _raw_src:
                try:
                    source = Provenance(_raw_src)
                except ValueError:
                    source = Provenance.player_decree
        else:
            raw_delta, narrative, decree_text = obj, "", ""
        # run_settle 抛 ValueError（畸形/未知/非 dict delta，含信封 delta 非 object）→ CLI 转退出码。
        try:
            report = run_settle(
                db, state, content, raw_delta, narrative=narrative, decree_text=decree_text,
                source=source,
            )
        except ValueError as exc:
            print(f"settle 失败：{exc}", file=sys.stderr)
            return 1
        print(report)
        return 0
    if args.cmd == "dump":
        _dump_board(db, state)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
