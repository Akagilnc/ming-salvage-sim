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
