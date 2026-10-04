# #1830 合并修理分支：三类续修回执

基线 `88d114e21`，分支 `ak-roles/issue-1830-w4merge`。本局 apply，未合入家族底座。读取本 run 两份封存判词、派单、全局／仓级规则，并以 `gh issue view 1830 --repo Akagilnc/ming-salvage-sim --json title,body` 核现行票面。沿用三类，不以点名文件作白名单；最终判词撤销的换行路径协议及扩展名读取边界不重加。

## 类定义、根因、处置

| 类 | 错误与正确行为 | 处置 |
| --- | --- | --- |
| 身份材料增补改写既存自由文本 | 读旧 INDEX → splitlines／过滤空行／join → 覆写，会改 CRLF、空行、孤立 CR。增补只能保留旧字节并追加自己的路径。 | `write_identity_materials` 使用标准库 append、`newline=""`，删除旧读拆拼机制。不增加解析、去重或正文护栏。身份子树仍复用已有 `_write_tree`；调用者的身份名集合与释放／重备生命周期不变。 |
| 测试以正文及非契约措辞推断身份、权限 | 覆盖成员关系、行／条数、哨兵、相等／不等、标题拆分、固定措辞、内部锁定、重复、同源渲染器自证；不能用原文搬运充当准入／完整性证明。 | 复用现有入口，按 applied id、source_id、chat_turn_id、record_id、持久化 origin、路径及契约字段判断来源／边界；删除无合法独立价值的正文证明及其 helper。不新增测试、生产钩子、平行夹具或正文解析器。 |
| 新交卷整类结清声明与事实不符 | 前回执的“无未修类别”与残留相抵。搜索命中数量／测试绿灯不能推出整类无遗漏，更不能推出整票收敛。 | 本回执明确更正旧声明，逐类列出成员、保留依据、实测失败与成功、真实 diff。历史回执及冻结材料不覆写。 |

## 全仓机械枚举及复扫

扫描域是版本控制中的整个仓库，不只列名测试。先以下列读写／决策／断言谓词搜索，再沿公开投影→场景／单人／世界目录的消费者核对语义、别名和 helper 调用。Python AST 不要求变量名中出现 body／title，涵盖比较、包含关系、数量、断言、条件、comprehension，以及拆分／匹配／格式化／读写／SQL；JS／TS 不设标识符白名单。文字关键词只作辅助导航，不作排除条件。

```sh
rg -n 'read_text|write_text|write_bytes|splitlines|split|strip|join|open\(' ming_sim tests web --glob '*.py' --glob '*.js' --glob '*.ts'
rg -n '身份卡|write_identity_materials|identity_material_rel' ming_sim tests web --glob '*.py' --glob '*.js' --glob '*.ts'
rg -n '(not in|==|!=|split|splitlines|count|search|match|startswith|endswith)' tests --glob '*.py'
rg -n 'WHERE.*body|if .*\["body"\]|if .*\["content"\]|if .*\["title"\]|not in .*blob|not in .*text|split\("："|_shared_bodies|_view_text' tests --glob '*.py'
rg -n '无未修|未修类别|整类|两类|结清|全部|未结' evidence/1830*
```

完整 AST 枚举命令（基线与修后各执行一次；仅在系统临时目录写调查产物）：

