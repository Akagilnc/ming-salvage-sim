# 0149 — 点颁布/退朝即进核账期；未了之事续跑、不打回

Status: proposed（陛下 2026-08-16：「点了以后继续走。不需要打回再点。」）

## 决定

**玩家一点颁布或退朝，会话内即入核账期，不因尚有未了之事未落账而打回或逼再点一次。** 核账期内等未了办完，再按既有收夜 / 结算次序自动往下走。未了不等于失败，不得与真失败长成同一种中止。真失败仍 fail-closed（[ADR 0036](0036-audience-night-restore-resume-at-last-entry.md) 收夜前须清空待补、仍失败则中止的原意不动），皇帝见人话；失败态全面设计另议。本条不改写 0036 射程。入核账期后皇帝看见什么，见 [ADR 0148](0148-settlement-period-shows-month-open-snapshot-not-engine-mid-state.md)。

## 为什么

若点退朝时仍有未了之事，闸口把「未了」与「办砸了」糊成同一种打回，皇帝先被打断再被要求重点——与「点了以后继续走」直接冲突，也让 [ADR 0148](0148-settlement-period-shows-month-open-snapshot-not-engine-mid-state.md) 的核账呈现无从起算。

## 边界

- 不改写 [ADR 0036](0036-audience-night-restore-resume-at-last-entry.md) 射程与真失败 fail-closed。
- 不改 [ADR 0008](0008-settlement-applier-contract-and-transaction-boundary.md) 的 phase / 事务 / 恢复。
- 可见面与月初真源归 0148；本条只钉入口起算与未了续跑。

## 否决的备选（防日后重议）

- **未了与真失败一视同仁打回再点**：与「一点即进」冲突，逼玩家为时序重点。
- **为区分未了而改写 0036 射程**：越出本条；真要动 0036 须另呈。
