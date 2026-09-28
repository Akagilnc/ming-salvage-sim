# 密令系统

章节／事件记忆已退役。人物经历、见闻与公开记录通过材料目录按身份授权读取（ADR 0155）；历月邸报存于 `公开说法/邸报/`。密令不通过公开材料目录泄露。

密令的结构化差务合同冻结在对应案卷的 `payload_json.covert_task_contract`；每月实况进度写 `dossier_actual_progress`，承办人密奏留在 `dossier_progress_json`。真实交付由前者决定，后者供玩家阅读。密令表 `secret_orders` 记录承办人、标题、内容、状态、结果与结案回合；同时 active 上限 20 条。

召对提出密令后，`session.py` 暂存 `pending_actions`；皇帝应允或结束回合默认同意时，`commit_pending_actions()` 同一事务写 active 密令、已颁密令案卷及差务合同。缺结构化差务类型时失败，不落空壳密令。

承办人逐月密奏不直接结案。月末从真实效果、案卷来源与执行判决累计实况；到期后 `settle_due_secret_orders()` 按合同对账，`db.close_secret_order()` 记录结案。奏报不能改变世界状态。

月末公共推演只看公开的到期承诺，不预读密令正文；密令分组仅进入 personnel_secret extractor 的独立轨。披露事件才可使密令内容成为公开知识（#883）。
