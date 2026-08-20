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
  // href/src absolute URLs (resource links)
  for (const m of text.matchAll(/\b(?:href|src)\s*=\s*["'](https?:\/\/[^"']+)["']/gi)) {
    found.add(m[1]);
  }
  // CSS url(...) absolute
  for (const m of text.matchAll(/url\(\s*['"]?(https?:\/\/[^'")\s]+)['"]?\s*\)/gi)) {
    found.add(m[1]);
  }
  // @import absolute
  for (const m of text.matchAll(/@import\s+(?:url\()?['"]?(https?:\/\/[^'")\s]+)['"]?\)?/gi)) {
    found.add(m[1]);
  }
  // preconnect/dns-prefetch targets often appear as bare https in link tags already caught;
  // also catch fonts host strings that might slip into bundled CSS as @font-face src.
  for (const host of ["fonts.googleapis.com", "fonts.gstatic.com"]) {
    if (text.includes(host)) found.add(`https://${host}`);
  }
  return [...found];
}

describe("源 index.html 字体卫生 #1332/#1412", () => {
  it("web/index.html 不引 Google Fonts 外网（截图/离线不阻塞）", () => {
    // #1412 已去三外链；本钉锁源入口不再回归。prototypes/ 不在玩家首屏路径，不扫。
    const indexPath = join(root, "index.html");
    expect(existsSync(indexPath)).toBe(true);
    const html = readFileSync(indexPath, "utf8");
    expect(externalResourceUrls(html)).toEqual([]);
    for (const host of ["fonts.googleapis.com", "fonts.gstatic.com"]) {
      expect(html).not.toContain(host);
    }
    // 无 @import 远程样式、无 stylesheet 指向 http(s)
    expect(html).not.toMatch(/@import\s+url\(\s*['"]?https?:/i);
    expect(html).not.toMatch(
      /rel=["']stylesheet["'][^>]*href=["']https?:/i,
    );
  });
});

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
    const faviconHref = index.match(
      /rel=["'](?:icon|shortcut icon)["'][^>]*href=["']([^"']+)["']/i,
    )?.[1]
      ?? index.match(
        /href=["']([^"']+)["'][^>]*rel=["'](?:icon|shortcut icon)["']/i,
      )?.[1];
    expect(faviconHref).toBeTruthy();
    expect(faviconHref).not.toMatch(/^https?:\/\//i);

    const faviconPath = faviconHref!.startsWith("/")
      ? join(distDir, faviconHref!.slice(1))
      : join(distDir, faviconHref!);
    expect(existsSync(faviconPath)).toBe(true);
  }, 120_000);
});
