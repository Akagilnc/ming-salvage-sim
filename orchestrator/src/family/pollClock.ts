/**
 * Shared poll/sleep clocks for Landing CI wait (#1145 B3).
 * Not Online Review host polling — that dual-owner path is deleted.
 */

import { BOT_POLL_INTERVAL_MS } from "../botPolling.js";

export interface BotPollClock {
  sleep(ms: number): void | Promise<void>;
}

export const realBotPollClock: BotPollClock = {
  sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  },
};

export const immediateBotPollClock: BotPollClock = {
  sleep() {},
};

/**
 * Family pending-CI re-poll delay.
 * Under Vitest use the immediate clock so unit tests do not wall-clock sleep.
 * Production uses real 2-minute cadence between pending-CI polls (#934 ID-004).
 */
export async function sleepPendingCiPollInterval(
  clock?: BotPollClock,
): Promise<void> {
  const resolved =
    clock ??
    (process.env.VITEST !== undefined ? immediateBotPollClock : realBotPollClock);
  await resolved.sleep(BOT_POLL_INTERVAL_MS);
}
