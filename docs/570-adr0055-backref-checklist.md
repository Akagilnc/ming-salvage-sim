# #570 · ADR 0055 回注靶点点核（P-1）

分母＝`docs/adr/0055-promulgation-gate-at-settlement-effects-follow-verdict.md` 正文末句 8 项。  
每项二选一：已回注 → `文件:行号`；未回注 → 本片补。禁凭记忆。

**ADR 0056 侧靶点＝空集**（全文无回注条款；机器契约真源＝#564 Implementation Decisions）。  
本片对 0056 只点核：与 #564 Implementation Decisions 无口径分叉（signed `direction`×`intensity`、三笔、零反应不入清单；见 `tests/test_override_breach_costs_564.py`）。**不得自造 0056 靶点**。

| # | 靶点 | 状态 | 证据指针 |
|---|---|---|---|
| 1 | #513 物化时点表 | 已回注（issue 评论/body） | GitHub #513 body「物化时点（按 ADR 0055 修订下沉…）」段；W3 保真审判回注抬头。本片评论再钉 0055 依据。 |
| 2 | ADR 0011-2 D2-8 括注 | 已回注 | `docs/adr/0011-2-blood-debt-ratchet-schema.md:142`（「0055 收窄适用域…」） |
| 3 | CONTEXT「颁诏」词条 | 已回注 | `CONTEXT.md:61`（颁诏条括注 0055 颁布关）；另见 `CONTEXT.md:134-136` 颁布关词条 |
| 4 | DELTA_SCHEMA 效果分工线与 origin 槽 | 本片补 + 既有 origin 槽 | 本片新增 `docs/DELTA_SCHEMA.md:8`「ADR 0055 效果分工线与 origin 槽」节；origin 槽既有各 `origin_ref` / `authority_changes` 的 `dossier_id` 资格 |
| 5 | SETTLEMENT_FLOW 受判类 staging/判决步 | 已回注 | `docs/SETTLEMENT_FLOW.md:7-15`（#571 S1 颁布关实码顺序）；`docs/SETTLEMENT_FLOW.md:41`（pre_settle staging 括注 0055） |
| 6 | `docs/character-office-changes.md`（character_offices 解禁只写 + 废止「本回合即可召见」） | 已回注；#672 document-release 同步现行接线 | 任免生效时点与解禁只写均见 `docs/character-office-changes.md` |
| 7 | DELTA_SCHEMA class_delta 嵌套形 | 已回注 | `docs/DELTA_SCHEMA.md:22`（顶层注释嵌套形）；`docs/DELTA_SCHEMA.md:84-88`（value 必须 dict，扁平 int 拒收） |
| 8 | #519 / #520 验收口径若涉 | 已回注（issue body） | #519 / #520 body 均含「物化时点按 ADR 0055 下沉」保真审判回注；本片评论再钉。 |

点核日：随 #570 合入 HEAD。