```python
# /tmp/1830-enumerate.py; python3 /tmp/1830-enumerate.py 88d114e21
#                         python3 /tmp/1830-enumerate.py
import ast, json, subprocess, sys
from pathlib import Path
revision = sys.argv[1] if len(sys.argv) > 1 else None
listing = ['git', 'ls-tree', '-rz', '--name-only', revision] if revision else ['git', 'ls-files', '-z']
paths = subprocess.check_output(listing, text=True).split('\0')
counts = {}
with open('/tmp/1830-enumeration-' + (revision or 'current') + '.jsonl', 'w') as output:
    for name in paths:
        path = Path(name)
        if not name or (not revision and not path.is_file()):
            continue
        if path.suffix not in {'.py', '.js', '.jsx', '.ts', '.tsx'}:
            continue
        text = subprocess.check_output(['git', 'show', revision+':'+name], text=True) if revision else path.read_text()
        if path.suffix == '.py':
            for node in ast.walk(ast.parse(text, filename=name)):
                decision = isinstance(node, (ast.Assert, ast.Compare, ast.If, ast.IfExp, ast.comprehension))
                transformation = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'split', 'splitlines', 'join', 'strip', 'replace', 'count', 'startswith', 'endswith', 'search', 'match', 'findall', 'read_text', 'write_text', 'open', 'execute'}
                if decision or transformation:
                    kind = type(node).__name__
                    counts[kind] = counts.get(kind, 0) + 1
                    output.write(json.dumps({'path':name, 'line':getattr(node, 'lineno', 0), 'kind':kind, 'source':ast.unparse(node)}, ensure_ascii=False)+'\n')
        else:
            for line, source in enumerate(text.splitlines(), 1):
                output.write(json.dumps({'path':name, 'line':line, 'kind':'source', 'source':source}, ensure_ascii=False)+'\n')
print(json.dumps(counts, sort_keys=True))
```

基线 AST：Assert 13754、Call 7999、Compare 21188、If 8863、IfExp 1528、comprehension 3875；修后：13666、7947、21078、8861、1527、3805。辅助运算候选 11922 行、文字导航候选 2840 行，最终窄式复扫候选 55 行（随后把其中在途固定措辞也删去）。数量只是调查产物，不是成员判定或结清证明。身份写手／调用者枚举 10 行，实际旧 INDEX 读拆拼增补核只有下表一处；初次写树、按既有来源重备新树不是改写既存 INDEX 的增补核。

## 成员表

以函数定位，函数内同形断言合并列示；共享 helper 的未改正文调用者也列入。不存在把点名样本替换成另一份正文证明的处置。

### 类 1

| 成员 | 处置 |
| --- | --- |
| `ming_sim/materials.py::write_identity_materials` 的旧 INDEX 读拆拼覆写块 | 改为保字节 append。唯一生产改动。 |

### 类 2

