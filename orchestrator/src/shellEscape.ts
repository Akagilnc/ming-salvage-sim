/**
 * Shell-escape a single argv token for inclusion in a `sandbox.exec` command string.
 * Shared by agy/grok (and any other CLI that builds a shell command line).
 */
export function shellEscape(value: string): string {
  if (value.length === 0) return "''";
  if (/^[A-Za-z0-9_./:@%+=,-]+$/.test(value)) return value;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}
