# 军事流程探针

用于验证军事盘面动作能否从 sim 推演的固定「军事」大章进入军务抽取，并正确落到 `armies` / `army_logs`。覆盖建军、扩编、缩编、裁撤、改编制、改统帅、调度。

## 跑法

```bash
.venv/bin/python scripts/military_flow_probe.py \
  --db data/military_flow_probe.db \
  --out scripts/runs/military_flow_probe_result.json
```

脚本会删除同名测试库后重跑三回合。需要 `.env` 或当前 shell 中已有 `OPENAI_API_KEY`，可选 `OPENAI_BASE_URL` / `OPENAI_MODEL`。

## 三回合流程

1. 1627 年 10 月：关宁军统帅由袁崇焕改为孙承宗；新建 `神枢新军`，驻京师昌平，徐光启统帅，兵额 8000，月维护费 2。
2. 1627 年 11 月：神枢新军扩编 3000、裁汰 1000，净增 2000；改为火器步兵、炮兵、车营辎重；统帅改为孙承宗；调往辽东宁远；补给和机动下降，训练和装备上升。
3. 1627 年 12 月：神枢新军裁撤 3000，月维护费减 1；关宁军裁撤老弱空额 5000，月维护费减 1。

## 必查断言

```bash
sqlite3 data/military_flow_probe.db \
  "SELECT year,period,turn,turn_phase FROM game_state; SELECT COUNT(*) FROM turn_logs;"

sqlite3 -header -column data/military_flow_probe.db "
SELECT id,name,owner_power,station,commander,troop_type,
       manpower,maintenance_per_turn,supply,morale,training,equipment,
       arrears,mobility,loyalty,status
FROM armies
WHERE id='guanning' OR name LIKE '%神枢%'
ORDER BY id;"

sqlite3 -header -column data/military_flow_probe.db "
SELECT turn,year,period,army_id,field,old_value,new_value,delta,reason
FROM army_logs
WHERE army_id='guanning'
   OR army_id IN (SELECT id FROM armies WHERE name LIKE '%神枢%')
ORDER BY id;"

sqlite3 -header -column data/military_flow_probe.db "
SELECT turn,year,period,substr(report,instr(report,'、军事')-8,420) AS military_slice
FROM turn_reports
ORDER BY turn;"
```

通过标准：

- `turn_logs=3`，`game_state` 推进到第 4 回合待召见。
- 三篇 `turn_reports` 都有独立大章 `军事`，位置在普通事件章之后。
- 只存在一支 `神枢新军`，不得因后续扩编/裁撤重复建军。
- `army_logs` 能看到：关宁军换统帅；神枢新军 created；神枢新军 +2000、维护费 +1、改兵种、改统帅、调驻地、训练 +8、装备 +5、补给 -5、机动 -5；神枢新军 -3000、维护费 -1；关宁军 -5000、维护费 -1。

## 本次实测结果

时间：2026-05-27。

结果：通过。最终状态：

- `guanning`：统帅孙承宗，兵额 67000，月维护费 14，状态 `裁汰空额后整饬、欠饷待发`。
- `shenshu_new_army`：兵额 7000，月维护费 2，驻 `辽东 / 宁远`，统帅孙承宗，兵种 `火器步兵、炮兵、车营辎重`，状态 `裁撤老弱后驻辽东并整训火器`。

注意：第二回合邸报曾把已存在的神枢新军状态更新写在 `新建军队` 行，但抽取器没有重复建军，仍正确落到 `军队变化`。已在 `season_simulator.md` 加硬约束：`input.armies` 已有军队后续变化只能写 `军队变化`。

## 大凌河投敌探针

用于验证“大凌河之围”里人物投敌与成建制降军能否落盘。起始时间固定为事件前一个月 `1631.07`，跑两回合：

1. 1631 年 7 月：祖大寿率关宁军精锐二万人移驻 `辽东 / 大凌河城`，关宁军统帅改为祖大寿，状态改为被围断粮。
2. 1631 年 8 月：祖大寿降后金；关宁军本体减二万人并退守锦州宁远；另建 `祖大寿降军`，归属后金，驻 `辽东 / 大凌河降营`。

跑法：

```bash
.venv/bin/python scripts/dalinghe_defection_probe.py \
  --db data/dalinghe_defection_probe.db \
  --start-ym 1631.07 \
  --out scripts/runs/dalinghe_defection_probe_result.json
```

必查断言：

```bash
sqlite3 -header -column data/dalinghe_defection_probe.db "
SELECT name,power_id,status,office
FROM characters
WHERE name='祖大寿';"

sqlite3 -header -column data/dalinghe_defection_probe.db "
SELECT id,name,owner_power,station,commander,manpower,maintenance_per_turn,status
FROM armies
WHERE id='guanning'
   OR name LIKE '%祖%'
   OR commander LIKE '%祖大寿%'
ORDER BY id;"

sqlite3 -header -column data/dalinghe_defection_probe.db "
SELECT turn,year,period,army_id,field,old_value,new_value,delta,reason
FROM army_logs
WHERE army_id='guanning'
   OR army_id IN (SELECT id FROM armies WHERE name LIKE '%祖%' OR commander LIKE '%祖大寿%')
ORDER BY id;"
```

