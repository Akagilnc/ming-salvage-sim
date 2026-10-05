# #1897 K1/K2/F3 本轮完整成员处置表
第三轮 fixer。**不宣称 merge／关票。**
## 枚举命令（可执行）
### K1
```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests
```
### K2
```bash
rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|按唯一标题|binds_from_unique_title|猜绑' ming_sim tests
rg -n '唯一标题|title_to_ids|标题补绑|标题重绑|猜绑' TODOS.md docs/test-cleanup-audit-1185.md
```
### F3（全断言＋全函数候选，无 HIGH 词表收窄）
```bash
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
$PY artifacts/1897-f3-enum-gen_tables.py
find tests -name '*.py' | wc -l
find web \( -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' -o -name '*.spec.tsx' \) | wc -l
```
- Python 测试文件：235
- Web 测试文件：25
- 全断言条数：12960
- 散文提示候选：2196
- 消费者函数调用：38
- 空心（context+relation 同案）：0
- Web 散文提示样本：368
- 违规残留：0

## K1 成员处置
| # | 成员 | 接缝 | 处置 | 依据 |
|---:|---|---|---|---|
| 1 | `db._note / update_secret_order_progress 缺案卷` | 进展 | **raise ValueError** | K1 |
| 2 | `db.close_secret_order 缺案卷` | 结案 | **raise** | K1 |
| 3 | `covert_progress monthly / settle_due 缺案卷` | 月度／到期 | **raise** | K1 |
| 4 | `commit_pending_actions 非 typed Exception` | 暂存→应允 | **raise 且 pending 保留** | K1 本轮入口变异 |
| 5 | `unknown/non-active → False` | 进展 | **合法保留领域拒收** | 判词 |
| 6 | `供料读缺案卷 soft-skip` | 读 | **边界外保留** | 非写接缝 |

## K2 成员处置
| # | 成员 | 处置 | 依据 |
|---:|---|---|---|
| 1 | `title_to_ids 唯一标题补／重绑` | **已删除** | ADR0142 |
| 2 | `显式 event_id／dossier: 前缀` | **合法保留** | 显式引用 |
| 3 | `prepare_rescript_prewrite→bind→commit_rescript_phase1` | **本轮入口变异：改写标题仍绑显式 id；标题-only 不绑** | K2 |
| 4 | `test_decision_event_binding_389 负向闸` | **合法保留** | 附属闸 |
| 5 | `TODOS / cleanup-audit 说明` | **已补绑退休** | 附属物 |

## F3 空心消费者
无（`character_context_with_db`+`project_relation_ledger` 同案已清）。

## F3 处置汇总（散文提示候选语义复核）
| 处置 | 条数 |
|---|---:|
| 合法保留：散文提示命中但断言为结构／身份／闸／夹具回读（非自由正文承重锁） | 2065 |
| 合法保留：空串／None 结构闸 | 40 |
| 合法保留：P4 负向闸（裸数不得入呈现） | 22 |
| 合法保留：确定性结构化标签／builder | 19 |
| 合法保留：非空交付（不锁正文） | 16 |
| 合法保留：类型＋非空交付（非正文等值） | 13 |
| 合法保留：夹具写入→投影回读 | 7 |
| 合法保留：CLI 模型标签配置 | 4 |
| 合法保留：纯抽取 helper 入出对照 | 4 |
| 合法保留：结构化白名单标签集 | 3 |
| 合法保留：夹具问话身份回读 | 2 |
| 合法保留：流式重放传输一致性（非锁固定 mock 正文） | 1 |

## 本轮已处置文件摘要
- `tests/test_audience_restore_505.py`：去 mock answer／回话正文锁；保留状态／计数结构
- `tests/test_candidate_supply_1893.py`：去 summary 正文等值；保留 id／缺 effect 结构
- `tests/test_featured_dossiers_494.py`：去资产散文 in rendered；改结构化交付／分桶／P4 负向
- `tests/test_highlight_judge_544.py`：去 mock answer／seen_reply 正文锁；保留时序／高亮结构
- `tests/test_pay_order_override_653.py`：影子 SQL 已删（前轮）；复扫无命中
- `tests/test_scene_llm_1836.py`：去 answer==script／reply 成员锁；保留调用次数／身份
- `tests/test_structured_decree_contract_1624.py`：去 draft_text 正文锁；保留身份束结构
- `tests/test_style_temperament_641.py`：整案删除空心 character_context→relation_ledger；闸负向保留

