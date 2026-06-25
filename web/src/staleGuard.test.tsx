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
function UndoGuardFixture({ getResult }: { getResult: () => Promise<string> }) {
  const [selected, setSelected] = React.useState("甲");
  const selectedRef = React.useRef("甲");
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const [globalApplied, setGlobalApplied] = React.useState(0);
  const [panel, setPanel] = React.useState("");
  const undo = async (targetMinister: string) => {
    const result = await getResult();
    setGlobalApplied((n) => n + 1); // global undo effect — always applies
    if (selectedRef.current === targetMinister) {
      setPanel(`${targetMinister}：${result}`);
    }
  };
  return (
    <div>
      <div data-testid="global">{globalApplied}</div>
      <div data-testid="panel">{panel}</div>
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
 * catch block (error / AbortError-cancel). Mirrors main.tsx — on cancel/error it
 * restores input + writes a panel notice; without the staleness guard those land
 * on whichever minister is now selected (cross-minister bleed when the player
 * switches mid-flight then cancels). Guard = early-return when stale; finally still
 * clears busy/abortRef globally (modelled here by `cleared`).
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
      setInput(message); // restore input for retry
      setNotice(`${targetMinister}：已取消`);
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

describe("召对陈旧守卫 — 取消/错误分支（sendChat catch）", () => {
  it("切到乙后甲被取消，输入与取消提示不写入乙面板，但全局清理照常", async () => {
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

  it("未切人时取消正常恢复输入与提示", async () => {
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
    expect(host.querySelector("[data-testid=input]")?.textContent).toBe("甲的问话");
    expect(host.querySelector("[data-testid=notice]")?.textContent).toBe("甲：已取消");
    expect(host.querySelector("[data-testid=cleared]")?.textContent).toBe("1");
  });
});

describe("召对陈旧守卫 — 广范围（undoLastChat 全局生效、面板守卫）", () => {
  it("切人后撤回的全局效果照样生效，但旧面板写被守卫丢弃", async () => {
    let resolve!: (v: string) => void;
    const pending = new Promise<string>((r) => (resolve = r));
    const host = render(<UndoGuardFixture getResult={() => pending} />);
    act(() => (host.querySelector("[data-testid=undo]") as HTMLButtonElement).click());
    act(() => (host.querySelector("[data-testid=switch]") as HTMLButtonElement).click());
    await act(async () => {
      resolve("已撤回");
      await pending;
    });
    // global undo effect applied (state mutated) ...
    expect(host.querySelector("[data-testid=global]")?.textContent).toBe("1");
    // ... but the stale panel write was dropped (no bleed into 乙).
    expect(host.querySelector("[data-testid=panel]")?.textContent).toBe("");
  });

  it("未切人时撤回的全局效果与面板写都生效", async () => {
    let resolve!: (v: string) => void;
    const pending = new Promise<string>((r) => (resolve = r));
    const host = render(<UndoGuardFixture getResult={() => pending} />);
    act(() => (host.querySelector("[data-testid=undo]") as HTMLButtonElement).click());
    await act(async () => {
      resolve("已撤回");
      await pending;
    });
    expect(host.querySelector("[data-testid=global]")?.textContent).toBe("1");
    expect(host.querySelector("[data-testid=panel]")?.textContent).toBe("甲：已撤回");
  });
});
