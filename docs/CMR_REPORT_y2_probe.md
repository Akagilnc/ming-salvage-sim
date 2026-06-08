# CMR 报告 — probe/session-as-llm(ahead 5 vs origin/main)

**时间**:2026-06-08
**scope**:`origin/main...HEAD` 排除 `docs/raw`(134 文件 / 19233 行 benchmark dump 噪声)= 33 文件 / 2869 insert 净代码+测试
**编队(wiki cross-model-review v3,大 diff N=3)**:3 × codex gpt-5.5(分段 A/B/C)+ 1 × Claude opus(full)+ 1 × agy/Gemini 3.5 Flash(full)= 3+1+1,5 reviewer 全在场
**手动按 wiki 跑**(skill 未必同步 wiki),two-phase 顺机理派发已守 no-peek。

---

## 合并 + 分级(adversarial verify 后)

### 自治修(bounded 正确性 / mechanical,不动数据模型契约)

| ID | finding | reviewers | 级别 | 核实 |
|---|---|---|---|---|
| F1 | web_app 会话动作「更新」调 `upsert_secret_order(state, minister, …)` 按「该大臣最新 active(`ORDER BY id DESC`)」改,**忽略已解析 target id** → 多条密令时改错条;且更新传 `tags=[]` 清空原标签;`get_active_secret_orders_for_minister` 含 pending_review,动作按 active 处理 | codexC×3, codexA | P1 | ✅ 读码确认 |
| F2 | `_run_agy/_run_codex/_run_claude` 不查 `returncode`,stdout 空时从 stderr 剥文当回答 → CLI auth/quota 错被静默当空/角色文本落库 | codexA, codexC | P1 | ✅ 读码确认 |
| F3 | session `_cli_backend_fallback_actions` 用 `create_secret_order`(非 upsert)+ 缺 `registry.refresh` → CLI 模式重复密令、大臣同回合看不到新令 | agy, codexC, Claude | P1 | ✅ 读码确认(我写的) |
| F4 | `content/offices.json` `经略` 同在「边镇」「地方」stems,边镇 priority 在前 → 地方的`经略`死配置 | agy | P3 | ✅ |
| F5 | `cannon_equipment` 注释/测试文案写 0-100 / 「超30截到30」,实现 clamp 0-12(随军炮门数)→ spec/impl 不一致 | codexB, Claude, codexA | P3 | ✅ |
| F6 | `enrich_initiative_effects`/`_extract_secret_order` 的 trace `backend` 硬编码 `"agy"`,codex/claude 后端复盘被污染 | codexA | P3 | ✅ |
| F7 | `_apply_issue_entities` docstring 称「全局严格不静默」,但非 dict 的 `character_status_changes` item 直接 `continue` 静默丢 | codexB | P2 | ✅ |
| F8 | extract/enrich prompt 模板含 `//` 注释但要求纯 JSON,`_loads_lenient` 不剥 JSONC → 模型照模板输出注释时静默解析失败退默认 | codexA | P2 | ✅ |
| F9 | `ARMY_FIELD_ALIASES` 缺 `火器/随军大炮/大炮` 中文别名(其他字段都有)→ LLM 若输出中文 key 被静默 skip(**非崩溃**) | agy, codexB | P3 | ⚠️ 降级:agy/codexB 称「抛 LLMContractError 崩溃」**证伪**——未知字段是 `[WARN]+跳过`,且 prompt 用英文 key。实为一致性/静默丢失 P3 |
| F10 | `extract_minister_actions` 不校验 `密令动作` 白名单、不验 `order_id ∈ active_orders`(消费方 web_app 已限范围,函数自身无防御) | codexA | P3 | ✅ |

### (d) 类 → defer + flag(数据模型 / settlement 契约决策,不自治改)

> Defer 协议(wiki §切片内纪律):① 显式分级 ② 具体理由 ③ 预期时机。

- [ ] **[P1→defer] D1 `apply_score_extraction` 事务边界** — pipeline 有 5 个中段 commit(db.py:834/910/945/988/1030),后段 `army_delta` 引用不存在军 raise 时留半落库账本。**理由**:这与用户拍板的「全局严格·选项1(非法 delta 直接抛错中断,不静默)」是同一决策的两面;改成 validate-all-then-mutate / 真事务 rollback 是 settlement 管线架构改动,需用户定方向。**时机**:专门一轮架构切片(配 e2e「中途抛错→DB 无半落库」测试,Claude 亦指出此测试缺口)。reviewers: codexB(P1) + Claude(测试缺口)
- [ ] **[P1→defer] D2 城防炮 `region.cannon` 无 delta 写入路径** — `apply_region_cannon`(db.py:1114)**零调用方**,`regions.cannon` 只被它写(没人调)+ 读显示;`REGION_*_FIELDS`/别名表无 `cannon` → LLM 无路径改城防炮,刚加的城防功能是只读死功能。**理由**:补写路径要定 contract(走 region_delta 新字段?建筑效果?新 effect 类型?)+ 配套 prompt/extractor schema,是数据模型决策。**时机**:城防炮做成可玩切片时一并定 schema。reviewer: codexB(P1)
- [ ] **[P2→defer] D3 `conftest.game` fixture 依赖 gitignored `data/probe.db`,缺失时 skip** → 干净 checkout/CI 大面积假绿。**理由**:修需造最小 deterministic seed DB 或提交专用小 fixture,是测试基建工程,独立于本批代码正确性。**时机**:接 CI 前。reviewer: codexB(P2)
- [ ] **[P2→defer] D4 `_loads_lenient` JSONC 容错非 quote-aware** — 已做 strict-first(合法 JSON 零误伤,常见情况已消);但严格解析失败的恢复路径上,`//`/`,}` 清洗仍会进字符串内部(病态边界:`{"note":"x,}", "n":1,}` → `x}`)。**理由**:彻底修需写 quote-aware 清洗器(追踪字符串/转义态),是独立小重构;当前残留仅在「LLM 同时吐尾逗号 + 串值含 `//` 或 `,}`」的双重病态输入下触发,概率极低。**时机**:下一轮 cli_backend 维护时换 quote-aware 清洗器 + 补这两条回归测试。reviewer: fix-loop re-review codex(P2)

---

## 终止信号判定

非 5/5 concur(查出多条真 P1)→ 进 fix loop。round 1 findings 真实多样、非 drift(数量/类别/target 三联未命中)。按 wiki:bounded P1/P2/P3 自治修,(d) 类 defer-with-protocol。

**红线约束**:公开/商用前净重写,在此之前**不 push 自己改动到公开仓库**。故本轮自治走到 **push 边界即停**,不建 PR(`gstack-ship` 的 push/PR 步触红线)。
