# orchestrator 失败诚实 · 违宪扫描

**法源**：「接住可以，洗白不行」；「未识别异常不得冒用具体标签」；「真因必须落痕」；「catch 后照常继续视同缺陷，除非『此失败下继续』是文档化契约」；「重试循环掩盖持续性失败」；裸/空 catch。  
**范围**：`orchestrator/` Node 运行时（含 `src/**/*.ts`；字面 `.mjs/.cjs` 另述）。限时快扫，宁缺毋滥。

---

## 1. [严重] merge 确认：任意异常冒用 `not_merged`，再重试洗成「未确认 MERGED」

**位置**：`orchestrator/src/family/landing.ts:749-753`（同环 `782-784`）

**违反条文**：「未识别异常不得冒用具体标签」；「重试循环掩盖持续性失败」；「真因必须落痕」

**证据**：
```749:753:orchestrator/src/family/landing.ts
          try {
            alignment = confirmAlignment(completionHeadOid);
          } catch {
            alignment = { kind: "not_merged" };
          }
```

**说明**：`gh`/auth/解析失败与「传播滞后未合并」共用 `not_merged`，最多再转 3 次后只报「live GitHub state did not confirm MERGED」，真因蒸发。同环 `fetchState` 空 catch（约 L782）继续轮询，属同一洗白。

---

## 2. [严重] leg slug 解析：配置/IO 真失败冒用「unknown cmr review leg slug」

**位置**：`orchestrator/src/modelRoutes.ts:434-441`（经 `modelFamilyForSlug` → `loadModelData`）

**违反条文**：「未识别异常不得冒用具体标签」；「真因必须落痕」

**证据**：
```434:441:orchestrator/src/modelRoutes.ts
  try {
    return { slug: trimmed, family: modelFamilyForSlug(trimmed) };
  } catch {
    throw new Error(
      `unknown cmr review leg slug "${trimmed}". Register a live worker in ` +
        "model-data config before selecting it in a route.",
    );
  }
```

**说明**：`loadModelData` 缺文件/坏 JSON/坏形状会抛具体原因；此处裸 catch 一律改写成「未知 slug」，leg 路由把配置崩坏洗成选错模型。

---

## 3. [高] child 分支存在探测：任意 `rev-parse` 失败当成「不存在」

**位置**：`orchestrator/src/family/realFamilyBackend.ts:3653-3668`

**违反条文**：「未识别异常不得冒用具体标签」；「catch 后照常继续视同缺陷…」

**证据**：
```3653:3668:orchestrator/src/family/realFamilyBackend.ts
          try {
            const childHead = sh(["rev-parse", "--verify", `${childBranch}^{commit}`]);
            return { exists: true, childHead };
          } catch {
            return { exists: false };
          }
        ...
          } catch {
            // continue to next candidate
          }
```

**说明**：同文件 `isAncestor`（约 L3675-3679）已区分 exit 1 vs 128；此处把坏对象/坏仓等运营失败洗成 `exists: false`，下游可按「已合并/可跳过」继续。

---

## 4. [中] spawn 采纳失败清理：子进程 `exitPromise` 空 catch，次因不落痕

**位置**：`orchestrator/src/dispatchRetry.ts:102-107`

**违反条文**：「真因必须落痕」；空 catch

**证据**：
```102:107:orchestrator/src/dispatchRetry.ts
  try {
    await input.exitPromise;
  } catch {
    // Preserve the original spawn-persist error if child cleanup fails.
  }
```

**说明**：主因会再抛 `AdoptionPersistFailedError`，但 cleanup/exit 次因被吞，spawn 路径排障少一环。

---

## 5. [中] HEAD 观测失败静默回落 fallback，无落痕

**位置**：`orchestrator/src/family/landing.ts:297-302`；同形 `orchestrator/src/family/verifyCmr.ts:1595-1600`

**违反条文**：「catch 后照常继续视同缺陷…」；「真因必须落痕」

**证据**：
```297:302:orchestrator/src/family/landing.ts
  try {
    const head = (await backend.readFamilyHead(familyBase)).trim();
    return head.length > 0 ? head : fallback;
  } catch {
    return fallback;
  }
```

**说明**：读仓头失败与「空头」一样走 fallback，无错误包/日志；非文档化的「此失败下继续」契约。

---

### 字面 `.js/.mjs/.cjs`（不含 dist）

`scripts/online-review-durable-bin.mjs` 的裸 catch（`isPidAlive` / `processStarttime` / lock reclaim / JSONL corrupt→`die`）为锁与进程探测或 fail-closed，**未计入上表**。`apply-sandcastle-cancel-patch.mjs` / `launch-362.mjs` / `fast-tax-preload.cjs` **无**同类业务洗白。

**结论**：交付相关面上记 **5** 条（2 严重 / 1 高 / 2 中）；最重是 landing merge 确认把异常洗成 `not_merged` 再重试，以及 leg 路由把 model-data 真失败冒充「未知 slug」。
