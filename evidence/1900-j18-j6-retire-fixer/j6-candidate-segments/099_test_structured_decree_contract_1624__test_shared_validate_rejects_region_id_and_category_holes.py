def test_shared_validate_rejects_region_id_and_category_holes(game, monkeypatch):
    """共同 assemble/validate 最低可证层：钉原洞 typed 拒绝。

    class1 原洞 = 非 region + national 夹带 region_id（旧闸只拒 scope==none）；
    class2 原洞 = 非 assignment 非空非法类别（旧闸闭集只罩 assignment）；
    action_alias_conflict = action_type 与 dossier_action_type 双非空且不同。
    #1778：动作×national 白名单已取消，national 只受 8×3 矩阵约束。
    """
    from ming_sim import cli_backend as cb

    db, state, content = game

    def create(payload):
        data = {
            **payload, "拟旨意图": "拟旨", "动作类型": payload["action_type"],
            "目标类型": payload["target_kind"], "目标ID": payload["target_id"],
            "地区ID": payload.get("region_id", ""), "事务类别": payload.get("transaction_category", ""),
            "施行范围": payload.get("locality_scope", "none"), "颁布方式": "普通",
            "承办人": payload.get("assignee", ""), "参与人": [dict(item) for item in _OWNER_ROSTER],
            "期限月数": 3,
        }
        monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (json.dumps(data), 1))
        return cb.extract_draft_intent_with_roster_heal("拟旨", "准入样本", db=db, content=content)

    with pytest.raises(StructuredDecreeCombinationError):
        create({
            "action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "national",
            "region_id": "shaanxi",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        create({
            "action_type": "military_order",
            "target_kind": "army",
            "target_id": "xuanfu",
            "locality_scope": "none",
            "assignee_name": "祖大寿",
            "transaction_category": "INVALID",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        create({
            "action_type": "punishment",
            "target_kind": "character",
            "target_id": "毕自严",
            "locality_scope": "none",
            "transaction_category": "INVALID",
        })
    # 双非空动作身份冲突：默认 validate 入口 typed 拒绝，failed_fields 含两键
    with pytest.raises(StructuredDecreeCombinationError) as ei:
        create({
            "action_type": "assignment",
            "dossier_action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "none",
            "transaction_category": "督赈",
        })
    assert ei.value.failed_fields == frozenset(
        {"action_type", "dossier_action_type"}
    )
    # 同值或一侧空：维持现状（不因 alias 比较误伤）
    same = create({
        "action_type": "policy",
        "dossier_action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "none",
    })
    assert same["action_type"] == "policy"
    only_action = create({
        "action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "none",
    })
    assert only_action["action_type"] == "policy"
