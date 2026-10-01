/**
 * #1302/#1303 前端资源卫生：构建产物零外链 + 本地 favicon。
 * seam = vite build 产出的 dist/index.html 与打包 CSS（玩家首屏实际加载面）。
 */
import { execSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const distDir = join(root, "dist");

function listFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) listFiles(full, acc);
    else acc.push(full);
  }
  return acc;
}

function externalResourceUrls(text: string): string[] {
  const found = new Set<string>();
  // Read HTML attributes through the platform parser, not source quoting/order.
  const document = new DOMParser().parseFromString(text, "text/html");
  for (const element of document.querySelectorAll("[href], [src]")) {
    for (const name of ["href", "src"]) {
      const value = element.getAttribute(name);
      if (value && /^https?:\/\//i.test(value)) found.add(value);
    }
  }
  // CSS url(...) absolute
  for (const m of text.matchAll(/url\(\s*['"]?(https?:\/\/[^'")\s]+)['"]?\s*\)/gi)) {
    found.add(m[1]);
  }
  // @import absolute
  for (const m of text.matchAll(/@import\s+(?:url\()?['"]?(https?:\/\/[^'")\s]+)['"]?\)?/gi)) {
    found.add(m[1]);
  }
  return [...found];
}

describe("构建产物资源卫生 #1302/#1303", () => {
  it("dist 零外链资源，且含本地 favicon", () => {
    execSync("npm run build", { cwd: root, stdio: "pipe", env: process.env });
    expect(existsSync(join(distDir, "index.html"))).toBe(true);

    const index = readFileSync(join(distDir, "index.html"), "utf8");
    const cssFiles = listFiles(distDir).filter((f) => f.endsWith(".css"));
    const surfaces = [index, ...cssFiles.map((f) => readFileSync(f, "utf8"))];

    const external: string[] = [];
    for (const text of surfaces) {
      external.push(...externalResourceUrls(text));
    }
    expect(external).toEqual([]);

    // favicon link is present and points at a same-origin path (no protocol-host)
    const document = new DOMParser().parseFromString(index, "text/html");
    const faviconHref = document.querySelector('link[rel~="icon" i]')?.getAttribute("href");
    expect(faviconHref).toBeTruthy();
    expect(faviconHref).not.toMatch(/^https?:\/\//i);

    const faviconPath = faviconHref!.startsWith("/")
      ? join(distDir, faviconHref!.slice(1))
      : join(distDir, faviconHref!);
    expect(existsSync(faviconPath)).toBe(true);
  }, 120_000);
});
