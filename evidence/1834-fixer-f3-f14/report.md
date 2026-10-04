# #1834 修内司回执：F3 删除侧手读复核（相对 7b70f4d51）

依据：同工作树复查 `7b70f4d51`。F14 本轮不处理。禁全量 / kill / stash / amend / rewrite / push / PR。未合并，不声称关票。

## 对本局纠正

`7b70f4d51` 成员表 source 仅写 `answer` / `SELECT id`、basis 泛称 fixture，且 175 一律 RESTORE，无法对照源码核验；裸 `read_material` 20 条 REACHABILITY「路径在册可达」过宽。本轮逐条手读 `52809cdf3` 删除上下文与现行生产通道，重写可核成员表；删无价值裸读（保路径异常 2 案）；补回表中假阳性未落原测的 3 条透明输送。

## 范围

- 比对基线：`52809cdf3`
- 删除侧成员：**175** → RESTORE **166** / KEEP_DELETED **9**
- 裸 `read_material` Expr：原 **22** → 现 **2**（仅 `PATH_CONFINEMENT`）
- F14：未触

### KEEP_DELETED（9）

| i | 位置 | 理由 |
| --- | --- | --- |
| 092 | `test_player_payload_1022` 整包 `payload == {…}` | 叙事 equality；现行结构键断言已覆盖 |
| 121,124–130 | `appDurableWiring` MIDCOURSE/SNAP 正向 `toContain` | 半程泄漏案要证明不可见；现行 `not.toContain` / 结构 null |

### 假阳性补回（表称 RESTORE 但原测仍缺）

- `test_audience_translate_1837::test_translate_call_failure…`：`assert result.answer == "臣在。"`（FakeAgent mock）
- `test_month_call_recovery_1846::test_world_translate_exhaustion…`：`assert chain.get("world_text") == "世界段已成文。"`（world mock）
- `test_relation_read_640::test_dto_shape…`：`assert "杨嗣昌蒙知遇之恩" in summary`（ledger `recent_segment`）

### army_display「欠饷约15万两」精确依据

- **不是**测试自写正文透明输送
- **是**固定 UI/字段生成：`UPDATE arrears=12.5` → `db.army_payload()` → `_army_arrears_report_text` → `_approx_wanliang(12.5)` → `"欠饷约15万两"`
- class=`T_FIXED_UI_FIELD`

### 点名裸读（前轮无独立种子内容契约 → 删裸调用）

| 位点 | 前轮是否有独立种子内容契约 | 处置 | 其它断言覆盖 |
| --- | --- | --- | --- |
| `character_knowledge:1411` archive | 无（仅 truthy/非空烟测；#1830 退役正文） | DELETE_BARE | ledger reason/category 排除；dossier 不可引用；路径 `endswith(/公事档案.txt)` |
| `gazette_author` experience/INDEX/world | 无（`_SECRET_BRIEF` 等哨兵按 553d581fb 退役） | DELETE_BARE | `_REPORT in text`；`_PUBLIC_FACT/_PLAIN_DOSSIER_FACT/_PRIVATE_KEEP`；source_id；路径在册 |
| `world_materials` affair/candidate/petition | 无（01a08e3a 退役标题/JSON/「皇太极称帝」等） | DELETE_BARE | 路径成员 / `len==1` / `set(paths)==eligible|due` |
| `secret_order_payoff` identity read | 无（who/body 正文锁已退役） | DELETE_BARE | 工具口 `read_material` 与直接读字节相等；feed `materials_path` 结构 |
| `material_directory` 55/71/72/255 | 无 | DELETE_BARE | 路径集合 / root 隔离 / INDEX 存在 |
| `material_directory` 179/199 | 路径异常 | **KEEP** PATH_CONFINEMENT | 越界抛错 |

## 可复现命令

解释器：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
七 BIN（逐个设置）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_KIMI_BIN=/usr/bin/false
export MING_SIM_GROK_BIN=/usr/bin/false
export MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
```

### 枚举删除侧（相对 52809cdf3）

```bash
git diff 52809cdf3 HEAD --unified=0 -- tests web \
  | rg '^[-].*(assert |expect\(|toContain|toEqual|toMatch|toHaveTextContent)'
# 成员表真源：evidence/1834-fixer-f3-f14/f3_deletion_side_members.jsonl（175 行）
# 人读表：evidence/1834-fixer-f3-f14/f3_deletion_side_member_table.md
```

### 枚举全仓裸 read_material Expr

```bash
python3 - <<'PY'
import ast, pathlib
bare=[]
for path in pathlib.Path('tests').rglob('*.py'):
    tree=ast.parse(path.read_text())
    lines=path.read_text().splitlines()
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            f=n.value.func
            name=f.id if isinstance(f, ast.Name) else getattr(f,'attr',None)
            if name=='read_material':
                bare.append(f'{path}:{n.lineno}:{lines[n.lineno-1].strip()}')