| 文件 | 成员（原名称；函数内全部同类实例一起处置） |
| --- | --- |
| `tests/test_army_card_status_1501.py` | `_expected_army_card_from_row`；`test_army_payload_omits_static_status_exposes_arrears_text`；`test_army_report_keeps_row_status`；`test_shared_consumers_still_surface_status` |
| `tests/test_army_display_173.py` | `test_army_public_exits_approx_arrears_and_hide_split_accounts`；`test_army_arrears_presentation_rounds_half_steps_up`；`test_army_payload_exposes_approx_arrears_text_not_raw` |
| `tests/test_army_firearms.py` | `test_army_public_exits_surface_firearm_and_cannon` |
| `tests/test_audience_night_498.py` | `test_legacy_reply_without_segments_stays_neutral_in_night_scroll` |
| `tests/test_audience_scroll_539.py` | `test_unnamed_speaker_cannot_finish_translation`；`test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats`；`test_scroll_contract_merges_both_stores_with_container_and_coda`；`test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action`；`test_extractor_open_tags_do_not_drive_beat_or_soft_boundary` |
| `tests/test_audience_translate_1837.py` | `test_translation_entry_preserves_unknown_rejection_and_source_cutoff` |
| `tests/test_audience_translate_1837_reopen.py` | `test_separate_inquiries_same_turn_survive_and_retry_is_idempotent` |
| `tests/test_audience_translation_1838.py` | `test_three_speaker_segments_private_whisper_reaches_only_participant`；`test_edge_event_and_public_saying_attach_affair` |
| `tests/test_audience_travel_gating_670.py` | `test_summon_recorder_default_body_is_empty_and_tags_carry_facts` |
| `tests/test_character_knowledge_489.py` | `test_turn_report_counterpart_never_uses_aggregate_when_sources_exist`；`test_shared_archive_storage_never_writes_restricted_aggregate` |
| `tests/test_featured_dossiers_494.py` | `_court_ministers`；`_dossier_voice`；`test_every_active_seven_faction_minister_has_featured_dossier`；`test_seven_faction_dossiers_are_objective_and_identity_scoped`；`test_north_star_ministers_have_distinct_featured_voices`（整个失效文本证明文件删除） |
| `tests/test_gazette_author_1862.py` | `test_author_archives_own_title_and_same_run_advances` |
| `tests/test_highlight_judge_544.py` | `test_read_night_scroll_includes_minister_highlights` |
| `tests/test_month_chain_1847.py` | `test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects` |
| `tests/test_public_sayings_1829.py` | `test_absent_minister_reads_saying_not_actual_status`；`test_public_saying_excluded_name_does_not_see_it_others_do`；`test_public_saying_survives_same_turn_archive_projection` |
| `tests/test_relation_brew_636.py` | `test_failed_month_degrades_to_pending_and_rebrews_next_month`；`test_prepare_attaches_prior_events_only_via_history_seam` |
| `tests/test_secret_order_isolation_883.py` helpers | `_shared_bodies`；`_event_bodies`；`_view_text` 删除；`_assert_oral_decree_withheld_not_shared` 改按 source id。 |
| 同文件 #883 用例 | `test_883_shared_summary_write_seam_rejects_secret_order_source`；`test_883_audience_chat_path_does_not_leave_secret_in_shared_sources`；`test_883_audience_chat_paraphrase_does_not_leave_origin_in_shared_sources`；`test_883_public_audience_same_turn_survives_secret_classification`；`test_883_cross_turn_chat_origin_withheld_on_late_secret_create`；`test_883_zero_overlap_semantic_rewrite_withholds_prior_audience_origin`；`test_883_thematic_public_audience_survives_secret_create`；`test_883_shared_archive_bypass_positive_and_negative` |
| 同文件 #976 消息／pin 用例 | `test_976_minister_reply_not_shared_before_classification`；`test_976_secret_chat_turn_withholds_both_sides_but_public_turn_survives`；`test_976_withhold_does_not_yank_old_released_public_user`；`test_976_cross_person_speaker_user_origin_withheld_not_shared`；`test_976_same_window_pure_public_user_survives_secret_classification`；`test_976_stage_confirm_pin_provenance_not_max_held_user`；`test_976_pending_secret_pin_survives_partial_commit_same_minister`；`test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit` |
| 同文件 #976 真入口／共享 helper 调用者 | `test_976_rt01_two_secret_orders_different_assignees_no_cross_track`；`test_976_rt02_misassigned_provenance_follows_origin_message`；`test_976_rt03_late_chat_after_create_same_turn`；`test_976_rt04_undo_chat_turn_secret_order_brief_consistent`；`test_976_rt05_save_restore_between_hold_and_release`；`test_976_non_create_stage_commit_update_withholds_oral_pin`；`test_976_non_create_stage_commit_rush_withholds_oral_pin`；`test_976_non_create_stage_commit_progress_and_review_withhold_oral_pin` |
| `tests/test_secret_order_monthly_progress_566.py` | `test_only_emperor_private_payload_shows_monthly_report`：删去 assignee 材料 blob 的正文权限证明；改名 `test_emperor_private_payload_preserves_monthly_report`，只称实际保留的原样搬运契约。 |
| `tests/test_web_court_visibility.py` | `test_choose_minister_real_entry_excludes_weishi_includes_court`：删除 printed blob 推断名单／标题证明，不另造 UI 文本测试。 |

