## 违宪扫描结果（`tests/` 其余文件）

法源：锚定宪法「机器只咬契约，不咬呈现…对自由文本的…措辞/表头机械依赖…视同缺陷」；失败诚实「catch 后照常继续视同缺陷…」；SHARED §13「盯文…直接删」。  
已排除：已知 8 文件盯文条目；`audience_restore`/`beat`/`web_audience_night` 的 teardown 吞失败（已有报告同形）。  
**未发现**：`@pytest.mark.skip` / 无条件 `pytest.skip()`；`toMatchSnapshot` / syrupy 等呈现锁 snapshot。

---

### 1. 人物定性措辞整表锁死（#1023）
- **位置**：`tests/test_character_projection_1023.py:37-50`
- **违反**：锚定 — *「不咬呈现」*；§13 *「盯文」*
- **证据**：
```python
assert row["忠诚"] == "离心已显"
assert row["能力"] == "才具有限"
...
assert "忠诚离心已显" in character_rendered
```
- **说明**：应断言「无裸数值 / 有定性档」，却把用词表锁进回归。

### 2. 局势条件 humanize 整句相等（呈现翻译）
- **位置**：`tests/test_web_issue_condition_display.py:9`、`:26`、`:40`、`:48`、`:56`
- **违反**：锚定 — *「对自由文本的…措辞…机械依赖」*
- **证据**：
```python
assert text == "毛文龙忠诚回稳"
assert text == "袁崇焕状态为在朝"
assert text == "毛文龙所在为辽东"
```
- **说明**：契约应是「隐藏 machine key/阈值」；整句中文一改即红。

### 3. 承诺进度显示串硬锁
- **位置**：`tests/test_commitment_display_348.py:110`、`:126-140`、`:239`
- **违反**：锚定 — *「呈现为人服务，随时可重排」*；§13 *「盯文」*
- **证据**：
```python
assert "到期待裁" in text
assert "直到补齐" in text
assert commitment_display_text(...) == "限4月·已履行2月·还剩2月"
```
- **说明**：应用 typed progress 字段（elapsed/remaining）断言，却咬显示模板。

### 4. 军饷/忠诚呈现措辞硬断言（同 drawers 盯文形态）
- **位置**：`tests/test_army_display_173.py:72-75`、`:87`
- **违反**：锚定 — *「不咬呈现」*；§13 *「盯文」*
- **证据**：
```python
assert "欠饷约60万两" in joined
assert "忠诚：尚稳" in joined
# ... expected in ("欠饷约15万两", "欠饷约30万两")
```
- **说明**：P4「无裸数」可用负向断言；正向锁死奏报口吻措辞属盯文。

### 5. 地区城防表头/门数文案硬断言
- **位置**：`tests/test_region_citydefense_display.py:22`、`:31-32`、`:47`
- **违反**：锚定 — *「表头机械依赖」*；§13 *「盯文」*
- **证据**：
```python
assert "城防炮5门" in rep
assert "城市等级" in det
assert f"城防{label}" in detail  # 简陋/坚固/雄城
```
- **说明**：应断言 payload/字段有城防数据，不锁报告散文与等级用词。

### 6. CLI 技能卡定性文案硬断言
- **位置**：`tests/test_player_payload_1022.py:151-154`
- **违反**：锚定 / §13 *「盯文」*
- **证据**：
```python
assert "忠诚可托腹心" in rendered
assert "能力才具出众" in rendered
assert "清廉操守清正" in rendered
```
- **说明**：与 #1023 同病：锁定性词表；负向「无忠诚88」已够。

### 7. 建筑定性三元组字面锁死
- **位置**：`tests/test_qualitative.py:28`
- **违反**：§13 *「盯文」*；锚定 *「不咬呈现」*
- **证据**：
```python
assert building_qualitative_fields(row) == ("初设", "残损", "低")
```
- **说明**：共享呈现词表被测成机械契约；改词表必假红。

### 8. fixture/finally 吞 `close` 失败（其余文件）
- **位置**：`tests/test_new_game_smoke.py:51-54`；`tests/test_rejection_wiring.py:801-804`；`tests/test_office_inference.py:242-245`
- **违反**：失败诚实 — *「catch 后照常继续视同缺陷，除非…文档化契约」*
- **证据**：
```python
try:
    sess.close()
except Exception:
    pass
```
- **说明**：teardown/finally 静默吞任意异常，close 真失败不落痕、灯仍绿。

---

**未列入（刻意放过）**：财政/拒收 reason 等闸类契约字面；条件性 `pytest.skip`（缺基底数据）；`capture_chat_rollback_snapshot` / settle golden（状态/数值，非呈现锁）。
