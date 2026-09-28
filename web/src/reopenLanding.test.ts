import { describe, expect, it } from "vitest";

import { opensAudienceOnResume, type ReopenLanding } from "./reopenLanding";

describe("#1855 reopen landing（前端只认后端枚举）", () => {
  it.each([
    ["audience", true],
    ["settlement", false],
    ["month", false],
    [undefined, false],
    ["", false],
    ["open_night", false],
  ] as const)("%s → opensAudience=%s", (landing, expected) => {
    expect(opensAudienceOnResume(landing as ReopenLanding | undefined)).toBe(expected);
  });
});
