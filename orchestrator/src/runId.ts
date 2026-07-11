/** A distinct telemetry identity for one top-level runner invocation. */
export function mintRunId(): string {
  return `${new Date().toISOString()}-${globalThis.crypto.randomUUID()}`;
}