通过标准：

- `characters` 中祖大寿 `power_id='houjin'`。
- `armies` 中出现 `祖大寿降军`，`owner_power='houjin'`，驻地为 `辽东 / 大凌河降营`，统帅为祖大寿。
- `guanning` 仍为 `owner_power='ming'`，但兵额减少 20000，月维护费减少 4，驻地退到锦州宁远，状态说明大凌河所部投后金。
- `army_logs` 有 `zu_dashou_defectors created`，同时有 `guanning` 的减员、减维护费、降补给/士气/忠诚、改驻地和改状态记录。

实测结果：通过。最终状态：

- `祖大寿`：`power_id=houjin`。
- `guanning`：`owner_power=ming`，兵额 52000，月维护费 11，驻 `辽东 / 锦州宁远`，状态 `大凌河所部投后金、宁锦余部退守锦州宁远`。
- `zu_dashou_defectors`：`祖大寿降军`，`owner_power=houjin`，兵额 20000，驻 `辽东 / 大凌河降营`，统帅祖大寿，状态 `新降后金、待皇太极改编`。

备注：测试中曾尝试直接把整个 `关宁军 / 宁锦防线` 改为后金，但这会把宁锦余部也错误转走。更合理的盘面表达是“关宁军减员 + 新建后金降军实体”，后续测试按此标准复用。

## 关宁拉满北伐探针

用于验证“关宁军补给、士气、训练、装备显著超过后金八旗”时，sim 是否能推演出收复辽沈、进取建州，并把地区控制权与军队调度真正落盘。起始时间固定为 `1632.01`，跑三回合：

1. 1632 年 1 月：倾太仓与内帑整饬关宁军，统帅改为孙承宗，兵额补至 80000，补给、士气、训练、装备拉到 95，欠饷清零。
2. 1632 年 2 月：关宁军、山海关、东江、登莱合攻沈阳 / 辽阳；沈阳 / 辽阳控制改为明，关宁军调驻辽东 / 沈阳辽阳一线，满洲八旗退回建州。
3. 1632 年 3 月：三路进逼建州 / 赫图阿拉；建州控制改为明，关宁军调驻建州 / 赫图阿拉，满洲八旗主力溃散。

跑法：

```bash
.venv/bin/python scripts/guanning_northern_expedition_probe.py \
  --db data/guanning_northern_expedition_probe.db \
  --start-ym 1632.01 \
  --out scripts/runs/guanning_northern_expedition_probe_result.json
```

必查断言：

```bash
sqlite3 -header -column data/guanning_northern_expedition_probe.db "
SELECT id,name,controlled_by,military_pressure,status
FROM regions
WHERE id IN ('liaodong','shenyang_liaoyang','jianzhou','dongjiang_area')
ORDER BY id;"

sqlite3 -header -column data/guanning_northern_expedition_probe.db "
SELECT id,name,owner_power,station,commander,manpower,
       supply,morale,training,equipment,arrears,status
FROM armies
WHERE id IN ('guanning','manchu_banners_main','shanhaiguan','dongjiang','denglai')
ORDER BY id;"

sqlite3 -header -column data/guanning_northern_expedition_probe.db "
SELECT turn,year,period,region_id,field,old_value,new_value,delta,reason
FROM region_logs
WHERE region_id IN ('liaodong','shenyang_liaoyang','jianzhou')
ORDER BY id;"
```

通过标准：

- `shenyang_liaoyang.controlled_by='ming'`，且 `region_logs` 有对应 `controlled_by` 记录。
- `jianzhou.controlled_by='ming'`，且 `region_logs` 有对应 `controlled_by` 记录。
- `guanning` 统帅为孙承宗，兵额 80000，补给 / 士气 / 训练 / 装备均为 95，欠饷 0。
- `guanning.station` 先改为 `辽东 / 沈阳辽阳一线`，最终改为 `建州 / 赫图阿拉`。
- `manchu_banners_main` 兵额从 62000 降到 20000，补给、士气、训练、装备、忠诚均下降，状态为主力溃散。

实测结果：通过。最终状态：

- `shenyang_liaoyang`：`controlled_by=ming`，军事压力降到 2，状态 `收复辽沈，设留守司，招抚流亡`。
- `jianzhou`：`controlled_by=ming`，状态 `后金退守，坚壁清野`。
- `guanning`：驻 `建州 / 赫图阿拉`，统帅孙承宗，兵额 80000，补给 / 士气 / 训练 / 装备均为 95，欠饷 0，状态 `收复建州、辽东威胁解除`。
- `manchu_banners_main`：兵额 20000，补给 26，士气 46，训练 66，装备 58，状态 `主力溃散、贝勒内讧、余部北遁`。
- `victory_status` 仍为 `ongoing`：后金综合 189，明辽东防线综合 410，但京畿压力 70、北方民变 75，说明军事收复路径成立，却不会自动消除财政和内地民变危机。
