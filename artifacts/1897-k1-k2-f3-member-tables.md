# #1897 K1/K2/F3 成员处置表（第四轮）

第四轮 fixer。**纠正 r3 F3 假结清。不宣称 merge／关票。**

## 枚举命令（可执行，非自动判合法）

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

### F3（stdlib AST 候选文本；合法性须手工语义核）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
../Ming_LLM/.venv/bin/python artifacts/1897-f3-enum-scan.py
# 输出：
#   /tmp/1897-r4-f3-enum/python-prose-candidates.txt
#   /tmp/1897-r4-f3-enum/web-prose-candidates.txt
#   /tmp/1897-r4-f3-enum/python-consumer-calls.txt
#   /tmp/1897-r4-f3-enum/meta.json
```

r3 的 `1897-f3-enum-gen_tables.py`（自动 dispose_* 分类器）已删除；它不能自动判 F3 合法。

### 本轮扫描计数（HEAD 候选，非结清声明）

| 项 | 数 |
|---|---:|
| Python 散文比较候选 | 4386 |
| Python 含中文候选 | 2809 |
| Web 表面比较候选 | 250 |
| Web 含中文候选 | 135 |
| 消费者调用点 | 86 |
| 含消费者的测试函数 | 65 |

完整逐项处置：

- Web 全量：[`1897-f3-web-disposition-r4.txt`](1897-f3-web-disposition-r4.txt)（250 行，每条 KEEP_*/REWRITE）
- Web 本轮改动断言：[`1897-f3-web-changed-assertions-r4.txt`](1897-f3-web-changed-assertions-r4.txt)
- Python 本轮改动：[`1897-f3-python-disposition-r4.txt`](1897-f3-python-disposition-r4.txt)

## K1 / K2（承接 r3；本轮复扫）

| 类 | 状态 | 证据 |
|---|---|---|
| K1 缺案卷响亮 | **维持结清** | `db.py` / `covert_progress.py` 仍 `raise ValueError("密令进展缺少对应案卷")` |
| K2 标题猜绑 | **维持结清** | `title_to_ids` / `按唯一标题` 生产与测试无命中 |

## F3：r3 假结清纠正点

r3 成员表自身反例却宣称违规残留=0：

| 位置 | r3 错误 | r4 处置 |
|---|---|---|
| `appDurableWiring.test.tsx:182` | `杨嗣昌御前低语` 标合法 | REWRITE→attendant/aside 结构 |
| `appDurableWiring.test.tsx:256/258` | `臣已入殿` 标合法 | REWRITE→stream scene + 殿上入口结构 |
| `appDurableWiring.test.tsx:348` | 夹具问话 `边务如何` 标合法 | REWRITE→user turn-id 段 |
| `appDurableWiring.test.tsx:1208` | `MIDCOURSE_ISSUE` 标合法 | REWRITE→`.situation-list`/panel |
| Python「2065 笼统合法」 | 无逐项语义核 | 真自由正文／夹具回读已逐项 REWRITE；见 python disposition |
| Web「前 20 / 368 样本」 | 未全读却宣称清净 | 250 候选全表写入 disposition 文件 |

禁止项本轮遵守：不因 mock／流式／夹具回读豁免自由正文；不以非空／类型换形保壳；不另造平行证明测试。

## F3 空心／影子（非仅 context+relation）

| 检查 | 结果 |
|---|---|
| `character_context_with_db`+`project_relation_ledger` 同案空心 | 无 |
| `turn_region_summary` 影子 SQL（pay_order） | 无专属影子复制 |
| 消费者调用却无其返回／DTO 断言 | 抽查 relation_read／seed：均断言 DTO／字段集；无空壳整案须删 |

## 合法保留口径（不得扩到回话／叙事）

- KEEP_UI：按钮／菜单／busy／固定离开提示等界面契约
- KEEP_ERR：结构化 error message／code／pack path
- KEEP_STRUCT：空串／相位／HUD 数／panel 显隐／aria
- KEEP_ID：人名／地名／官职等结构化身份；entity name 字段

**不**把上述扩到：大臣回话、场景戏文、邸报／奏疏正文、议题 title 叙事、夹具问话回读。

## 附注

- 过程史：`1897-k1-k2-f3-apply-report.md`、`…-r2.md`、`…-r3.md` 保留；本表与 r4 报告纠正假结清。
- **不宣称 merge／关票。**
