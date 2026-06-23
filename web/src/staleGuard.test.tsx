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
