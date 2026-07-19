import { vi } from "vitest";

import {
  execFile,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
  tmpdir,
  join,
  BindMountSandboxHandle,
  afterEach,
  describe,
  expect,
  it,
  faultState,
  makeGrokSessionStorage,
  grokSessionAtomicReplaceTestInject,
  tempDirs,
  tmp,
  oldBackupNames,
  localHandleWithStdin,
  seedSandboxSession,
  seedHostSession,
} from "./grok-session-atomic-959.shared.js";

vi.mock("../../src/externalCall.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/externalCall.js")>();
  return {
    ...actual,
    execFileAsyncWithTimeout: async (
      file: string,
      args: readonly string[],
      opts: Parameters<typeof actual.execFileAsyncWithTimeout>[2],
    ) => {
      const result = await actual.execFileAsyncWithTimeout(file, args, opts);
      if (faultState.failAfterHostExtract && opts.stage === "grok-session:tar-extract") {
        throw new Error("injected mid-transfer failure after extract");
      }
      return result;
    },
  };
});
afterEach(() => {
  faultState.failAfterHostExtract = false;
  grokSessionAtomicReplaceTestInject.reset();
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

describe("#959 captureToHost atomic temp+swap", () => {

  it("failed first capture does not leave a half-written host session dir", async () => {
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const hostCwd = "/host/work-959-nofirst";
    const sessionId = "019f-959-nofirst";

    const handle: BindMountSandboxHandle = {
      worktreePath: sandboxFs,
      exec: async () => ({
        stdout: Buffer.from("not-a-tar").toString("base64"),
        stderr: "",
        exitCode: 0,
      }),
      copyFileIn: async () => {},
      copyFileOut: async () => {},
      close: async () => {},
    };

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: join(sandboxFs, "sessions"),
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd: "/sbx",
        sessionId,
        handle,
      }),
    ).rejects.toThrow();

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(existsSync(hostDir)).toBe(false);
    expect(await storage.existsOnHost(hostCwd, sessionId)).toBe(false);
  });

});