## Web 散文提示样本（前 20）
| 位置 | 文本 |
|---|---|
| `web/src/appDurableWiring.test.tsx:127` | `expect(host.textContent).toContain("天启七年九月邸报·试重开");` |
| `web/src/appDurableWiring.test.tsx:182` | `expect(host.textContent).toContain("杨嗣昌御前低语");` |
| `web/src/appDurableWiring.test.tsx:252` | `await vi.waitFor(() => expect(calls.some((call) => call.body?.includes(`宣${minister.name}`))).toBe(true));` |
| `web/src/appDurableWiring.test.tsx:256` | `await act(async () => { await vi.waitFor(() => expect(host.textContent).toContain("臣已入殿")); });` |
| `web/src/appDurableWiring.test.tsx:258` | `await act(async () => { await vi.waitFor(() => expect(host.textContent).toContain("臣已入殿")); });` |
| `web/src/appDurableWiring.test.tsx:301` | `expect(alert.textContent).toBe(detail.message);` |
| `web/src/appDurableWiring.test.tsx:302` | `expect(alert.textContent).not.toContain(detail.code);` |
| `web/src/appDurableWiring.test.tsx:347` | `expect(host.querySelector("textarea")?.value).toBe("");` |
| `web/src/appDurableWiring.test.tsx:348` | `expect(host.querySelector('[data-audience-turn-id="8"]')?.textContent).toContain("边务如何");` |
| `web/src/appDurableWiring.test.tsx:581` | `await act(async () => { await vi.waitFor(() => expect(replyButton()?.textContent).toBe("重试")); });` |
| `web/src/appDurableWiring.test.tsx:584` | `await act(async () => { await vi.waitFor(() => expect(translationButton()?.textContent).toBe("重试")); });` |
| `web/src/appDurableWiring.test.tsx:594` | `expect(replyAttempts).toBe(1);` |
| `web/src/appDurableWiring.test.tsx:606` | `expect(retryCalls).toContain("/api/audience/reply/retry");` |
| `web/src/appDurableWiring.test.tsx:609` | `expect(JSON.parse(String(targetedRetry?.[1]?.body))).toEqual({ chat_turn_id: 7 });` |
| `web/src/appDurableWiring.test.tsx:612` | `expect(retryCalls).not.toContain("/api/ministers/%E9%83%AD%E5%85%81%E5%8E%9A/reply/retry");` |
| `web/src/appDurableWiring.test.tsx:719` | `expect(replyNotice()?.querySelector("button")?.disabled).toBe(false);` |
| `web/src/appDurableWiring.test.tsx:1126` | `await vi.waitFor(() => expect(reopened.querySelector(".hud2-val")?.textContent).toContain("11"));` |
| `web/src/appDurableWiring.test.tsx:1130` | `expect(gazetteReport(reopened)).not.toBe("");` |
| `web/src/appDurableWiring.test.tsx:1198` | `expect(gazetteReport(host)).not.toBe("");` |
| `web/src/appDurableWiring.test.tsx:1208` | `expect(host.textContent).toContain(MIDCOURSE_ISSUE);` |

共 368 条样本；语义复核为 UI／契约结构断言为主，未发现须按 F3 删除的 mock 回话正文锁新簇。

## 附注
- 枚举改为**全断言 + 全函数候选**；`PROSE_HINT` 只标候选，不靠字段白名单宣布结清。
- 行为语义复核后：**违规残留=0** 即本授权类 F3 结清；合法保留项保留闸／结构／夹具回读。
- 前两轮报告保留为过程史；本表为 r3 现行 HEAD。
- **不宣称 merge／关票。**
