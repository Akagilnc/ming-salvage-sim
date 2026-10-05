# #1900 修内司回执 — J6 / J19（base c7d876145）复核修正

## 授权与跳过说明
- 末份判词未结仅 J6、J19；本轮复核修正 J6 变异证明与成员处置收窄。
- 根因判词已有取证；无须猜诊断（diagnosing-bugs Phase 3 跳过）。
- 官方能力：pytest `ExceptionInfo` / 对象身份 / `__cause__`；Python exception chaining。

## 分支 / 提交
- 工作分支：`ak-roles/1900-j6-j19-fixer-c7d876145`
- commitSha：见本轮 git 查询（提交后填入报告）

## J6 纠正（本轮）
### 1. 变异证明（弃用旧整入口替换）
- **弃用**：`mutations.log` / `mutations.txt` / `mutations-summary.txt`（整段替换 `minister_chat` / `atomic_and_reload`，未经过真实双故障）。
- **有效**：`run_mutations.py` → `mutations-valid.log` / `mutations-valid-summary.txt`
  - 方法：`inspect.getsource` + `compile`/`exec` 绑定**现役模块** `globals`；只改最终 rethrow／`original` 诊断赋值
  - ACTUAL_DOUBLE_FAULT 已记录：
    - CLI：`RuntimeError/LLM down` + `RuntimeError/rollback failed`
    - 月链：`RuntimeError/edict settle crashed` + `OSError/error pack unwritable`
    - reload：`RuntimeError/orig` + `ValueError/reload failed`
  - strong+wrong-primary：3 red；restore：3 green；weak+wrong-primary：3 false-green；final：3 green

### 2. 断言形态
- 三案改用**注入异常对象／str** 作期望（`is` / `args` / `str(settle_error)`），不散落硬编码措辞。

### 3. 成员表全类边界
- `j6-members.md`：125 弱候选逐项语义处置（`j6-disposition.jsonl`）
- 明确：**必要失败行为被吞**与原诊断保真同属 J6；禁止「无双故障默认 KEEP」
- 枚举脚本改为只写 `j6-inventory.md`，不再覆盖处置表

## J19
- 前轮结清维持；本轮未重开

## 聚焦测试
见 `focused-tests-recheck.txt`（七变量前缀）

## 未结（如实）
- J21 押解核账缺口：给事中／票庭
- 不声称已 merge / 关票