print('\n'.join(bare)); print('count', len(bare))
PY
# 期望仅 2 条 PATH_CONFINEMENT（见 f3_bare_read_material_disposition.jsonl）
```

### 聚焦测试（触及面，非 1253 广聚焦）

```bash
BASETEMP=$(mktemp -d /tmp/1834-f3-pytest-XXXX)
python -m pytest -q -p no:cacheprovider --basetemp="$BASETEMP" --tb=line \
  tests/test_audience_translate_1837.py::test_translate_call_failure_is_not_empty_success_dispatch \
  tests/test_month_call_recovery_1846.py::test_world_translate_exhaustion_keeps_text_resume_retries_translate_only \
  tests/test_relation_read_640.py::test_dto_shape_summary_plus_recent_context_with_backref \
  tests/test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics \
  tests/test_candidate_supply_1893.py::test_surge_candidate_offered_by_world_segment_is_declared_and_lands \
  tests/test_material_directory_1830.py \
  tests/test_gazette_author_1862.py::test_author_archives_own_title_and_same_run_advances \
  tests/test_world_materials_1834.py \
  tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree \
  tests/test_on_scene_immediate_write_1839.py::test_textual_fact_and_public_saying_land_and_show_in_materials \
  tests/test_public_projection_consistency_1830.py::test_scene_person_public_layer_matches_character_and_world_admission \
  tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects \
  tests/test_audience_translate_1837_reopen.py::test_inquiry_declaration_preserves_assignment_in_attendant_materials \
  tests/test_army_display_173.py::test_army_payload_exposes_approx_arrears_text_not_raw \
  tests/test_army_card_status_1501.py::test_army_report_keeps_row_status \
  tests/test_army_card_status_1501.py::test_shared_consumers_still_surface_status
# → 30 passed；日志 focused-pytest-handread.txt
rm -rf "$BASETEMP"
```

### 恒空串变异（自写固定输入输送案必须红）

```bash
SCRATCH=$(mktemp -d /tmp/1834-f3-mut-XXXX)
cat > "$SCRATCH/mut_empty_read.py" <<'EOF'
import ming_sim.materials as materials
def pytest_configure(config):
    materials.read_material = lambda *a, **k: ""
EOF
PYTHONPATH="$SCRATCH" python -m pytest -q -p no:cacheprovider -p mut_empty_read --tb=line \
  tests/test_on_scene_immediate_write_1839.py::test_textual_fact_and_public_saying_land_and_show_in_materials \
  tests/test_gazette_author_1862.py::test_author_archives_own_title_and_same_run_advances \
  tests/test_public_projection_consistency_1830.py::test_scene_person_public_layer_matches_character_and_world_admission \
  tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects \
  tests/test_audience_translate_1837_reopen.py::test_inquiry_declaration_preserves_assignment_in_attendant_materials
# → 5 failed（mutation-red.txt）

cat > "$SCRATCH/mut_empty_arrears.py" <<'EOF'
import ming_sim.db as db
def pytest_configure(config):
    db._approx_wanliang = lambda *a, **k: ""
    db._approx_pay_months = lambda *a, **k: ""
EOF
PYTHONPATH="$SCRATCH" python -m pytest -q -p no:cacheprovider -p mut_empty_arrears --tb=line \
  tests/test_army_display_173.py::test_army_payload_exposes_approx_arrears_text_not_raw
# → 1 failed（mutation-arrears-red.txt）；证明「欠饷约15万两」走格式化通道而非夹具正文
rm -rf "$SCRATCH"
```

绿对照：`mutation-green.txt` → 9 passed（含补回 3 测 + 输送 5 + army_display）。

## 证据文件

| 文件 | 作用 |
| --- | --- |
| `f3_deletion_side_member_table.md` | 175 条手读成员表（source+channel+basis） |
| `f3_deletion_side_members.jsonl` | 机器可读同表 |
| `f3_bare_read_material_disposition.jsonl` | 裸读保留 2 + 删除说明 20 |
| `focused-pytest-handread.txt` | 聚焦 30 passed |
| `mutation-red.txt` / `mutation-arrears-red.txt` / `mutation-green.txt` | 恒空变异 |

## 复杂度 / 合法性

- 无新增机制、无通用 source matcher、无生产出口改动。
- 仅必要测试与证据；F14 未碰。自查二连 done。

## 关票声明

分支未合并 → **不声称 #1834 关闭**。
