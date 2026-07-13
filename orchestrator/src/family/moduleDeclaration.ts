/**
 * Module declaration parsing + family module context assembly.
 *
 * These are the general-purpose utilities that survive the deletion of the
 * runner-side finding classification apparatus (#604 / ADR 0062). The runner no
 * longer routes by finding content, but it still needs to parse a family/child
 * issue's `## Module Declaration` and assemble the module context that other
 * layers consume. Keeping parsing separate lets those consumers share the
 * context without reviving a runner-side classification apparatus.
 */

export interface ModuleDeclaration {
  readonly module: string;
  readonly moduleScope: ReadonlyArray<string>;
}

export interface SourcedModuleDeclaration extends ModuleDeclaration {
  readonly source: "child_issue" | "family_issue" | "run_option";
  readonly issue?: number;
}

export interface FamilyModuleContext {
  readonly currentModules: ReadonlyArray<SourcedModuleDeclaration>;
  readonly childModules: ReadonlyArray<SourcedModuleDeclaration>;
  readonly fallbackModule?: SourcedModuleDeclaration;
  readonly undevelopedModules?: ReadonlyArray<SourcedModuleDeclaration>;
  readonly acceptedSuppressionSources?: ReadonlyArray<AcceptedSuppressionSource>;
}

export interface AcceptedSuppressionSource {
  readonly source: string;
  readonly scope: string;
  readonly reason: string;
  readonly findingIdentity: string;
  readonly boundedReopen: string;
}

export function sourcedModuleDeclaration(
  declaration: ModuleDeclaration | undefined,
  source: SourcedModuleDeclaration["source"],
  issue?: number,
): SourcedModuleDeclaration | undefined {
  if (declaration === undefined) return undefined;
  return {
    ...declaration,
    source,
    ...(issue !== undefined ? { issue } : {}),
  };
}

export function buildFamilyModuleContext(input: {
  readonly childModules: ReadonlyArray<SourcedModuleDeclaration | undefined>;
  readonly familyModule?: SourcedModuleDeclaration;
  readonly runOptionModule?: SourcedModuleDeclaration;
  readonly undevelopedModules?: ReadonlyArray<SourcedModuleDeclaration | undefined>;
  readonly acceptedSuppressionSources?: ReadonlyArray<AcceptedSuppressionSource>;
}): FamilyModuleContext {
  const childModules = input.childModules.filter(
    (decl): decl is SourcedModuleDeclaration => decl !== undefined,
  );
  const fallbackModule = input.familyModule ?? input.runOptionModule;
  const undevelopedModules = (input.undevelopedModules ?? []).filter(
    (decl): decl is SourcedModuleDeclaration => decl !== undefined,
  );
  const currentModules =
    childModules.length > 0
      ? [
          ...childModules,
          ...(fallbackModule !== undefined ? [fallbackModule] : []),
        ]
      : fallbackModule !== undefined
        ? [fallbackModule]
        : [];
  return {
    currentModules,
    childModules,
    ...(fallbackModule !== undefined ? { fallbackModule } : {}),
    ...(undevelopedModules.length > 0 ? { undevelopedModules } : {}),
    ...(input.acceptedSuppressionSources !== undefined &&
    input.acceptedSuppressionSources.length > 0
      ? { acceptedSuppressionSources: input.acceptedSuppressionSources }
      : {}),
  };
}

const MODULE_DECLARATION_HEADING = /^##\s+Module Declaration\s*$/gim;

function isEscapedQuote(line: string, index: number): boolean {
  let backslashes = 0;
  for (let idx = index - 1; idx >= 0; idx -= 1) {
    if (line[idx] !== "\\") break;
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

function trimComment(line: string): string {
  let inSingleQuote = false;
  let inDoubleQuote = false;
  for (let idx = 0; idx < line.length; idx += 1) {
    const char = line[idx]!;
    if (char === '"' && !inSingleQuote && !isEscapedQuote(line, idx)) {
      inDoubleQuote = !inDoubleQuote;
      continue;
    }
    if (char === "'" && !inDoubleQuote && !isEscapedQuote(line, idx)) {
      inSingleQuote = !inSingleQuote;
      continue;
    }
    if (
      char === "#" &&
      !inSingleQuote &&
      !inDoubleQuote &&
      (idx === 0 || /\s/.test(line[idx - 1]!))
    ) {
      return line.slice(0, idx).trimEnd();
    }
  }
  return line.trimEnd();
}

function unquoteScalar(value: string): string | undefined {
  const trimmed = value.trim();
  if (trimmed.length === 0) return undefined;
  if (
    trimmed.length >= 2 &&
    ((trimmed.startsWith('"') && trimmed.endsWith('"')) ||
      (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  if (trimmed.includes("{") || trimmed.includes("}") || trimmed.includes("[")) {
    return undefined;
  }
  return trimmed;
}

function parseModuleDeclarationYaml(yaml: string): ModuleDeclaration | undefined {
  let moduleName: string | undefined;
  const moduleScope: string[] = [];
  let inScope = false;

  for (const rawLine of yaml.split(/\r?\n/)) {
    const line = trimComment(rawLine);
    if (line.trim().length === 0) continue;

    const topLevel = /^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$/.exec(line);
    if (topLevel !== null && !/^\s/.test(line)) {
      const [, key, rawValue] = topLevel;
      if (key !== "module" && key !== "module_scope") return undefined;
      if (key === "module") {
        if (moduleName !== undefined) return undefined;
        moduleName = unquoteScalar(rawValue ?? "");
        if (moduleName === undefined || moduleName.length === 0) return undefined;
        inScope = false;
        continue;
      }
      if ((rawValue ?? "").trim().length > 0) return undefined;
      inScope = true;
      continue;
    }

    if (!inScope) return undefined;
    const item = /^\s*-\s+(.+?)\s*$/.exec(line);
    if (item === null) return undefined;
    const scope = unquoteScalar(item[1] ?? "");
    if (scope === undefined || scope.length === 0) return undefined;
    moduleScope.push(scope);
  }

  if (moduleName === undefined || moduleScope.length === 0) return undefined;
  return { module: moduleName, moduleScope };
}

/**
 * Parse a family/child issue's structured module declaration.
 *
 * The contract intentionally ignores titles, prose, temporary logs, and any YAML
 * outside the exact `## Module Declaration` section.
 */
export function parseModuleDeclaration(body: string): ModuleDeclaration | undefined {
  const headings = [...body.matchAll(MODULE_DECLARATION_HEADING)];
  if (headings.length !== 1) return undefined;
  const heading = headings[0];
  if (heading.index === undefined) return undefined;
  const afterHeading = body.slice(heading.index + heading[0].length);
  const fence = /```(?:ya?ml)\s*\n([\s\S]*?)\n```\s*/i.exec(afterHeading);
  if (fence === null) return undefined;
  const beforeFence = afterHeading.slice(0, fence.index);
  if (/(^|\r?\n)#{1,6}\s+\S/.test(beforeFence)) return undefined;
  return parseModuleDeclarationYaml(fence[1] ?? "");
}
