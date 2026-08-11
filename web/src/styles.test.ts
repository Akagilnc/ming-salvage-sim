import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync(`${process.cwd()}/src/styles.css`, "utf8");

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
