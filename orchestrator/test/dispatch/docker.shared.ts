import { spawnSync } from "node:child_process";

type DockerAvailability =
  | { available: true }
  | { available: false; reason: string };

function probeDocker(): DockerAvailability {
  const probe = spawnSync("docker", ["info"], {
    encoding: "utf8",
    timeout: 15_000,
  });
  if ((probe.error as NodeJS.ErrnoException | undefined)?.code === "ENOENT") {
    return { available: false, reason: "docker CLI is not on PATH" };
  }
  if (probe.status === 0) return { available: true };

  const detail = `${probe.stderr ?? ""}${probe.stdout ?? ""}`
    .trim()
    .split("\n")
    .find((line) => line.trim().length > 0);
  return {
    available: false,
    reason: detail
      ? `docker daemon is unavailable: ${detail.trim()}`
      : "docker daemon is unavailable",
  };
}

/** Shared, one-shot host Docker probe for container-backed live tests. */
const dockerAvailability = probeDocker();

export function dockerAvailable(): boolean {
  return dockerAvailability.available;
}

export function dockerUnavailableReason(): string | null {
  return dockerAvailability.available ? null : dockerAvailability.reason;
}
