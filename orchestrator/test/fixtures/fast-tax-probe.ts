import { spawnSync } from "node:child_process";

import { it } from "vitest";

it("pays process tax", () => spawnSync(process.execPath, ["-v"]));
