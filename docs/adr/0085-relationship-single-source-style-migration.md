# 0085: 关系唯一真源在边引擎——style 迁出关系层

Status: Proposed（决策：2026-07-06 #479 设计闸 grill Q6 用户拍）

characters 的 style 收缩为**人物固有层**（基调＋quirks＋立人事例，ADR 0033「他是谁」的料），不再承载任何关系内容；plan-character-personality 老方案中 private_ties / emperor_memory 的信息形态迁给边引擎（现存 style 关系句转为开局 seed 素材，见 0086）；`record_minister_memory` 工具路线由 0079＋召对口写端（0082）取代（判官当场记，无需心腹工具白名单防滥用）；extractor `character_style_updates` 软进化收窄为**人物自身变化**（丧子破胆、奏对不敢再引古），关系变化一律走边事件。理由：同一份关系信息两个家＝双真源必打架（style 说「素不合」、边摘要酿出「已和解」，喂 prompt 听谁的——真相分家是 P1 教训的变体）。守界：人物固有层的特征化生死归 #472/0033 线，本 ADR 只迁走关系、不判其全家。否决（防重议）：两处共存；全废 plan-character-personality（越权）。
