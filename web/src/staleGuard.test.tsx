import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return host;
}

afterEach(() => {
  document.body.innerHTML = "";
});

/**
 * Fixture mirroring the ref-based stale guard in main.tsx sendChat.
 * Has the same shape: selectedMinisterRef synced via useEffect,
 * captured target before the await, guard after.
 * Without the guard block, the first test fails (notice gets set for 乙's panel).
 */
function StaleGuardFixture({
  getResponse,
}: {
  getResponse: () => Promise<string>;
}) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  const [notice, setNotice] = React.useState("");

  const send = async (targetMinister: string) => {
    const target = targetMinister;
    const reply = await getResponse();
    // staleness guard — mirrors main.tsx selectedMinisterRef check
    if (selectedRef.current !== target) return;
    setNotice(`${target}：${reply}`);
  };

  return (
    <div>
      <div data-testid="notice">{notice}</div>
      <button data-testid="send" onClick={() => send(selected)}>
        发送
      </button>
      <button data-testid="switch" onClick={() => setSelected("乙")}>
        切换至乙
      </button>
    </div>
  );
}

describe("召对陈旧守卫（staleness guard）", () => {
  it("切到乙之后甲的迟到响应不写入 notice", async () => {
    let resolve!: (v: string) => void;
    const pending = new Promise<string>((r) => {
      resolve = r;
    });

    const host = render(<StaleGuardFixture getResponse={() => pending} />);

    // send for 甲 while selected = 甲
    act(() => {
      (host.querySelector("[data-testid=send]") as HTMLButtonElement).click();
    });

    // switch to 乙 before response arrives
    act(() => {
      (host.querySelector("[data-testid=switch]") as HTMLButtonElement).click();
    });

    // 甲's response arrives after switch
    await act(async () => {
      resolve("甲的回话");
      await pending;
    });

    expect(host.querySelector("[data-testid=notice]")?.textContent).toBe("");
  });

  it("未切人时响应正常应用不被守卫误丢", async () => {
    let resolve!: (v: string) => void;
    const pending = new Promise<string>((r) => {
      resolve = r;
    });

    const host = render(<StaleGuardFixture getResponse={() => pending} />);

    // send for 甲, no switch
    act(() => {
      (host.querySelector("[data-testid=send]") as HTMLButtonElement).click();
    });

    await act(async () => {
      resolve("甲的回话");
      await pending;
    });

    expect(host.querySelector("[data-testid=notice]")?.textContent).toBe("甲：甲的回话");
  });
});

/** Mirrors sendChat success path after streamChat returns: global state refresh
 * may await, so minister-panel writes after that await need a second stale guard. */
function SendPostLoadGuardFixture({
  getResponse,
  loadState,
}: {
  getResponse: () => Promise<{ failures: string }>;
  loadState: () => Promise<void>;
}) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const [globalApplied, setGlobalApplied] = React.useState(0);
  const [failures, setFailures] = React.useState("");
  const send = async (targetMinister: string) => {
    const result = await getResponse();
    if (selectedRef.current !== targetMinister) return;
    setGlobalApplied((n) => n + 1);
    await loadState();
    if (selectedRef.current !== targetMinister) return;
    setFailures(result.failures);
  };
  return (
    <div>
      <div data-testid="global">{globalApplied}</div>
      <div data-testid="failures">{failures}</div>
      <button data-testid="send" onClick={() => send(selected)}>
        发送
      </button>
      <button data-testid="switch" onClick={() => setSelected("乙")}>
        切换至乙
      </button>
    </div>
  );
}

describe("召对陈旧守卫 — sendChat 成功后全局刷新窗口", () => {
  it("loadState 等待期间切人后，失败列表不写入新大臣面板", async () => {
    let resolveResponse!: (v: { failures: string }) => void;
    let resolveLoad!: () => void;
    const response = new Promise<{ failures: string }>((r) => (resolveResponse = r));
    const loading = new Promise<void>((r) => (resolveLoad = r));
    const host = render(
      <SendPostLoadGuardFixture getResponse={() => response} loadState={() => loading} />
    );
    act(() => (host.querySelector("[data-testid=send]") as HTMLButtonElement).click());
    await act(async () => {
      resolveResponse({ failures: "甲的失败密令" });
      await response;
    });
    act(() => (host.querySelector("[data-testid=switch]") as HTMLButtonElement).click());
    await act(async () => {
      resolveLoad();
      await loading;
    });
    expect(host.querySelector("[data-testid=global]")?.textContent).toBe("1");
    expect(host.querySelector("[data-testid=failures]")?.textContent).toBe("");
  });
});

