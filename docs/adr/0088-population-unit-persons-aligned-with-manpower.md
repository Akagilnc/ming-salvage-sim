# 0088: 人口单位统一「人」，与 manpower 同刻度

Status: Accepted（PR #663 merged 2026-07-07；决策：2026-07-07 #477 设计闸 grill Q3 用户拍选项 1；用户原提「千」，采「人」以消换算面；局部失效见下方后出注记）

#1889 废止下文「无标旧档按万人读写与展示、content 人口 ÷10⁴」这一条。人口核算只按「人」。不迁移、不删除既存存档；无标不再改判万人。2026-07-07 的「人」刻度决定仍有效。Owner 源卷 uuid `64b7aa45-8865-4d2d-9495-dd1925545a08`。

人口量全线以**裸人数「人」**为存储单位：classes.population（含新增流民）、regions.population 由「万人」改「人」，与 armies.manpower（已是人）同刻度——流民↔兵源转移账两端**零单位换算**（拆掉万/人 10⁴ 倍换算事故面；早期贼伙数千人级从此可记账）。展示层负责换算：皇帝看到的仍是「约八百五十万口」定性/万级叙事（P4 不动）。DELTA_SCHEMA 的数量字段单位契约、extractor 提示与接口层 TSV 同步改口径；**content 全部人口量静态数据**随之机械换算（万→人，×10⁴）——含 classes/regions seed **与事件效果/夹具里的 population delta**（events.json `effect_on_trigger` 之类，如华北大疫 -40），漏迁任一处即开局人口或事件减员缩水万倍。旧档不迁移、新档生效（substrate cutover 先例）；旧档读写按存档口径走 legacy，不混刻度——**口径判别必须持久化在存档 DB 内**（新档落 population_unit/schema 版本标，无标即按「万人」legacy 读写与展示；不得依赖 content 元信息判别，其不随档持久化）。

〔后出注记（#1835，2026-10-11）：上文旧档 legacy 读写、无标按万人分流及服务该判别的持久标要求，由后出「不考虑旧存档兼容」决定及本次裁判取代，不再适用；人口统一为人、静态数据换算及呈现口径等决定继续有效。〕
原话真源：`~/.claude/projects/-Users-akagilnc-WorkSpace-Ming-LLM/a45c2e6b-8c9a-4f56-85fb-73324ee40299.jsonl`，uuid `64b7aa45-8865-4d2d-9495-dd1925545a08`（`attachment.prompt`，`origin.kind=human`）：「我早就说过无数次了！不考虑旧存档兼容，以前不，现在不，以后也不，除非哪天我明确说要考虑才开始考虑」。
本判指针：`~/.ak-roles/books/Ming_LLM/1835/runs/01a12a79-240f-7f7e-83ab-c7a65c87a70c@judge/history.jsonl` 末条裁决。
