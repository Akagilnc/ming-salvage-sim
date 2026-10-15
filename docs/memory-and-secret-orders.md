# 密令系统

章节／事件记忆已退役。人物经历、见闻与公开记录通过材料目录按身份授权读取（ADR 0155）；历月邸报存于 `公开说法/邸报/`。密令不通过公开材料目录泄露。

密令的结构化差务合同冻结在对应案卷的 `payload_json.covert_task_contract`；每月实况进度写 `dossier_actual_progress`，承办人密奏留在 `dossier_progress_json`。真实交付由前者决定，后者供玩家阅读。密令表 `secret_orders` 记录承办人、标题、内容、状态、结果与结案回合；同时 active 上限 20 条。

召对提出密令后，`session.py` 暂存 `pending_actions`；皇帝应允或结束回合默认同意时，`commit_pending_actions()` 同一事务写 active 密令、已颁密令案卷及差务合同。缺结构化差务类型时失败，不落空壳密令。

承办人逐月密奏不直接结案。月末按[密令选择合同](DELTA_SCHEMA.md#secret_order_updates--covert_exec_selections)记实况；到期后 `settle_due_secret_orders()` 按合同对账，`db.close_secret_order()` 记录结案。奏报不能改变世界状态。

月末公共推演只看公开的到期承诺，不预读密令正文。密令整月供料在 `month_chain._step_4a_secret_order_supply`（`build_secret_orders_supply_feed` → `run_secret_orders_supply`），**不经** `declaration_dispatch`/`settle_delta`：

- `dossier_progress_reports` → 直接 `db.record_monthly_dossier_progress`
- 披露 → `_apply_deferred_disclosures` 消费 `chain.pending_disclosures`（非供料产物上的披露字段）
- `covert_exec_selections` → 直接 `apply_monthly_covert_actual_progress`，随后 `settle_due_secret_orders`

执行态只从上述整月供料入口落账，不再接受世界段声明 effects 的执行态；`secret_dossier_participants` 由声明段 `entities.dossier.delta_section` 消费，4a 不读该键。旧五模块 `personnel_secret` extractor 包装已退役；字段名仍可标私密 provenance（#883）。披露事件才可使密令内容成为公开知识。
