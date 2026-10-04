#!/usr/bin/env node
/** #1902 D5：基线 0ca77fecc→HEAD Web 测试删改机械枚举。 */
const fs = require("fs");
const path = require("path");
const cp = require("child_process");
const root = path.resolve(__dirname, "../..");
const ts = require(path.join(root, "web/node_modules/typescript"));
const BASE = "0ca77fecc";
const outDir = __dirname;

function git(args) {
  return cp.execFileSync("git", args, { cwd: root, encoding: "utf8" });
}

const files = git(["diff", "--name-only", BASE, "--", "web"])
  .trim()
  .split("\n")
  .filter((f) => /\.(test|spec)\.[cm]?[jt]sx?$/.test(f));

function tests(file, source) {
  const kind = file.endsWith("tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, kind);
  const out = [];
  function visit(n) {
    if (
      ts.isCallExpression(n) &&
      /^(?:it|test)(?:\.(?:skip|only|each|todo))*$/.test(n.expression.getText(sf))
    ) {
      const body = n.arguments.find(
        (a) => ts.isArrowFunction(a) || ts.isFunctionExpression(a),
      );
      if (body) {
        const assertions = [];
        function scan(x) {
          if (ts.isExpressionStatement(x) && x.getText(sf).includes("expect(")) {
            assertions.push(x.getText(sf));
          } else {
            ts.forEachChild(x, scan);
          }
        }
        scan(body.body);
        out.push({
          name: n.arguments[0]?.getText(sf),
          line: sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1,
          assertions,
        });
      }
    }
    ts.forEachChild(n, visit);
  }
  visit(sf);
  return out;
}

const rows = [];
for (const file of files) {
  let before;
  try {
    before = git(["show", `${BASE}:${file}`]);
  } catch {
    continue;
  }
  const full = path.join(root, file);
  const old = tests(file, before);
  const now = tests(file, fs.existsSync(full) ? fs.readFileSync(full, "utf8") : "");
  for (const x of old) {
    const y = now.find((t) => t.name === x.name);
    const removed = x.assertions.filter((a) => !(y?.assertions || []).includes(a));
    if (!y || removed.length) {
      rows.push({
        member: `${file}::${x.name}`,
        kind: y ? "assertions_changed" : "test_deleted",
        removedAssertions: removed,
        currentAssertions: y?.assertions || [],
      });
    }
  }
  for (const y of now) {
    if (!old.find((t) => t.name === y.name)) {
      rows.push({
        member: `${file}::${y.name}`,
        kind: "test_added",
        removedAssertions: [],
        currentAssertions: y.assertions,
      });
    }
  }
}

const out = path.join(outDir, "d5-web-members.json");
fs.writeFileSync(out, JSON.stringify(rows, null, 2) + "\n");
console.log("D5 Web members", rows.length);
for (const r of rows) console.log(r.member, r.kind);
