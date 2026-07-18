import { readFileSync } from "node:fs";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  classifyExternalCallFailure,
  ExternalCallTimeoutError,
  execFileAsyncWithTimeout,
  execFileWithTimeout,
  withProviderTimeout,
  DEFAULT_PROVIDER_TIMEOUT_MS,
  shWithClock,
} from "../../src/externalCall.js";

import {
  MAX_LEG_TRANSIENT_ATTEMPTS,
  withLegTransientRetry,
} from "../../src/legTransientRetry.js";

export {
  readFileSync,
  dirname,
  join,
  fileURLToPath,
  describe,
  expect,
  it,
  classifyExternalCallFailure,
  ExternalCallTimeoutError,
  execFileAsyncWithTimeout,
  execFileWithTimeout,
  withProviderTimeout,
  DEFAULT_PROVIDER_TIMEOUT_MS,
  shWithClock,
  MAX_LEG_TRANSIENT_ATTEMPTS,
  withLegTransientRetry,
};
