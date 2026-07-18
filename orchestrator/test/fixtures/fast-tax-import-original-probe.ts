import { execFileSync } from "node:child_process";

import { it, vi } from "vitest";

vi.mock("node:child_process", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:child_process")>()),
}));

it("pays process tax through importOriginal", () => {
  execFileSync(process.execPath, ["-v"]);
});