/**
 * Broad-scope (#325, dogfood self-check): the bleed has THREE async→minister-panel
 * write paths, not just sendChat. These fixtures mirror the other two guards.
 */

/** Mirrors loadMinisterChat: a history load that writes the panel after an await. */
function LoadGuardFixture({ getHistory }: { getHistory: () => Promise<string> }) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const [panel, setPanel] = React.useState("");
  const load = async (targetMinister: string) => {
    const history = await getHistory();
    // loadMinisterChat writes ONLY panel state → blanket early-return.
    if (selectedRef.current !== targetMinister) return;
    setPanel(`${targetMinister}：${history}`);
  };
  return (
    <div>
      <div data-testid="panel">{panel}</div>
      <button data-testid="load" onClick={() => load(selected)}>
        加载历史
      </button>
      <button data-testid="switch" onClick={() => setSelected("乙")}>
        切换至乙
      </button>
    </div>
  );
}

/** Mirrors undoLastChat: GLOBAL effect always applies, PANEL write is guarded. */
function UndoGuardFixture({
  getResult,
}: {
  getResult: () => Promise<{ notice: string; failures?: string[] }>;
}) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const [globalApplied, setGlobalApplied] = React.useState(0);
  const [panel, setPanel] = React.useState("");
  const [failures, setFailures] = React.useState(["旧失败"]);
  const undo = async (targetMinister: string) => {
    const result = await getResult();
    setGlobalApplied((n) => n + 1); // global undo effect — always applies
    if (selectedRef.current === targetMinister) {
      setPanel(`${targetMinister}：${result.notice}`);
      setFailures(result.failures || []);
    }
  };
  return (
    <div>
      <div data-testid="global">{globalApplied}</div>
      <div data-testid="panel">{panel}</div>
      <div data-testid="failures">{failures.join("|")}</div>
      <button data-testid="undo" onClick={() => undo(selected)}>
        撤回
      </button>
      <button data-testid="switch" onClick={() => setSelected("乙")}>
        切换至乙
      </button>
    </div>
  );
}

describe("召对陈旧守卫 — 广范围（loadMinisterChat 历史加载）", () => {
  it("切人后甲的迟到历史不写入乙面板（不发消息也复现）", async () => {
    let resolve!: (v: string) => void;
    const pending = new Promise<string>((r) => (resolve = r));
    const host = render(<LoadGuardFixture getHistory={() => pending} />);
    act(() => (host.querySelector("[data-testid=load]") as HTMLButtonElement).click());
    act(() => (host.querySelector("[data-testid=switch]") as HTMLButtonElement).click());
    await act(async () => {
      resolve("甲的历史");
      await pending;
    });
    expect(host.querySelector("[data-testid=panel]")?.textContent).toBe("");
  });

  it("未切人时历史正常加载不被误丢", async () => {
    let resolve!: (v: string) => void;
    const pending = new Promise<string>((r) => (resolve = r));
    const host = render(<LoadGuardFixture getHistory={() => pending} />);
    act(() => (host.querySelector("[data-testid=load]") as HTMLButtonElement).click());
    await act(async () => {
      resolve("甲的历史");
      await pending;
    });
    expect(host.querySelector("[data-testid=panel]")?.textContent).toBe("甲：甲的历史");
  });
});

/**
 * The FOURTH async→minister-panel write path the #325 sweep missed: sendChat's
 * catch block (error / AbortError observer-departure). Mirrors main.tsx — on
 * observer departure/error it writes a panel notice; without the staleness guard
 * that lands on whichever minister is now selected (cross-minister bleed when
 * the player switches mid-flight then leaves the old stream). Guard =
 * early-return when stale; finally still clears busy/abortRef globally
 * (modelled here by `cleared`).
 */
