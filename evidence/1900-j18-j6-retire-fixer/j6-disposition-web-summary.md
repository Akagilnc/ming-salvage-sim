# J6 web_calls_without_ui_token 处置摘要（#1900）







来源：`j6-structural-candidates.jsonl` 中 `flags` 含 `web_calls_without_ui_token` 的 **55** 条。



逐条语义处置：`j6-disposition-web.jsonl`（每条含 `file/name/line/action/entry/result/mock_boundary/reason`）。







## 计数







| action | n |



|---|---|



| retain | 54 |



| migrate | 1 |



| delete | 0 |







扫描器把「有 `toHaveBeenCalled` 且未命中 UI token」打成候选；读源后绝大多数是 **真实组件/hook 入口 + DOM / handler 载荷 / 传输 URL·body** 的 UI 契约，**不是**纯 call-route / mock-替-SUT。







## 区分准则（本批）







- **retain**：render/mountHarness/真实控件点击为入口；结果落在 DOM（焦点、disabled、确认卡、phase/error testid、scrollTop、portal 挂载点等）或 **父级 handler / fetch 出口载荷**（`onResolve`/`onSend`/`expected_turn` 等）。`toHaveBeenCalled` 是读该出口的手段，不是锁内部协作路由。必要负向（`confirm` 未调、取消零请求、不 `reload`）与正向结果同测保留。



- **migrate**：仅剩协作调用计数、无可观察表面 → 真类成员，需改测补结果（本批不做代码改动）。



- **delete**：无（无 helper 专测、无 mock 替换 SUT、无仅文字锁）。







## 真类成员（需改代码）







| file | line | name | action | 缺口 |



|---|---|---|---|---|



| `web/src/useSettlementFlow.test.tsx` | 285 | `#1845 background tail failure observation` / `refreshes a non-ending month while the tail runs, then stops on persisted failure` | **migrate** | 断言只有 `loadState.toHaveBeenCalledTimes(1)`×2，无 host/hook 上 `mechanical_tail_failure` / alert 等可见结果。应在首轮 poll 后钉失败面，停轮询计数降为旁证。邻测 `shows a failed ending…`（L268）已覆盖静态失败面，但不能代替「跑尾中 poll→失败后停轮询」这条时间线。 |







**本回执只写处置，不落地 migrate 改测 / 不新增证明测 / 不挂生产钩子。**







## 按文件 retain 一览







| 文件 | n | 为何多 retain |



|---|---|---|



| `decisionModal.test.tsx` | 10 | 焦点/三态 DOM + `onResolve` 批红载荷 |



| `drawers.test.tsx` | 3 | 同衔分座/offstage DOM + 委派身份；portal 挂载点 |



| `gameMenu.test.tsx` | 4 | #1732 就地确认卡 DOM + fetch/confirm 负向 |



| `menuPage.test.tsx` | 4 | 继续 SSE 终态 + 就地确认/删除委派 |



| `modals.test.tsx` | 19 | 拟诏/召对/史册 DOM 与 seam 口令载荷 |



| `settlementGazettePanel.test.tsx` | 1 | 本面邸报 DOM + `onDismiss` |



| `useSettlementFlow.test.tsx` | 13 retain + 1 migrate | 令牌传输、HUD testid、阅读态 hook 字段；仅 L285 纯 poll 计数 |







## 核验







```sh



python3 -c "



import json



from collections import Counter



rows=[json.loads(l) for l in open('evidence/1900-j18-j6-retire-fixer/j6-disposition-web.jsonl')]



cands=[]



for l in open('evidence/1900-j18-j6-retire-fixer/j6-structural-candidates.jsonl'):



    o=json.loads(l)



    if 'web_calls_without_ui_token' in o.get('flags',[]): cands.append(o)



assert len(rows)==55==len(cands)



assert {(r['file'],r['line']) for r in rows}=={(c['file'],c['line']) for c in cands}



print(Counter(r['action'] for r in rows))



print('migrate:', [r['name'] for r in rows if r['action']=='migrate'])



"



```