处置总则：已存在来源／裁切断言时删去重复正文证明；缺失来源判断时复用当前测试的写入返回 ID。公开说法的既有过月用例只观察真实知识投影的结构化返回值，仍验证世界调用不排除、邸报调用显式排除、普通来源准入，不改被测投影行为。人物私语按 ledger ID 判可闻；公开说法按 applied/source ID 定位；卷轴按 chat_turn_id／record_id 判来源；关系历史按实际持久化 origin 判桶，不按 context 判桶；军牌保留契约键集及 DB identity 对照，删除复制 `_player_army_situation` 的 oracle。无独立契约价值的 dossier 文案 distinctness、军报／名册段落拆名、欠饷同源 renderer 自证直接删除，无换形替代。

### 类 3

| 成员 | 处置 |
| --- | --- |
| `evidence/1830-w4merge-fixer-receipt.md:55`：“本轮两类修理交付复核，无未修类别。” | 此完成表述不成立：本局仍发现 INDEX 改写与上表文本证明。以本回执纠正，旧卷保留供核。 |
| 本新回执／终局声明 | 以本次扫描、真实 diff 和下列验证报告本局修理；不把旧回执、统计数量或测试绿灯视作整票收敛。 |

## 保留项与合法边界

- `list_materials` 换行路径协议解析、按扩展名选读取对象：最终判词明确撤销该 boundary；保留。目录路径、DB/ledger/source ID、SSE wire event、有限结构化 enum 是契约，不是展示正文。
- `test_public_projection_consistency_1830.py` 的来源对应路径集合、CLI/API 同树；`test_material_directory_1830.py` 的路径集合、未知文件／越界读取负向、独立原文搬运：保留。INDEX 中的原始标题搬运断言不代替上述路径完整性断言。
- #883/#976 的 withheld/held/released、来源计数、他臣 source ID 排除、speaker/assignee 血缘、brief 原文、undo/reopen 和失败路径均保留。零 n-gram 重叠是调用前冻结夹具性质，不是生产语义解析或输出身份判断。
- 私密月报仍测试皇帝私有结构化载体及原样搬运；不声称被删的正文搜索能证明 assignee 供料边界。该展示内容的语义验收不能由正文哨兵测试洗白。
- CLI 菜单打印不是结构化名册。原有可召／名册／web 投影的未仕负向与真朝臣正向保留；不声称本轮机器验证了菜单措辞或实际模型生成内容。
- 冻结 seed 原文检查、用户显式输入字段的独立原样搬运、格式化数值与错误协议的非身份行为，不一概按文字断言删除。需要语言含义判断的模型产出不由测试作机械证明。
- 名册正文授权及职位权限仍由 #1832 承接；没有标成已修。未改生产呈现、治理文件、席位、宿主安装／配置、模型输出、冻结卷或已有有效生产修复。

## 验证与失败诚实

所有 pytest／探针进程均使用下列前缀；没有真实宿主、模型、网络验收，没有全量测试。这里的 `t` 仅为重放命令的 shell 简写，不加入仓库。

```sh
t() { env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python "$@"; }
```

### 变异真跑（复用已有入口，无永久新增测试）

1. 真实 `run_secret_orders_supply` 入口：在既有 `test_supply_call_writes_identity_materials_into_its_own_tree` 的身份增补边界放入 `b'Original title\r\n\r\nSecond paragraph\rThird line  \r\n'`，观察旧字节前缀是否保留。`t /tmp/1830-raw-probe.py old`：装回基线写手，`EXISTING_INDEX_BYTES_CHANGED`，1 failed，2.80s，exit 1。`t /tmp/1830-raw-probe.py current`：1 passed，1.69s，exit 0。旧逻辑在独立进程加载，不改工作树、不倒退提交。
2. `t /tmp/1830-test-mutation.py public-body old/current`：真实写入一条可公开的同正文另一来源，原受排除 source 的权限不变。基线测试误判“受排除说法绕过了邸报作者供料边界”：1 failed／4 passed，2.74s；本局最终测试按 ID 判定且保留两类真实供料调用的正负向：5 passed，1.62s。
3. `t /tmp/1830-test-mutation.py public old/current`：同时变更自由标题并加入同正文另一来源。基线 3 failed／2 passed，1.60s；本局 5 passed，1.50s。标题不是准入契约。
4. `t /tmp/1830-test-mutation.py affair old/current`：真实转译前写入同正文、不同事务的说法。基线 `test_edge_event_and_public_saying_attach_affair` 错选记录：1 failed，0.76s；本局按 applied ID：1 passed，0.73s。

