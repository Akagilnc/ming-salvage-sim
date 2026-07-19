import {
  resolveRouteModels,
  routeSmokeEntries,
  type ResolvedModelRoute,
} from "../src/modelRoutes.js";

function smokedRoute(): ResolvedModelRoute {
  const base = resolveRouteModels("normal", {});
  const smoke = Object.fromEntries(
    routeSmokeEntries(base).map((entry) => [
      entry.key,
      {
        state: "passed" as const,
        at: new Date().toISOString(),
        cliVersion: `cli-${entry.slug}`,
      },
    ]),
  );
  return resolveRouteModels("normal", {}, {}, smoke);
}

export { smokedRoute };
