import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync(`${process.cwd()}/src/styles.css`, "utf8");

describe("浅色卷轴角色级联", () => {
  it("让 live/archive 角色样式胜过浅色 modal 默认值", () => {
    const style = document.createElement("style");
    style.textContent = styles;
    document.head.appendChild(style);

    const live = document.createElement("section");
    live.className = "modal-bg-chat";
    live.innerHTML = `
      <div class="chat-message user"><span class="action">（搁笔）</span><p>卿且直言。</p></div>
      <div class="chat-message attendant aside"><p>御前低语</p></div>
      <div class="chat-message scene"><p>殿门徐启</p></div>
    `;
    const archive = document.createElement("section");
    archive.className = "modal-bg-state";
    archive.innerHTML = `<div class="modal-bg-chat">${live.innerHTML}</div>`;
    document.body.append(live, archive);

    for (const root of [live, archive]) {
      expect(getComputedStyle(root.querySelector(".user p")!).color).toBe("rgb(62, 48, 32)");
      expect(getComputedStyle(root.querySelector(".action")!).color).toBe("rgb(148, 128, 93)");
      const aside = getComputedStyle(root.querySelector(".aside")!);
      expect(aside.backgroundColor).toBe("rgba(255, 238, 198, 0.5)");
      expect(aside.borderTopStyle).toBe("dashed");
      expect(aside.borderTopColor).toBe("rgba(111, 83, 46, 0.5)");
      const scene = getComputedStyle(root.querySelector(".scene")!);
      expect(scene.backgroundColor).toBe("rgba(0, 0, 0, 0)");
      expect(scene.borderTopWidth).toBe("0px");
      expect(getComputedStyle(root.querySelector(".scene p")!).color).toBe("rgb(122, 106, 77)");
    }
  });
});

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
