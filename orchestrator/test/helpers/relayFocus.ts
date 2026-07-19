import { existsSync } from "node:fs";
import { join } from "node:path";
import { expect } from "vitest";

export const RELAY_FOCUS_FILENAME = ".relay-focus.md";

/** Assert the retired relay-focus file was not produced in a worktree. */
export function expectNoRelayFocusFile(worktreePath: string): void {
  expect(existsSync(join(worktreePath, RELAY_FOCUS_FILENAME))).toBe(false);
}
