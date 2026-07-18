/**
 * #1010 side-effect import — apply the local Sandcastle cancel patch before
 * any `import * as sc from "@ai-hero/sandcastle"` in the same module graph.
 *
 * Import this module as the **first** import in every file that loads
 * `@ai-hero/sandcastle` directly (RealBackend, RealFamilyBackend, tests that
 * call sc.run without going through those backends).
 *
 * Strategy (one line for the commit body): local patch of installed
 * `@ai-hero/sandcastle@0.12.0` cancel seam (abort/timeout → kill exec child);
 * no upstream bump (0.12.0 is latest).
 */
import { ensureSandcastleCancelPatch } from "./ensureSandcastleCancelPatch.js";

ensureSandcastleCancelPatch();
