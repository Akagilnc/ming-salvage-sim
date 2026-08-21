import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const stylesDir = `${process.cwd()}/src/styles`;
const styles = readdirSync(stylesDir)
  .filter((f) => f.endsWith(".css"))
  .map((f) => readFileSync(`${stylesDir}/${f}`, "utf8"))
  .join("\n");

describe("窄屏召见布局", () => {
  it("保留两列并让左栏滚动，避免密令被立绘裁掉", () => {
    const narrowLayout = styles.match(
      /\.chat-full-grid\s*\{[^}]*minmax\(120px,\s*38%\)\s+minmax\(0,\s*1fr\);[^}]*\}[\s\S]*?\.minister-side\s*\{[^}]*\}/,
    )?.[0];

    expect(narrowLayout).toBeDefined();
    expect(narrowLayout).toContain("grid-template-columns: minmax(120px, 38%) minmax(0, 1fr);");
    expect(narrowLayout).not.toContain("overflow: hidden;");
    expect(narrowLayout).toContain("overflow-y: auto;");
  });
});

describe("#1342 朝堂抽屉不得挡底栏命令", () => {
  it("drawer-scrim / court-drawer 底部留出命令安全区", () => {
    const scrim = styles.match(/\.drawer-scrim\s*\{[^}]*\}/)?.[0] || "";
    const drawer = styles.match(/\.court-drawer\s*\{[^}]*\}/)?.[0] || "";
    expect(scrim).toMatch(/bottom:\s*(max\(|[1-9]\d|calc)/);
    expect(drawer).toMatch(/bottom:\s*(max\(|[1-9]\d|calc)/);
    // 不得再 inset:0 盖死底栏
    expect(scrim).not.toMatch(/inset:\s*0/);
    expect(drawer).not.toMatch(/inset:\s*0/);
  });
});

describe("#1454 拟诏台不得挡底栏拟诏木牌", () => {
  it("edict-safe-cmd 层底部留出命令安全区（修 desk-footer 遮挡）", () => {
    const layer = styles.match(/\.fullscreen-layer\.edict-safe-cmd\s*\{[^}]*\}/)?.[0] || "";
    expect(layer).toBeTruthy();
    expect(layer).toMatch(/bottom:\s*(max\(|[1-9]\d|calc)/);
    // 不得 inset:0 把收起木牌盖死在 desk-footer 下
    expect(layer).not.toMatch(/inset:\s*0/);
  });
});

describe("#1352 地图驻军表头不拆字", () => {
  it("garrison intel 表头 nowrap / keep-all", () => {
    expect(styles).toMatch(/\.intel-table--garrison[^{]*thead th[^{]*\{[^}]*white-space:\s*nowrap/);
  });
});

describe("#1387 邸报可滚完", () => {
  it("gazette-document 在 modal 内 min-height:0 + overflow-y auto", () => {
    const block = styles.match(/\.gazette-document\s*\{[^}]*\}/g)?.join("\n") || "";
    expect(block).toMatch(/overflow-y:\s*auto/);
    expect(block).toMatch(/min-height:\s*0/);
  });
});

describe("#1398 邸报朕知道了视口常显", () => {
  it("gazette-shell 分栏：document 可滚、dismiss 不随文滚走", () => {
    const shell = styles.match(/\.gazette-shell\s*\{[^}]*\}/)?.[0] || "";
    expect(shell).toMatch(/display:\s*flex/);
    expect(shell).toMatch(/flex-direction:\s*column/);
    const dismiss = styles.match(/\.gazette-dismiss\s*\{[^}]*\}/)?.[0] || "";
    expect(dismiss).toMatch(/flex:\s*0\s+0\s+auto/);
  });
});

describe("#1486 邸报底栏不与卷轴末行混层", () => {
  it("modal-bg-gazette 下 dismiss 有实底，压过 * transparent", () => {
    // 行为面：按钮区自带实底，不与卷轴底缘半裁切行共透底层
    const starred = styles.match(/\.modal-bg-gazette\s+\*\s*\{[^}]*\}/)?.[0] || "";
    expect(starred).toMatch(/background:\s*transparent/);
    const dismiss = styles.match(/\.modal-bg-gazette\s+\.gazette-dismiss\s*\{[^}]*\}/)?.[0] || "";
    const bg = dismiss.match(/background:\s*([^;}]+)/)?.[1]?.trim() || "";
    // 真断言：现有四分量 rgba 第四分量 alpha 必须 finite 且 >0；缺失或 rgba(...,0) 必失败
    const alpha = Number(
      bg.match(/^rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)$/i)?.[1],
    );
    expect(Number.isFinite(alpha)).toBe(true);
    expect(alpha).toBeGreaterThan(0);
  });
});

describe("#1475 召对顶栏回收版面", () => {
  it("chat 大横幅轨不压过 modal-header-bare（hideTitle 时高度归零）", () => {
    // 大字居中横幅 min-height:78px 不得以更高特异性压过 bare 的 min-height:0，
    // 否则 hideTitle 仍占约 1/6 屏。要么 :not(.modal-header-bare)，要么显式 bare 覆盖。
    const fatBlocks = [...styles.matchAll(/[^{}]*modal-bg-chat[^{}]*modal-header[^{}]*\{[^}]*min-height:\s*78px[^}]*\}/g)].map((m) => m[0]);
    for (const fat of fatBlocks) {
      expect(fat).toMatch(/:not\(\s*\.modal-header-bare\s*\)/);
    }
    const bareOverride = [...styles.matchAll(/[^{}]*modal-bg-chat[^{}]*modal-header-bare[^{}]*\{[^}]*\}/g)].map((m) => m[0]);
    const bareOk = bareOverride.some((block) => /min-height:\s*0/.test(block));
    expect(fatBlocks.length > 0 || bareOk).toBe(true);
  });
});