function CatchGuardFixture({ getResponse }: { getResponse: () => Promise<string> }) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const [input, setInput] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [cleared, setCleared] = React.useState(0);
  const send = async (targetMinister: string, message: string) => {
    try {
      await getResponse(); // rejects (cancel/error)
    } catch {
      if (selectedRef.current !== targetMinister) return; // staleness guard
      setInput("");
      setNotice(`${targetMinister}：已离开实时回话`);
    } finally {
      setCleared((n) => n + 1); // global cleanup always runs (busy/abortRef)
    }
  };
  return (
    <div>
      <div data-testid="input">{input}</div>
      <div data-testid="notice">{notice}</div>
      <div data-testid="cleared">{cleared}</div>
      <button data-testid="send" onClick={() => send(selected, "甲的问话")}>
        发送
      </button>
      <button data-testid="switch" onClick={() => setSelected("乙")}>
        切换至乙
      </button>
    </div>
  );
}

describe("召对陈旧守卫 — 离开实时观察/错误分支（sendChat catch）", () => {
  it("切到乙后甲的实时观察离开，提示不写入乙面板，但全局清理照常", async () => {
    let reject!: (e: unknown) => void;
    const pending = new Promise<string>((_r, rej) => (reject = rej));
    const host = render(<CatchGuardFixture getResponse={() => pending} />);
    act(() => (host.querySelector("[data-testid=send]") as HTMLButtonElement).click());
    act(() => (host.querySelector("[data-testid=switch]") as HTMLButtonElement).click());
    await act(async () => {
      const abortErr = new Error("aborted");
      abortErr.name = "AbortError";
      reject(abortErr);
      await pending.catch(() => {});
    });
    expect(host.querySelector("[data-testid=input]")?.textContent).toBe("");
    expect(host.querySelector("[data-testid=notice]")?.textContent).toBe("");
    // finally still ran (busy/abortRef cleared) even though the panel writes were dropped
    expect(host.querySelector("[data-testid=cleared]")?.textContent).toBe("1");
  });

  it("未切人时离开实时观察正常提示但不恢复已发问话", async () => {
    let reject!: (e: unknown) => void;
    const pending = new Promise<string>((_r, rej) => (reject = rej));
    const host = render(<CatchGuardFixture getResponse={() => pending} />);
    act(() => (host.querySelector("[data-testid=send]") as HTMLButtonElement).click());
    await act(async () => {
      const abortErr = new Error("aborted");
      abortErr.name = "AbortError";
      reject(abortErr);
      await pending.catch(() => {});
    });
    expect(host.querySelector("[data-testid=input]")?.textContent).toBe("");
    expect(host.querySelector("[data-testid=notice]")?.textContent).toBe("甲：已离开实时回话");
    expect(host.querySelector("[data-testid=cleared]")?.textContent).toBe("1");
  });
});

function DecisionsFailureFixture({
  outcome,
}: {
  outcome: {
    decisions: Array<{ title: string }>;
    pending_action_failures?: string[];
  };
}) {
  const [failures, setFailures] = React.useState<string[]>([]);
  const [decisions, setDecisions] = React.useState<Array<{ title: string }>>([]);
  const [busy, setBusy] = React.useState("月末结算");
  const issue = async () => {
    setFailures(outcome.pending_action_failures || []);
    setDecisions(outcome.decisions || []);
    setBusy("");
  };
  return (
    <div>
      <div data-testid="failures">{failures.join("|")}</div>
      <div data-testid="decisions">{decisions.map((d) => d.title).join("|")}</div>
      <div data-testid="busy">{busy}</div>
      <button data-testid="issue" onClick={issue}>
        颁诏
      </button>
    </div>
  );
}

describe("结算决策暂停 — 密令失败提示", () => {
  it("decisions 响应同时保留 pending action failures 和待裁决策", async () => {
    const host = render(
      <DecisionsFailureFixture
        outcome={{
          decisions: [{ title: "辽东战守" }],
          pending_action_failures: ["密令未能正式落库"],
        }}
      />,
    );

    await act(async () => {
      (host.querySelector("[data-testid=issue]") as HTMLButtonElement).click();
    });

    expect(host.querySelector("[data-testid=failures]")?.textContent).toBe("密令未能正式落库");
    expect(host.querySelector("[data-testid=decisions]")?.textContent).toBe("辽东战守");
    expect(host.querySelector("[data-testid=busy]")?.textContent).toBe("");
  });
});

