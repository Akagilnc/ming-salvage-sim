# 0088: 人口单位统一「人」，与 manpower 同刻度

Status: Proposed（2026-07-07 #477 设计闸 grill Q3 用户拍选项 1；用户原提「千」，采「人」以消换算面）

人口量全线以**裸人数「人」**为存储单位：classes.population（含新增流民）、regions.population 由「万人」改「人」，与 armies.manpower（已是人）同刻度——流民↔兵源转移账两端**零单位换算**（拆掉万/人 10 倍事故面；早期贼伙数千人级从此可记账）。展示层负责换算：皇帝看到的仍是「约八百五十万口」定性/万级叙事（P4 不动）。DELTA_SCHEMA 的数量字段单位契约、extractor 提示与接口层 TSV 同步改口径；content 静态 seed（classes/regions 人口量）随之机械换算（万→人，×10⁴——不换算则开局人口缩水万倍）。旧档不迁移、新档生效（substrate cutover 先例）；旧档读写按存档口径走 legacy，不混刻度。
