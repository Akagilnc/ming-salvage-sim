import { execFile } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const require = createRequire(import.meta.url);
const execFileAsync = promisify(execFile);

/** Runs real Chromium geometry checks for every viewport in one existing Electron process. */
export async function measureElectronLayout<T>(
  pageHtml: string,
  css: string,
  viewports: Array<{ width: number; height: number }>,
  measureSource: string,
): Promise<T[]> {
  const dir = mkdtempSync(join(tmpdir(), "electron-layout-"));
  try {
    writeFileSync(
      join(dir, "fixture.html"),
      `<!doctype html><html><head><meta charset="utf-8" /><style>${css.replace(/</g, "\\u003c")}</style></head><body>${pageHtml}</body></html>`,
    );
    writeFileSync(
      join(dir, "main.cjs"),
      [
        'const { app, BrowserWindow } = require("electron");',
        'const path = require("path");',
        'app.commandLine.appendSwitch("headless");',
        'app.commandLine.appendSwitch("no-sandbox");',
        `const viewports = ${JSON.stringify(viewports)};`,
        "app.whenReady().then(async () => {",
        "  const first = viewports[0];",
        "  const win = new BrowserWindow({ width: first.width, height: first.height, show: false, webPreferences: { offscreen: true } });",
        '  await win.loadFile(path.join(__dirname, "fixture.html"));',
        "  const results = [];",
        "  for (const viewport of viewports) {",
        "    win.setContentSize(viewport.width, viewport.height);",
        // Wait until the renderer actually observes the target content size.
        // setContentSize is async w.r.t. window.innerWidth/innerHeight; a 0ms
        // timer races under full-suite load and measures the previous viewport.
        "    await win.webContents.executeJavaScript(",
        "      '(async (w, h) => {' +",
        "      '  const deadline = Date.now() + 5000;' +",
        "      '  while (innerWidth !== w || innerHeight !== h) {' +",
        "      '    if (Date.now() > deadline) {' +",
        "      '      throw new Error(\"viewport resize timeout: \" + innerWidth + \"x\" + innerHeight + \" != \" + w + \"x\" + h);' +",
        "      '    }' +",
        "      '    await new Promise((r) => requestAnimationFrame(r));' +",
        "      '  }' +",
        "      '})(' + viewport.width + ', ' + viewport.height + ')'",
        "    );",
        `    results.push(await win.webContents.executeJavaScript(${JSON.stringify(measureSource)}));`,
        "  }",
        "  process.stdout.write(JSON.stringify(results));",
        "  app.exit(results.some((result) => result && result.error) ? 1 : 0);",
        "});",
        "",
      ].join("\n"),
    );
    const electronPath = require("electron") as string;
    const { stdout } = await execFileAsync(electronPath, [join(dir, "main.cjs")], {
      timeout: 60_000,
      env: { ...process.env, ELECTRON_NO_ATTACH_CONSOLE: "1" },
    });
    const results = JSON.parse(stdout) as Array<T & { error?: string }>;
    const error = results.find((result) => result?.error)?.error;
    if (error) throw new Error(error);
    return results;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