function SurfaceFailuresFixture({ loadState }: { loadState: () => Promise<void> }) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  const [activeModal, setActiveModal] = React.useState("none");
  const [busy, setBusy] = React.useState("月末结算");
  const [recovery, setRecovery] = React.useState(false);
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const surface = async () => {
    const targetName = "";
    setRecovery(true);
    const initialMinister = selectedRef.current;
    try {
      await loadState();
      if (selectedRef.current !== initialMinister) return;
      selectedRef.current = targetName;
      setSelected(targetName);
      setActiveModal("chat");
    } finally {
      setBusy("");
    }
  };
  return (
    <div>
      <div data-testid="selected">{selected}</div>
      <div data-testid="active">{activeModal}</div>
      <div data-testid="busy">{busy}</div>
      <div data-testid="recovery">{String(recovery)}</div>
      <button data-testid="surface" onClick={surface}>失败</button>
    </div>
  );
}

describe("未落库政务告知 — 无承办人", () => {
  it("没有 minister_name 的失败也会打开全局失败告知面板", async () => {
    const host = render(<SurfaceFailuresFixture loadState={() => Promise.resolve()} />);

    await act(async () => {
      (host.querySelector("[data-testid=surface]") as HTMLButtonElement).click();
    });

    expect(host.querySelector("[data-testid=selected]")?.textContent).toBe("");
    expect(host.querySelector("[data-testid=active]")?.textContent).toBe("chat");
    expect(host.querySelector("[data-testid=busy]")?.textContent).toBe("");
    expect(host.querySelector("[data-testid=recovery]")?.textContent).toBe("true");
  });
});

describe("召对陈旧守卫 — 广范围（undoLastChat 全局生效、面板守卫）", () => {
  it("切人后撤回的全局效果照样生效，但旧面板写被守卫丢弃", async () => {
    let resolve!: (v: { notice: string; failures?: string[] }) => void;
    const pending = new Promise<{ notice: string; failures?: string[] }>((r) => (resolve = r));
    const host = render(<UndoGuardFixture getResult={() => pending} />);
    act(() => (host.querySelector("[data-testid=undo]") as HTMLButtonElement).click());
    act(() => (host.querySelector("[data-testid=switch]") as HTMLButtonElement).click());
    await act(async () => {
      resolve({ notice: "已撤回", failures: ["旧失败"] });
      await pending;
    });
    // global undo effect applied (state mutated) ...
    expect(host.querySelector("[data-testid=global]")?.textContent).toBe("1");
    // ... but the stale panel write was dropped (no bleed into 乙).
    expect(host.querySelector("[data-testid=panel]")?.textContent).toBe("");
  });

  it("未切人时撤回的全局效果与面板写都生效", async () => {
    let resolve!: (v: { notice: string; failures?: string[] }) => void;
    const pending = new Promise<{ notice: string; failures?: string[] }>((r) => (resolve = r));
    const host = render(<UndoGuardFixture getResult={() => pending} />);
    act(() => (host.querySelector("[data-testid=undo]") as HTMLButtonElement).click());
    await act(async () => {
      resolve({ notice: "已撤回", failures: ["旧失败"] });
      await pending;
    });
    expect(host.querySelector("[data-testid=global]")?.textContent).toBe("1");
    expect(host.querySelector("[data-testid=panel]")?.textContent).toBe("甲：已撤回");
  });

  it("撤回响应必须刷新失败列表，不能隐藏仍未落库的旧密令失败", async () => {
    let resolve!: (v: { notice: string; failures?: string[] }) => void;
    const pending = new Promise<{ notice: string; failures?: string[] }>((r) => (resolve = r));
    const host = render(<UndoGuardFixture getResult={() => pending} />);
    expect(host.querySelector("[data-testid=failures]")?.textContent).toBe("旧失败");
    act(() => (host.querySelector("[data-testid=undo]") as HTMLButtonElement).click());
    await act(async () => {
      resolve({ notice: "已撤回", failures: ["旧失败"] });
      await pending;
    });
    expect(host.querySelector("[data-testid=failures]")?.textContent).toBe("旧失败");
  });
});
