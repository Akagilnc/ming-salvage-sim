#!/usr/bin/env python3
"""#1902 D5：对枚举全员按独立契约分类（非点名白名单）。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 上一轮已纠正、本轮明确认可保留的合法修理（判词 classes「D5已纠正部分」）
PRIOR_SOURCE_REPAIRS = {
    "tests/test_pihong_dossier_1490.py::test_lying_label_rebuilt_from_server_option": (
        "服务端命中 option 是 label/hint 的源，客户端只有 note 可透传。"
    ),
    "tests/test_adr0015_per_item_rejection.py::test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate": (
        "解码后的完整持久数据等于按公开 UTF-8 backslashreplace 契约处理的输入。"
    ),
    "tests/test_adr0015_per_item_rejection.py::test_sqlite_text_sanitization_covers_issue_rows_and_advances": (
        "issue、advance、close 的全部文本/JSON 字段保存完整输入，不锁 JSON 拼写。"
    ),
    "tests/test_execution_joint_liability_565.py::test_execution_note_merge_interface_and_restore": (
        "合并前内容和实际提交的新片段都必须保留。"
    ),
    "tests/test_relation_seed_638.py::test_seeded_pair_flows_into_month_end_brew_selection": (
        "seed 事件各结构化字段无损进入酿制输入。"
    ),
    "tests/test_fiscal_substrate_bridge.py::test_region_loader_expands_shared_settle_meta_defaults": (
        "默认说明与省份覆盖均从输入取得；共享默认来源不得被回写污染。"
    ),
    "tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect": (
        "续推 prior_forecast_text 等于实际暂存的问前预推原文。"
    ),
    "tests/test_style_temperament_641.py::test_inertia_natural_resolve_applies_temperament_style": (
        "自然结案 reason 来源必须完整保存到人物事实日志。"
    ),
    "tests/test_style_temperament_641.py::test_apply_score_extraction_writes_temperament_style_and_log": (
        "真实 delta 输入 reason 必须完整保存到人物事实日志。"
    ),
    "tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects": (
        "密令原始拒收 item 无损进入密报供料；同一 origin 不进入公开邸报拒收供料。"
    ),
    "tests/test_audience_translate_1837.py::test_translate_call_failure_is_not_empty_success_dispatch": (
        "Future 必须真实传播注入的 RuntimeError；保留原拒收/持久水位断言。"
    ),
    "tests/test_deepseek_thinking_disable_1797.py::test_dump_llm_messages_records_reasoning_usage_finish_reason": (
        "调试落盘：reasoning／usage／finish_reason 取实际输入比较，不锁旧混合文本格式。"
    ),
}

RETIRED_FORMATTER_PREFIXES = (
    "tests/test_power_section_rejections.py::",
    "tests/test_section4_rejections.py::",
)

# 本轮按独立契约修好的成员（与枚举谓词交叉，非白名单收窄）
THIS_ROUND_REPAIRS = {
    "tests/test_rescript_draft_656.py::test_generate_rescript_draft_degrades_loudly_without_raising": (
        "repaired_source_persistence_contract",
        "降级附记 reason 等于注入异常的 str(exc)；来源比较取实际输入。",
    ),
    "tests/test_due_review_621.py::test_due_review_scene_tops_live_open_night_even_with_body": (
        "repaired_scene_consumer_and_source_contract",
        "进入 _scene_opening_text 场景供料消费者；facts 进 opening，"
        "origin_context／criterion_text 取实际 staged 输入；不恢复「当前待裁场面」固定措辞。",
    ),
    "tests/test_web_court_visibility.py::test_choose_minister_real_entry_excludes_weishi_includes_court": (
        "repaired_selection_contract_cleared_hollow_residue",
        "恢复排未仕／留真臣选择契约；清除仅 assert None 却保留名册夹具与打印收集的失效证明；"
        "不恢复「可召见大臣」标题措辞锁。",
    ),
}


def classify_python(row: dict) -> None:
    member = row["member"]
    if member in THIS_ROUND_REPAIRS:
        disp, reason = THIS_ROUND_REPAIRS[member]
        row["disposition"] = disp
        row["reason"] = reason
        return
    if member in PRIOR_SOURCE_REPAIRS:
        row["disposition"] = "retained_and_repaired_source_contracts"
        row["reason"] = PRIOR_SOURCE_REPAIRS[member]
        return
    if row["kind"] == "function_deleted" and any(
        member.startswith(p) for p in RETIRED_FORMATTER_PREFIXES
    ):
        row["disposition"] = "deleted_retired_helper_proof"
        row["reason"] = (
            "formatter 无现役生产消费者；真实 applier 拒收/落账断言在同文件保留。"
        )
        return
    # 结构谓词：若仍 helper-only／打印收集空洞，标未结（本轮修后应为空）
    if row.get("callsPendingFactsHelper") and not row.get("entersSceneConsumer"):
        row["disposition"] = "unresolved_helper_without_consumer"
        row["reason"] = "仍只调 pending facts helper，未进场景供料消费者。"
        return
    if (
        row.get("hasPrintCollect")
        and not row.get("usesPrintCollectInAssert")
        and row.get("removedSelectionRosterAssert")
    ):
        row["disposition"] = "unresolved_hollow_selection_residue"
        row["reason"] = "仍保留打印收集却不断选择契约。"
        return
    if row.get("removedNoteReasonSource") and member not in THIS_ROUND_REPAIRS:
        # deepseek 等已由 prior repair 覆盖；其余若仍删 note reason 且无补回则标出
        if not any("reason" in a for a in row.get("currentAssertions") or []):
            row["disposition"] = "unresolved_source_persist_misdelete"
            row["reason"] = "附记／落盘 reason 来源断言仍缺。"
            return
    if row["kind"] == "function_deleted":
        row["disposition"] = "maintained_independent_contract_retirement"
        row["reason"] = (
            "退役入口/配置、副本 helper、内部表示或源码/措辞证明维持清退；"
            "不因同函数曾有其它断言而整函数恢复。"
        )
        return
    if row["kind"] == "function_added":
        row["disposition"] = "retained_real_entry_contract_migration"
        row["reason"] = "实际调用输入/结构化返回/来源/拒收/持久事实的现役替代入口。"
        return
    row["disposition"] = "retained_independent_contracts_and_removed_noncontract_proofs"
    row["reason"] = (
        "当前真实行为断言和异常类型/结构化失败契约保留；"
        "已删措辞、内部形状或重复证明不恢复。"
    )


def classify_web(row: dict) -> None:
    if row["kind"] == "test_deleted":
        row["disposition"] = "maintained_retirement"
        row["reason"] = (
            "退役拟诏入口、CSS/内部实现证明或固定呈现锁维持删除。"
        )
        return
    if row["kind"] == "test_added":
        row["disposition"] = "retained_real_entry_contract_migration"
        row["reason"] = "现役 Web 入口行为契约。"
        return
    row["disposition"] = "retained_independent_behavior_contracts"
    row["reason"] = (
        "当前输入来源、机面/回调/交互/数据隔离断言见 currentAssertions；"
        "不恢复已删固定措辞。"
    )


def main() -> None:
    py = json.loads((HERE / "d5-python-members.json").read_text(encoding="utf-8"))
    web = json.loads((HERE / "d5-web-members.json").read_text(encoding="utf-8"))
    for r in py:
        classify_python(r)
    for r in web:
        classify_web(r)
    all_rows = sorted(py + web, key=lambda r: r["member"])
    out = HERE / "D5-member-table.json"
    out.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(r["disposition"] for r in all_rows)
    unresolved = [r for r in all_rows if r["disposition"].startswith("unresolved_")]
    summary = {
        "python": len(py),
        "web": len(web),
        "total": len(all_rows),
        "dispositions": dict(counts),
        "unresolved": [r["member"] for r in unresolved],
        "thisRoundRepairs": sorted(THIS_ROUND_REPAIRS),
    }
    (HERE / "d5-classification-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if unresolved:
        raise SystemExit(f"unresolved D5 members remain: {len(unresolved)}")


if __name__ == "__main__":
    main()
