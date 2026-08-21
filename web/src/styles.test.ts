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

  it("#1458 安全区跟随 hud2-stage 实际底边，方/竖视口不盖收起木牌", () => {
    // 固定 22vh 在 800×800 时 layer 底边 y=624，而 stage 居中后木牌约 y=519–600，整块被盖。
    // 安全区须按 stage 高度/letterbox 计算（与 .hud2-stage 的 min(100vh, 100vw*1440/2560) 同构）。
    const layer = styles.match(/\.fullscreen-layer\.edict-safe-cmd\s*\{[^}]*\}/)?.[0] || "";
    expect(layer).toMatch(/--hud2-stage-h|1440\s*\/\s*2560|76\.5/);
    expect(layer).toMatch(/bottom:\s*max\(/);
    // 不得只剩与 stage 无关的裸 22vh
    expect(layer.replace(/\/\*[^*]*\*\//g, "")).not.toMatch(/bottom:\s*max\(\s*148px\s*,\s*22vh\s*\)/);
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

describe("#1480 / #1499 hideTitle 单行 1fr 不误伤有标题栏 modal-bg-chat", () => {
  it("单行 minmax(0,1fr) 只挂 .modal-layout-bare；裸 modal-bg-chat.fullscreen-modal 不得单行", () => {
    // bare 路径：组件 hideTitle → .modal-layout-bare，正文落唯一 1fr 行有界。
    const bare = [...styles.matchAll(/[^{.]*\.modal-bg-chat\.fullscreen-modal\.modal-layout-bare[^{}]*\{[^}]*\}/g)]
      .map((m) => m[0])
      .filter((b) => /grid-template-rows/.test(b));
    const bareOk = bare.some((b) => /grid-template-rows:\s*minmax\(\s*0\s*,\s*1fr\s*\)\s*;/.test(b)
      && !/grid-template-rows:\s*auto/.test(b));
    expect(bare.length).toBeGreaterThan(0);
    expect(bareOk).toBe(true);

    // 有标题栏路径（起居注 / 政务失败恢复）：不得对裸 .modal-bg-chat.fullscreen-modal 写单行 1fr，
    // 否则可见标题被塞进唯一显式行、正文落隐式 auto 行遭 overflow:hidden 裁切。
    const unscoped = [...styles.matchAll(/[^{.]*\.modal-bg-chat\.fullscreen-modal\s*\{[^}]*\}/g)]
      .map((m) => m[0])
      .filter((b) => /grid-template-rows/.test(b));
    expect(unscoped).toHaveLength(0);
  });

  it("基础 .fullscreen-modal 正向钉两行网格 auto + minmax(0,1fr)", () => {
    // 有标题栏默认：首行 auto 吃 header，正文落 minmax(0,1fr)。bare 覆盖不得抹掉此默认。
    // 只读 modals.css 顶层真源——拼接全库会把媒体查询/后裔选择器里的同名块误认作基础规则。
    const modalStyles = readFileSync(`${stylesDir}/modals.css`, "utf8");
    const base = [...modalStyles.matchAll(/(?:^|})\s*\.fullscreen-modal\s*\{[^}]*\}/g)]
      .map((m) => m[0])
      .filter((b) => /grid-template-rows/.test(b));
    const ok = base.some((b) =>
      /grid-template-rows:\s*auto\s+minmax\(\s*0\s*,\s*1fr\s*\)\s*;/.test(b),
    );
    expect(base.length).toBeGreaterThan(0);
    expect(ok).toBe(true);
  });
});