测试变异器通过 pytest `pytest_collection_modifyitems` 在收集后的真实 module 装回 `git show 88d114e21:<测试文件>`，将 item.obj 指向原函数；current 不装回。public 场景包装 `record_public_saying`，当原输入为“边情已定，漕运如常”那条公开记录时，再用真实写入 API 写一条与受排除说法同正文的公开记录；affair 场景包装 `apply_audience_round_translation`，先用真实记录 API 写入同正文无事务说法，再执行原转译。没有 mock 投影、权限或材料写手的被测结果。

初次变异器误覆写了预先 import 的另一 module，pytest 实际没有收集旧函数，old/current 都绿；这些结果不作证。改在 collection hook 装回后才得到上述红绿。聚焦测试另两次报红是本局先把 canonical origin 当作输入裸 origin，遗漏持久化的 `|round:N`；改为按返回记录 ID 读取真正 origin，未放松互斥／来源断言。最后补回真实供料调用的结构化正负向观察时，首次把 spy 安在 materials 模块，因该模块局部导入知识入口而报 AttributeError；改安在实际 knowledge 入口，原函数照常执行，未以 mock 结果洗白。

### 聚焦组最终结果

```sh
t -m pytest -q -p no:cacheprovider --tb=short \
 tests/test_army_card_status_1501.py tests/test_army_display_173.py tests/test_army_firearms.py \
 tests/test_audience_night_498.py tests/test_audience_scroll_539.py \
 tests/test_audience_translate_1837.py tests/test_audience_translate_1837_reopen.py \
 tests/test_audience_translation_1838.py tests/test_audience_travel_gating_670.py \
 tests/test_character_knowledge_489.py tests/test_gazette_author_1862.py \
 tests/test_highlight_judge_544.py tests/test_month_chain_1847.py tests/test_public_sayings_1829.py \
 tests/test_relation_brew_636.py tests/test_secret_order_isolation_883.py \
 tests/test_secret_order_monthly_progress_566.py tests/test_web_court_visibility.py \
 tests/test_material_directory_1830.py tests/test_public_projection_consistency_1830.py \
 tests/test_secret_order_payoff_1504.py tests/test_player_army_projection_321.py
```

最终 **438 passed、1 skipped、1 warning，12.96s**。skip 是旧军饷排序测试的 seed 前提不足；warning 是现有 Starlette/httpx 弃用警告。Python AST 全仓解析成功，改动入口均 import／执行通过。没有 Python 静态 typecheck 配置／本机 mypy、pyright 命令；本片没有 TS 或类型声明改动，不冒称运行了静态类型检查。`git diff --check` 最终通过。

## 质量、净增减与交卷边界

生产仅标准库 append 替换旧拆拼；无新造通用件。测试修改最小必要成本是删除错误正文 oracle、在原入口使用现成结构化 ID；没有新增测试函数或平行夹具。原有负向和失败传播没有为绿灯放松；删去的文案证明不换形重造。成员多而代码主要删除，不能按拆文件隐藏同类残留。

净增减以 `git diff --cached --numstat` 核：生产 +3/-4；测试 +128/-543；本回执 +159/-0；合计 21 文件、+290/-547（净减 257 行）。生产＋测试净减 416 行，不以说明性“净减”替代真实行数。

本局三类修理提交复审；上述调查范围内检出的成员已处置，保留项按契约而非展示判断。不宣告 #1830 整票／家族收敛，不合入家族底座，不 push／开 PR，不 amend／stash／rewrite。后续为御史台／大理寺对新提交复核；#1832 等已划归票范围不由本局冒领完成。
