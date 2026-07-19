import {
  describe,
  it,
  expect,
  statSync,
  HOOK,
} from "./commit-message-hook.shared.js";

describe("commit-msg hook — sandcastle: prefix", () => {
  it("is committed as an executable script", () => {
    // The image RUN chmod relies on it being shipped executable; a non-exec hook
    // is a silent no-op in-container.
    expect(statSync(HOOK).mode & 0o111).toBeGreaterThan(0);
  });
});
