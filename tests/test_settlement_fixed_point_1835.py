"""#1835 F1 固定点验收：旧总入口与旧声明包装确已退出（ADR 0150 决定 6）。

本文件是**退役本身的**验收，不是行为测试——它钉的是「旧形状不再存在」这条
fixed-point 不变式。判词要求的「非只改名或改为空 dict」正由这里守：只改名的话
``issues.apply_score_extraction`` 仍在，本文件即红。
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]


def _python_sources(*subdirs: str):
    for sub in subdirs:
        yield from (REPO / sub).rglob("*.py")


def test_retired_entry_is_gone_from_issues_module():
    """旧单体入口整体退役，不留 deprecated 壳、不改名续命。"""
    import ming_sim.issues as issues

    assert not hasattr(issues, "apply_score_extraction")
    assert not hasattr(issues, "_apply_score_extraction_body")
    assert not hasattr(issues, "_apply_extracted_army_delta")


def test_no_production_module_still_calls_retired_entry():
    """生产代码不得再引用旧入口（含注释外的任何真实调用）。"""
    offenders = []
    for path in _python_sources("ming_sim", "scripts"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None
            )
            if name == "apply_score_extraction":
                offenders.append(f"{path.relative_to(REPO)}:{node.lineno}")
    assert offenders == [], f"旧入口仍有生产调用点：{offenders}"


def test_no_module_imports_retired_entry():
    offenders = []
    for path in _python_sources("ming_sim", "scripts", "tests"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if (alias.asname or alias.name) == "apply_score_extraction":
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno}")
    assert offenders == [], f"旧入口仍被导入：{offenders}"


def test_old_recursive_rejection_bridge_is_gone():
    """旧递归桥接（含其硬编码特例）随固定点删除。"""
    import ming_sim.decree as decree

    assert not hasattr(decree, "_collect_inline_rejections")


def test_outcome_carries_no_legacy_compat_keys():
    """旧 39 键 dict 的病灶——恒空兼容键与双份键——不在 typed 结果上复活。"""
    from ming_sim.settlement import SettlementOutcome

    fields = set(SettlementOutcome.__dataclass_fields__)
    for dead in (
        "appointments", "character_status_changes", "character_power_changes",
        "office_changes",          # 恒空兼容键（#1835 F1 随 C0 声明契约退役）
        "person_changes",          # 双份键（输入回声）
        "world_advance",           # 纯输入透传，无消费端
        "economy_moves_rejections", "faction_delta_rejections",
        "class_delta_rejections", "population_transfers_rejections",
        "surcharge_decrees_rejections",   # 独立拒收键（拒收单一形状）
        "validate_shape_rejections",       # 框架前置闸产物，不经段落格
        "module_misroute_rejections",
        "issue_summary", "secret_order_closes", "pairing_warnings",
    ):
        assert dead not in fields, f"旧键 {dead} 复活成 typed 字段"


def test_registry_is_the_single_source_of_section_order():
    """段序真源是有序登记表，不是编排器里的注释或代码位置。"""
    from ming_sim.settlement import registry

    specs = registry.section_specs()
    assert [s.ordinal for s in specs] == sorted(s.ordinal for s in specs)
    # 人物 pre 必在局势段前、post 必在其后（段序约束可审的数据化）。
    order = {s.name: s.ordinal for s in specs}
    assert order["person_pre"] < order["issue"] < order["person_post"]
    # 财政三段 removes → creates → changes。
    assert order["fiscal_removes"] < order["fiscal_creates"] < order["fiscal_changes"]
    # 哭谏先于一切（原约束只在注释里）。
    assert order["breach_plea"] == min(order.values())


def test_registry_delta_keys_cover_all_landing_sections():
    """登记表承接声明字段真源职责：无主字段会静默缩键，故派生视图须覆盖它们。"""
    from ming_sim.settlement import registry
    from ming_sim.simulation import DECLARATION_EFFECT_FIELDS

    declared = set(DECLARATION_EFFECT_FIELDS)
    registered = set(registry.delta_keys()) | set(registry._FRAMEWORK_KEYS)
    # 旧四人物键已随 C0 声明契约退役，不在现行字段契约里，故不要求登记。
    assert declared - registered == set(), (
        f"声明字段无段落登记：{sorted(declared - registered)}"
    )


def test_views_module_is_not_a_dict_compat_shim():
    """具名视图是 typed 投影，不得复活 ``[]`` 取键的 dict 兼容层。"""
    from ming_sim.settlement import outcome as outcome_mod
    from ming_sim.settlement import views

    assert not hasattr(outcome_mod.SettlementOutcome, "__getitem__")
    assert not hasattr(outcome_mod.SettlementOutcome, "get")
    # 视图标签有闭集：多一个标签即多一条无主投影。
    assert "fiscal_creates" in views.view_keys()


def test_declared_effect_fields_is_derived_from_registry_not_duplicated():
    """ADR 0150 决定 4：登记表承接字段真源后，``DECLARATION_EFFECT_FIELDS``
    必须是**派生视图**而非第二份手写键集——手写则登记表新增段会静默缩键。

    此处钉住派生结果的键集与容器类型：键集＝登记表（落库段 + 框架段），
    容器类型＝声明形状契约。两者任一漂移即红。
    """
    from ming_sim.settlement import registry
    from ming_sim.simulation import DECLARATION_EFFECT_FIELDS

    assert set(DECLARATION_EFFECT_FIELDS) == set(registry.delta_keys()) | set(
        registry._FRAMEWORK_KEYS
    )
    # 无恒空容器：每个键都给出真实容器类型（dict / list），只有 emperor_fate
    # 是标量（崇祯结局字段，值域 abdicate/suicide/null）。
    scalars = {
        key for key, container in DECLARATION_EFFECT_FIELDS.items()
        if container is None
    }
    assert scalars == {"emperor_fate"}


def test_victory_status_is_set_on_typed_outcome(game):
    """结局判定上浮为 typed 附加结果，且 frozen 结果不被就地改写。

    旧实现给 frozen dataclass 赋属性会在真结局（退位/自尽）时抛
    FrozenInstanceError——常规月（ongoing）走不到那条分支，故须专门钉。
    """
    from ming_sim.settlement import SettlementContext, settle_delta

    db, state, content = game
    outcome = settle_delta(
        state, db, {"emperor_fate": "abdicate"}, SettlementContext(content=content),
    )
    assert outcome.victory_status is not None
    assert outcome.victory_status["status"] == "emperor_abdicate"


def test_ongoing_outcome_carries_no_victory_status(game):
    """ongoing 不入 victory_status（与旧报告同口径：只有非 ongoing 才带）。"""
    from ming_sim.settlement import SettlementContext, settle_delta

    db, state, content = game
    outcome = settle_delta(state, db, {}, SettlementContext(content=content))
    assert outcome.victory_status is None
