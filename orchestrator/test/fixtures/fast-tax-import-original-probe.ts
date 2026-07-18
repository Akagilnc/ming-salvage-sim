import { execFileSync } from "node:child_process";

import { expect, it, vi } from "vitest";

vi.mock("node:child_process", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:child_process")>()),
}));

it("pays process tax through importOriginal", () => {
  expect(process.env.NODE_OPTIONS).toContain("--trace-warnings");
  execFileSync(process.execPath, ["-v"]);
});
