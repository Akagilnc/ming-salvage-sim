# web_calls_without_ui_token (55)

## [106] web/src/components/decisionModal.test.tsx:92 `"DecisionModal" / "blocks background focus and shortcuts while the red-seal page is open"`
flags=['web_calls_without_ui_token'] lines=22
```
  it("blocks background focus and shortcuts while the red-seal page is open", () => {
    const background = document.createElement("button");
    background.textContent = "底层 HUD 控件";
    document.body.appendChild(background);
    const shortcut = vi.fn();
    window.addEventListener("keydown", shortcut);

    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const option = document.querySelector<HTMLButtonElement>(".decision-option");
    const event = new KeyboardEvent("keydown", { key: "`", ctrlKey: true, bubbles: true, cancelable: true });

    act(() => background.focus());
    expect(document.activeElement).toBe(option);

    act(() => document.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    expect(shortcut).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(option);

    window.removeEventListener("keydown", shortcut);
    cleanup();
  });
```

## [107] web/src/components/decisionModal.test.tsx:115 `"DecisionModal" / "leaves focus and Ctrl+` available to a cheat console opened before decisions arrive"`
flags=['web_calls_without_ui_token'] lines=25
```
  it("leaves focus and Ctrl+` available to a cheat console opened before decisions arrive", () => {
    const cheatConsole = document.createElement("div");
    cheatConsole.className = "cheat-console";
    const cheatInput = document.createElement("textarea");
    cheatConsole.appendChild(cheatInput);
    document.body.appendChild(cheatConsole);
    cheatInput.focus();

    const closeCheatConsole = vi.fn();
    const shortcut = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key === "`") closeCheatConsole();
    };
    window.addEventListener("keydown", shortcut);

    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    expect(document.activeElement).toBe(cheatInput);

    const event = new KeyboardEvent("keydown", { key: "`", ctrlKey: true, bubbles: true, cancelable: true });
    act(() => cheatInput.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
    expect(closeCheatConsole).toHaveBeenCalledOnce();

    window.removeEventListener("keydown", shortcut);
    cleanup();
  });
```

## [108] web/src/components/decisionModal.test.tsx:160 `"DecisionModal" / "requires a listed rescript action for dossier memorials"`
flags=['web_calls_without_ui_token'] lines=36
```
  it("requires a listed rescript action for dossier memorials", () => {
    const onResolve = vi.fn();
    const rejectionReasonMarker = "__opaque_rejection_reason_614__";
    const oppositionMarker = "__opaque_opposition_614__";
    const dossierDecision: PendingDecision = {
      ...decisions[0],
      event_id: "dossier:42",
      rejection_reason: rejectionReasonMarker,
      opposition: oppositionMarker,
      options: [{
        label: "强颁", hint: "以中旨颁行。",
        dossier_id: 42, dossier_decision: "force_promulgated",
      }],
    };
    const cleanup = render(<DecisionModal decisions={[dossierDecision]} onResolve={onResolve} />);
    const rejectionSection = Array.from(document.querySelectorAll(".decision-document-section")).find((section) => {
      const paragraphs = Array.from(section.querySelectorAll("p")).map((p) => p.textContent || "");
      return paragraphs.some((text) => text === rejectionReasonMarker)
        && paragraphs.some((text) => text.includes(oppositionMarker));
    });
    expect(rejectionSection).toBeTruthy();
    const note = document.querySelector<HTMLTextAreaElement>("textarea")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "朕意已决。");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelector<HTMLButtonElement>(".decision-confirm")!.disabled).toBe(true);
    act(() => document.querySelector<HTMLButtonElement>(".decision-option")!.click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledWith([{
      label: "强颁", hint: "以中旨颁行。",
      dossier_id: 42, dossier_decision: "force_promulgated",
      note: "朕意已决。",
    }]);
    cleanup();
  });
```

## [109] web/src/components/decisionModal.test.tsx:197 `"DecisionModal" / "keeps the handwritten reply in the existing resolve payload"`
flags=['web_calls_without_ui_token'] lines=13
```
  it("keeps the handwritten reply in the existing resolve payload", () => {
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    const note = document.querySelector<HTMLTextAreaElement>("textarea");
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理，不得有误。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledWith([{ note: "着即办理，不得有误。" }]);
    cleanup();
  });
```

## [110] web/src/components/decisionModal.test.tsx:211 `"DecisionModal" / "keeps the selected memorial's label and hint in the existing resolve payload"`
flags=['web_calls_without_ui_token'] lines=8
```
  it("keeps the selected memorial's label and hint in the existing resolve payload", () => {
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    act(() => document.querySelector<HTMLButtonElement>(".decision-option")!.click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledWith([{ label: "拨帑速发", hint: "先解燃眉之急。" }]);
    cleanup();
  });
```

## [111] web/src/components/decisionModal.test.tsx:262 `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "submits via the existing decision-confirm handler path with zero payload drift"`
flags=['web_calls_without_ui_token'] lines=21
```
  it("submits via the existing decision-confirm handler path with zero payload drift", () => {
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    act(() => document.querySelectorAll<HTMLButtonElement>(".decision-option")[0].click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledOnce();
    expect(onResolve).toHaveBeenCalledWith([{ label: "拨帑速发", hint: "先解燃眉之急。" }]);
    cleanup();

    const onResolveNote = vi.fn();
    const cleanupNote = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolveNote} />);
    const note = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理，不得有误。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolveNote).toHaveBeenCalledWith([{ note: "着即办理，不得有误。" }]);
    cleanupNote();
  });
```

## [112] web/src/components/decisionModal.test.tsx:285 `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "keeps the three-state invariant for listed picks without sealing the handwritten-only path"`
flags=['web_calls_without_ui_token'] lines=51
```
  it("keeps the three-state invariant for listed picks without sealing the handwritten-only path", () => {
    const cleanupListed = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const confirm = () => document.querySelector<HTMLButtonElement>(".decision-confirm")!;
    const options = () => document.querySelectorAll<HTMLButtonElement>(".decision-option");

    // 无择票拟 ⇔ 无选中样 ⇔ 确认不可用（须择票拟语义下）
    expect(options()[0].classList.contains("is-picked")).toBe(false);
    expect(options()[1].classList.contains("is-picked")).toBe(false);
    expect(confirm().disabled).toBe(true);

    act(() => options()[0].click());
    expect(options()[0].classList.contains("is-picked")).toBe(true);
    expect(confirm().disabled).toBe(false);

    cleanupListed();

    // 亲笔批示-only 路径（ADR 0043 留门）不得改死
    const onResolve = vi.fn();
    const cleanupNote = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    const note = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);
    expect(confirm().disabled).toBe(false);
    act(() => confirm().click());
    expect(onResolve).toHaveBeenCalledWith([{ note: "着即办理。" }]);
    cleanupNote();

    // dossier 路径仍须择票拟：仅亲笔不可确认
    const dossierDecision: PendingDecision = {
      ...decisions[0],
      event_id: "dossier:7",
      options: [{
        label: "强颁", hint: "以中旨颁行。",
        dossier_id: 7, dossier_decision: "force_promulgated",
      }],
    };
    const cleanupDossier = render(<DecisionModal decisions={[dossierDecision]} onResolve={vi.fn()} />);
    const dossierNote = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(dossierNote, "朕意已决。");
      (dossierNote as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      dossierNote.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(confirm().disabled).toBe(true);
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);
    cleanupDossier();
  });
```

## [113] web/src/components/decisionModal.test.tsx:337 `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "#657 同页两类 + 六动作可点 + 留中默认"`
flags=['web_calls_without_ui_token'] lines=82
```
  it("#657 同页两类 + 六动作可点 + 留中默认", () => {
    const mixed: PendingDecision[] = [
      {
        idx: 0,
        kind: "rescript_draft",
        decision_key: "rescript_draft:1:0",
        title: "陕西告饥",
        context: "秦地赤旱",
        actor_name: "杨嗣昌",
        options: [
          {
            label: "发帑赈济", hint: "所安者饥民",
            draft_capability: "cap1", action_type: "assignment",
            target_kind: "region", target_id: "shaanxi",
            locality_scope: "single", region_id: "shaanxi",
            transaction_category: "督赈",
          },
          { label: "缓征", hint: "h", draft_capability: "cap2" },
        ],
      },
      {
        idx: 1,
        kind: "decision",
        decision_key: "decision:1:1",
        title: "打回件",
        context: "科臣封驳",
        options: [
          { label: "准", hint: "" },
          { label: "驳", hint: "" },
        ],
      },
    ];
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={mixed} onResolve={onResolve} />);
    const confirmBtn = () => document.querySelector<HTMLButtonElement>(".decision-confirm")!;
    // 急务六钮
    const six = document.querySelector("[data-testid='rescript-six-actions']");
    expect(six).toBeTruthy();
    const actions = Array.from(document.querySelectorAll("[data-action]")).map(
      (el) => el.getAttribute("data-action"),
    );
    expect(actions).toEqual([
      "follow_draft", "return_revise", "midzhi", "deliberate", "hold", "summon",
    ]);
    // 显式留中可点并落印推进
    act(() => {
      (document.querySelector('[data-action="hold"]') as HTMLButtonElement).click();
    });
    expect(confirmBtn().disabled).toBe(false);
    act(() => confirmBtn().click());
    // 第二疏 decision
    expect(document.getElementById("decision-page-title")).toBeTruthy();
    act(() => {
      const opt = Array.from(document.querySelectorAll(".decision-option")).find(
        (b) => b.textContent?.includes("准"),
      ) as HTMLButtonElement;
      opt.click();
    });
    act(() => confirmBtn().click());
    expect(onResolve).toHaveBeenCalledTimes(1);
    const payload = onResolve.mock.calls[0][0];
    expect(payload[0].action).toBe("hold");
    expect(payload[0].decision_key).toBe("rescript_draft:1:0");
    expect(payload[1].label).toBe("准");
    expect(payload[1].decision_key).toBe("decision:1:1");
    cleanup();

    // V7：急务不点六钮 → 确认可点 → onResolve 该行无 action 且有 decision_key
    const onResolveDefault = vi.fn();
    const cleanupDefault = render(
      <DecisionModal decisions={[mixed[0]]} onResolve={onResolveDefault} />,
    );
    expect(document.querySelector<HTMLButtonElement>(".decision-confirm")!.disabled).toBe(false);
    act(() => {
      document.querySelector<HTMLButtonElement>(".decision-confirm")!.click();
    });
    expect(onResolveDefault).toHaveBeenCalledTimes(1);
    const defPayload = onResolveDefault.mock.calls[0][0][0];
    expect(defPayload.decision_key).toBe("rescript_draft:1:0");
    expect(defPayload.action).toBeUndefined();
... (2 more lines)
```

## [114] web/src/components/decisionModal.test.tsx:420 `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "#657 跨月 draft idx=2 首行可点，submit 携带 decision_key（禁 idx===position 拒收）"`
flags=['web_calls_without_ui_token'] lines=35
```
  it("#657 跨月 draft idx=2 首行可点，submit 携带 decision_key（禁 idx===position 拒收）", () => {
    const crossMonth: PendingDecision[] = [
      {
        idx: 2,
        kind: "rescript_draft",
        source_turn: 3,
        decision_key: "rescript_draft:3:2",
        title: "跨月急务",
        context: "上月遗留",
        options: [
          {
            label: "发帑", hint: "h",
            draft_capability: "cap-x", action_type: "assignment",
            target_kind: "region", target_id: "shaanxi",
            locality_scope: "single", region_id: "shaanxi",
            transaction_category: "督赈",
          },
          { label: "缓", hint: "h", draft_capability: "cap-y" },
        ],
      },
    ];
    expect(pendingDecisionsFrom(crossMonth)).toEqual(crossMonth);
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={crossMonth} onResolve={onResolve} />);
    act(() => {
      (document.querySelector('[data-action="hold"]') as HTMLButtonElement).click();
    });
    act(() => {
      document.querySelector<HTMLButtonElement>(".decision-confirm")!.click();
    });
    expect(onResolve).toHaveBeenCalledTimes(1);
    expect(onResolve.mock.calls[0][0][0].decision_key).toBe("rescript_draft:3:2");
    expect(onResolve.mock.calls[0][0][0].action).toBe("hold");
    cleanup();
  });
```

## [115] web/src/components/decisionModal.test.tsx:456 `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "#657 midzhi projects non-assignment §C.4 closed-set keys from selected option"`
flags=['web_calls_without_ui_token'] lines=63
```
  it("#657 midzhi projects non-assignment §C.4 closed-set keys from selected option", () => {
    const decisions = [
      {
        idx: 0,
        kind: "rescript_draft",
        decision_key: "rescript_draft:1:0",
        title: "中旨非 assignment",
        context: "c",
        actor_name: "杨嗣昌",
        options: [
          {
            label: "加衔恩赏",
            hint: "荣誉",
            draft_capability: "cap-grant",
            action_type: "grant_allocation",
            grant_action: "加衔",
            target_kind: "character",
            target_id: "杨嗣昌",
            name: "杨嗣昌",
            locality_scope: "none",
            office: "太子太保",
            // #1778：C.4 名单须随中旨投影进 choice
            participant_roster: [
              { character_id: "毕自严", tier: "主办", role: "总核", delegator_id: null },
            ],
          },
          { label: "备", hint: "h", draft_capability: "cap2" },
        ],
      },
    ];
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={decisions} onResolve={onResolve} />);
    // 先点选非 assignment option，再点中旨——投影须用选中项闭集键
    act(() => {
      const opt = Array.from(document.querySelectorAll(".decision-option")).find(
        (b) => b.textContent?.includes("加衔恩赏"),
      ) as HTMLButtonElement | undefined;
      opt?.click();
    });
    act(() => {
      (document.querySelector('[data-action="midzhi"]') as HTMLButtonElement).click();
    });
    act(() => {
      document.querySelector<HTMLButtonElement>(".decision-confirm")!.click();
    });
    expect(onResolve).toHaveBeenCalledTimes(1);
    const choice = onResolve.mock.calls[0][0][0];
    expect(choice.action).toBe("midzhi");
    // P7：decree_text 回退 label——必须保留所选 option 的 LLM 文案，禁结构钮文泄漏
    expect(choice.label).toBe("加衔恩赏");
    expect(choice.hint).toBe("荣誉");
    expect(choice.action_type).toBe("grant_allocation");
    expect(choice.grant_action).toBe("加衔");
    expect(choice.target_kind).toBe("character");
    expect(choice.target_id).toBe("杨嗣昌");
    expect(choice.name).toBe("杨嗣昌");
    expect(choice.office).toBe("太子太保");
    expect(choice.locality_scope).toBe("none");
    expect(choice.participant_roster).toEqual([
      { character_id: "毕自严", tier: "主办", role: "总核", delegator_id: null },
    ]);
    cleanup();
  });
```

## [116] web/src/components/drawers.test.tsx:636 `"朝堂同衔分座（#1196 呈现层去冲突）" / "同衔两张 minister-card 依次点击均委派 onOpenChat"`
flags=['web_calls_without_ui_token'] lines=24
```
  it("同衔两张 minister-card 依次点击均委派 onOpenChat", async () => {
    // 票面复现对：来宗道/温体仁同「礼部尚书」——每人一张卡，各自 click 须召对到本人
    const lai = minister({ name: "来宗道", office: "礼部尚书,东阁大学士" });
    const wen = minister({ name: "温体仁", office: "礼部尚书" });
    const onOpenChat = vi.fn();
    const host = await renderCourtList([lai, wen], onOpenChat);

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const laiCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "来宗道");
    const wenCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "温体仁");
    expect(laiCard).toBeTruthy();
    expect(wenCard).toBeTruthy();

    await act(async () => {
      laiCard!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      wenCard!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenChat).toHaveBeenCalledTimes(2);
    expect(onOpenChat.mock.calls[0][0]).toBe(lai);
    expect(onOpenChat.mock.calls[1][0]).toBe(wen);
  });
```

## [117] web/src/components/drawers.test.tsx:661 `"朝堂同衔分座（#1196 呈现层去冲突）" / "#1402 offstage 卡：网格与朝班同形——主体非 button、reason 位、起复委派 onOpenEdict"`
flags=['web_calls_without_ui_token'] lines=96
```
  it("#1402 offstage 卡：网格与朝班同形——主体非 button、reason 位、起复委派 onOpenEdict", async () => {
    const offstage = minister({
      name: "刘鸿训",
      office: "",
      status: "offstage",
      status_label: "罢居",
      status_reason: "因病乞休",
    });
    const onOpenChat = vi.fn();
    const onOpenEdict = vi.fn();
    const onUploadPortrait = vi.fn(async () => undefined);

    async function mount(
      courtMode: boolean,
      opts: { chatEntryEnabled?: boolean; withPortrait?: boolean } = {},
    ) {
      const { chatEntryEnabled = true, withPortrait = false } = opts;
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          if (String(url).includes("/api/court_layout")) {
            return { ok: true, json: async () => ({ layout: "{}" }) } as Response;
          }
          return { ok: true, json: async () => ({}) } as Response;
        }),
      );
      const host = document.createElement("div");
      document.body.appendChild(host);
      const root = createRoot(host);
      await act(async () => {
        root.render(
          <MinisterCardList
            list={[offstage]}
            portraitPrefix="minister_"
            selectedMinister=""
            emptyNote="empty"
            onOpenChat={onOpenChat}
            onOpenEdict={onOpenEdict}
            courtMode={courtMode}
            chatEntryEnabled={chatEntryEnabled}
            onUploadPortrait={withPortrait ? onUploadPortrait : undefined}
            phase={chatEntryEnabled ? undefined : "settling"}
          />,
        );
      });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      mountedRoots.push({ root, host });
      return host;
    }

    for (const courtMode of [false, true]) {
      onOpenChat.mockClear();
      onOpenEdict.mockClear();
      const host = await mount(courtMode);
      // 单卡夹具：唯一 .minister-card；结构辅 .minister-status-reason / resume btn
      const card = host.querySelector(".minister-card") as HTMLElement | null;
      expect(card).toBeTruthy();
      expect(card!.tagName).not.toBe("BUTTON");
      expect(card!.querySelector(".minister-status-reason")).not.toBeNull();

      await act(async () => {
        card!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      expect(onOpenChat).not.toHaveBeenCalled();

      const resume = card!.querySelector("button.minister-resume-btn") as HTMLButtonElement | null;
      expect(resume).not.toBeNull();
      expect(resume!.disabled).toBe(false);
      await act(async () => {
        resume!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      expect(onOpenEdict).toHaveBeenCalledTimes(1);
      expect(onOpenChat).not.toHaveBeenCalled();
    }

    // Class1：核账门控——resume 禁点且不调 onOpenEdict
    onOpenEdict.mockClear();
... (16 more lines)
```

## [118] web/src/components/drawers.test.tsx:837 `"#1732 T2 上传失败告警条挂载点" / "告警条不在 .minister-card 子树内（portal 出 transform 卡）"`
flags=['web_calls_without_ui_token'] lines=34
```
  it("告警条不在 .minister-card 子树内（portal 出 transform 卡）", async () => {
    const onUpload = vi.fn(async () => {
      throw new Error("网络中断");
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    // 模拟朝堂卡：transform 祖先会劫持 position:fixed 的 containing block
    await act(async () => {
      root.render(
        <div className="minister-card" style={{ transform: "scale(0.5)" }}>
          <PortraitUploadButton ministerName="周延儒" onUpload={onUpload} />
        </div>,
      );
    });
    mountedRoots.push({ root, host });

    const input = host.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    const file = new File(["x"], "x.png", { type: "image/png" });
    await act(async () => {
      Object.defineProperty(input, "files", { value: [file], configurable: true });
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onUpload).toHaveBeenCalled();
    const alert = document.body.querySelector(".inline-alert-bar");
    expect(alert).not.toBeNull();
    // 结构化：挂载点不在大臣卡子树（不锁文案）
    expect(alert!.closest(".minister-card")).toBeNull();
    expect(host.querySelector(".minister-card .inline-alert-bar")).toBeNull();
  });
```

## [119] web/src/components/gameMenu.test.tsx:733 `"#1732 GameMenu · 就地消解" / "回到主菜单：面板直通，不调 window.confirm"`
flags=['web_calls_without_ui_token'] lines=15
```
  it("回到主菜单：面板直通，不调 window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const onExit = vi.fn(async () => {});
    const { cleanup } = render(<ExitToMenuTab onExit={onExit} />);
    const btn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("回到主菜单")
    );
    expect(btn).toBeTruthy();
    await act(async () => {
      btn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(confirm).not.toHaveBeenCalled();
    expect(onExit).toHaveBeenCalledTimes(1);
    cleanup();
  });
```

## [120] web/src/components/gameMenu.test.tsx:749 `"#1732 GameMenu · 就地消解" / "退出游戏：面板直通，不调 window.confirm"`
flags=['web_calls_without_ui_token'] lines=14
```
  it("退出游戏：面板直通，不调 window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    global.fetch = vi.fn().mockResolvedValue({ ok: true } as Response);
    const { cleanup } = render(<ShutdownTab />);
    const btn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("退出游戏")
    );
    await act(async () => {
      btn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(confirm).not.toHaveBeenCalled();
    expect(global.fetch).toHaveBeenCalledWith("/api/menu/shutdown", { method: "POST" });
    cleanup();
  });
```

## [121] web/src/components/gameMenu.test.tsx:764 `"#1732 GameMenu · 就地消解" / "加载存档：取消就地确认零请求；确认后 POST load"`
flags=['web_calls_without_ui_token'] lines=48
```
  it("加载存档：取消就地确认零请求；确认后 POST load", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (String(url) === "/api/saves" && !init?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ saves: [{ name: "slot_a", mtime: 1, size: 2048 }] }),
        } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });
    const onAfterLoad = vi.fn();
    const { cleanup } = render(<LoadTab onAfterLoad={onAfterLoad} />);
    await act(async () => {});

    const loadBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").trim() === "加载" || (b.textContent || "").includes("加载")
    );
    expect(loadBtn).toBeTruthy();
    await act(async () => {
      loadBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel = document.querySelector('[aria-label="确认加载 slot_a"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    await act(async () => {
      cancel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(calls.some((c) => String(c.url).includes("/load"))).toBe(false);

    await act(async () => {
      loadBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel2 = document.querySelector('[aria-label="确认加载 slot_a"]');
    const yes = Array.from(panel2!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("加载")
    );
    await act(async () => {
      yes!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(calls.some((c) => String(c.url).includes("/api/saves/slot_a/load") && c.init?.method === "POST")).toBe(true);
    expect(onAfterLoad).toHaveBeenCalled();
    cleanup();
  });
```

## [122] web/src/components/gameMenu.test.tsx:813 `"#1732 GameMenu · 就地消解" / "删除存档：行下展开；取消零请求；确认后 DELETE"`
flags=['web_calls_without_ui_token'] lines=40
```
  it("删除存档：行下展开；取消零请求；确认后 DELETE", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });
    const onRefresh = vi.fn();
    const { cleanup } = render(
      <SavesList saves={[{ name: "keep", mtime: 1, size: 1024 }]} onRefresh={onRefresh} />
    );
    const del = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("删")
    );
    await act(async () => {
      del!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel = document.querySelector('[aria-label="确认删除 keep"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    await act(async () => {
      cancel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);

    await act(async () => {
      del!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const yes = Array.from(document.querySelector('[aria-label="确认删除 keep"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("删除")
    );
    await act(async () => {
      yes!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(calls.some((c) => String(c.url).includes("/api/saves/keep") && c.init?.method === "DELETE")).toBe(true);
    expect(onRefresh).toHaveBeenCalled();
    cleanup();
  });
```

## [123] web/src/components/menuPage.test.tsx:84 `"MenuPage continue SSE stages (#1195)" / "updates busy label from stage events then enters game"`
flags=['web_calls_without_ui_token'] lines=68
```
  it("updates busy label from stage events then enters game", async () => {
    const enterGame = vi.fn(async () => {});
    const setError = vi.fn();
    // 分块推送：第一读只给首条 stage，便于断言 busy 已更新；再推后续。
    const encoder = new TextEncoder();
    let pull = 0;
    const chunks = [
      'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
      'event: stage\ndata: {"content":"载入上次进度..."}\n\n',
      'event: stage\ndata: {"content":"重整朝堂名册..."}\n\n',
      'event: done\ndata: {"state":{"ok":true}}\n\n',
    ];
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url !== "/api/menu/continue") {
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      }
      const body = {
        getReader() {
          return {
            async read() {
              if (pull >= chunks.length) return { value: undefined, done: true };
              const value = encoder.encode(chunks[pull++]);
              return { value, done: false };
            },
          };
        },
      };
      return Promise.resolve({ ok: true, status: 200, body } as unknown as Response);
    });

    const cleanup = render(
      <MenuPage
        status={readyStatus as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={enterGame}
        error=""
        setError={setError}
      />
    );

    const continueBtn = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "继续"
    );
    expect(continueBtn).toBeTruthy();
    expect(continueBtn?.disabled).toBe(false);

    await act(async () => {
      continueBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // 让微任务跑完首条 stage 的 setBusy
      await Promise.resolve();
      await Promise.resolve();
    });

    // 流消费完成后应进游戏；busy 区在 finally 清空
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch).toHaveBeenCalledWith("/api/menu/continue", { method: "POST" });
    expect(enterGame).toHaveBeenCalledTimes(1);
    // guard 开头会 setError("") 清旧错；成功路径不应再写入非空错误
    const errorPayloads = setError.mock.calls.map((c) => c[0]).filter((m) => m);
    expect(errorPayloads).toEqual([]);
    // 终态 busy 已清（进 HUD 由 onEnterGame 负责）
    expect(document.querySelector(".menu-busy")).toBeNull();
    cleanup();
  });
```

## [124] web/src/components/menuPage.test.tsx:153 `"MenuPage continue SSE stages (#1195)" / "surfaces SSE error message without entering game"`
flags=['web_calls_without_ui_token'] lines=34
```
  it("surfaces SSE error message without entering game", async () => {
    const enterGame = vi.fn(async () => {});
    const setError = vi.fn();
    global.fetch = vi.fn().mockResolvedValue(
      streamResponse([
        'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
        'event: error\ndata: {"message":"未配 API key，请先到设置页填写。"}\n\n',
      ]),
    );

    const cleanup = render(
      <MenuPage
        status={readyStatus as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={enterGame}
        error=""
        setError={setError}
      />
    );

    const continueBtn = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "继续"
    );
    await act(async () => {
      continueBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // 等 reader 抽完 stage+error 并 throw→guard catch
      for (let i = 0; i < 10; i++) await Promise.resolve();
    });

    expect(enterGame).not.toHaveBeenCalled();
    const errMsg = setError.mock.calls.map((c) => String(c[0] || "")).find((m) => m.includes("未配 API key"));
    expect(errMsg).toBeTruthy();
    cleanup();
  });
```

## [125] web/src/components/menuPage.test.tsx:975 `"#1732 MenuPage · 就地消解" / "有主进度时「开始新游戏」展开就地卡；取消零请求；确认后 POST new_game"`
flags=['web_calls_without_ui_token'] lines=46
```
  it("有主进度时「开始新游戏」展开就地卡；取消零请求；确认后 POST new_game", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const enterGame = vi.fn(async () => {});
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });
    const cleanup = render(
      <MenuPage
        status={{ ...readyStatus, has_main_db: true } as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={enterGame}
        error=""
        setError={() => {}}
      />
    );
    const start = Array.from(document.querySelectorAll("button")).find((b) =>
      b.textContent?.trim() === "开始新游戏"
    );
    await act(async () => {
      start!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const card = document.querySelector('[aria-label="覆盖主进度确认"]');
    expect(card).not.toBeNull();
    const cancel = Array.from(card!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    await act(async () => {
      cancel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(calls.some((c) => String(c.url).includes("/api/menu/new_game"))).toBe(false);

    await act(async () => {
      start!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const yes = Array.from(document.querySelector('[aria-label="覆盖主进度确认"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").trim() === "继续"
    );
    await act(async () => {
      yes!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      for (let i = 0; i < 6; i++) await Promise.resolve();
    });
    expect(calls.some((c) => String(c.url) === "/api/menu/new_game" && c.init?.method === "POST")).toBe(true);
    expect(enterGame).toHaveBeenCalled();
    cleanup();
  });
```

## [126] web/src/components/menuPage.test.tsx:1022 `"#1732 MenuPage · 就地消解" / "删除存档：行下展开；取消零请求；确认后调用 onDelete"`
flags=['web_calls_without_ui_token'] lines=42
```
  it("删除存档：行下展开；取消零请求；确认后调用 onDelete", async () => {
    const onDelete = vi.fn(async () => {});
    const cleanup = render(
      <SaveListModal
        campaigns={[{
          campaign_id: "c1",
          kind: "manual",
          current: false,
          saves: [{ name: "辽饷吃紧", label: "辽饷吃紧", mtime: 1, size: 10 }],
        }] as any}
        onClose={() => {}}
        onLoad={async () => {}}
        onDelete={onDelete}
      />
    );
    const del = document.querySelector(".menu-save-del") as HTMLButtonElement;
    await act(async () => {
      del.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel = document.querySelector('[aria-label="确认删除存档 辽饷吃紧"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    await act(async () => {
      cancel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onDelete).not.toHaveBeenCalled();

    await act(async () => {
      del.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const yes = Array.from(document.querySelector('[aria-label="确认删除存档 辽饷吃紧"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("删除")
    );
    await act(async () => {
      yes!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(onDelete).toHaveBeenCalledWith("辽饷吃紧");
    cleanup();
  });
```

## [127] web/src/components/modals.test.tsx:288 `"EdictModal — decree desk behavior" / "issues an approved conversational draft without a second review gate"`
flags=['web_calls_without_ui_token'] lines=16
```
  it("issues an approved conversational draft without a second review gate", () => {
    const onIssue = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ directives: [{ id: 8, event_id: "", event_title: "", actor: "", text: "发饷辽东", source: "chat", status: "pending", notes: "", authority: "" }] }),
      onIssueDecree: onIssue,
    });
    const item = host.querySelector(".directive-item");
    const tools = item?.querySelectorAll(".directive-tools button");
    const button = host.querySelector<HTMLButtonElement>(".desk-footer button");

    expect(item).not.toBeNull();
    expect(tools).toHaveLength(2);
    expect(button?.disabled).toBe(false);
    act(() => button?.click());
    expect(onIssue).toHaveBeenCalledTimes(1);
  });
```

## [128] web/src/components/modals.test.tsx:305 `"EdictModal — decree desk behavior" / "#1732 failed-only：页脚就地确认；取消零调用；确认后退朝"`
flags=['web_calls_without_ui_token'] lines=36
```
  it("#1732 failed-only：页脚就地确认；取消零调用；确认后退朝", () => {
    const onAdvance = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    const { host } = renderEdictModal({
      state: baseGameState({
        directives: [],
        pending_directive_count: 0,
        pending_secret_order_count: 0,
        pending_non_directive_action_count: 0,
        failed_secret_order_count: 1,
      }),
      onAdvanceWithoutEdict: onAdvance,
    });
    const footer = host.querySelector<HTMLButtonElement>(".desk-footer button");
    expect(footer?.disabled).toBe(false);
    act(() => footer?.click());
    expect(confirm).not.toHaveBeenCalled();
    expect(onAdvance).not.toHaveBeenCalled();
    const panel = host.querySelector('[aria-label="退朝确认"]');
    expect(panel).not.toBeNull();
    expect(panel?.textContent).toContain("失败密令未处理");
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    act(() => cancel?.click());
    expect(onAdvance).not.toHaveBeenCalled();
    expect(host.querySelector('[aria-label="退朝确认"]')).toBeNull();

    const footer2 = host.querySelector<HTMLButtonElement>(".desk-footer button");
    act(() => footer2?.click());
    const yes = Array.from(host.querySelector('[aria-label="退朝确认"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("退朝结束本月")
    );
    act(() => yes?.click());
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });
```

## [129] web/src/components/modals.test.tsx:344 `"#1732 ChatModal · 撤回就地确认" / "取消零调用；确认后 onUndo"`
flags=['web_calls_without_ui_token'] lines=30
```
  it("取消零调用；确认后 onUndo", () => {
    const onUndo = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      canUndoLastChat: true,
      onUndo,
    });
    const undo = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("撤回本轮")
    ) as HTMLButtonElement;
    act(() => undo.click());
    expect(confirm).not.toHaveBeenCalled();
    expect(onUndo).not.toHaveBeenCalled();
    const panel = host.querySelector('[aria-label="撤回召对确认"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    act(() => cancel?.click());
    expect(onUndo).not.toHaveBeenCalled();

    act(() => undo.click());
    const yes = Array.from(host.querySelector('[aria-label="撤回召对确认"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("继续撤回")
    );
    act(() => yes?.click());
    expect(onUndo).toHaveBeenCalledWith("周延儒");
  });
```

## [130] web/src/components/modals.test.tsx:375 `"#1732 ChatModal · 撤回就地确认" / "#1732 T3 开着确认条发送后确认条关闭"`
flags=['web_calls_without_ui_token'] lines=28
```
  it("#1732 T3 开着确认条发送后确认条关闭", () => {
    const onSend = vi.fn();
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      canUndoLastChat: true,
      onSend,
    });
    const undo = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("撤回本轮")
    ) as HTMLButtonElement;
    act(() => undo.click());
    expect(host.querySelector('[aria-label="撤回召对确认"]')).not.toBeNull();

    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "问边饷");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("发送")
    ) as HTMLButtonElement;
    act(() => send.click());

    expect(onSend).toHaveBeenCalledWith("周延儒", "问边饷");
    expect(host.querySelector('[aria-label="撤回召对确认"]')).toBeNull();
  });
```

## [131] web/src/components/modals.test.tsx:404 `"#1732 ChatModal · 撤回就地确认" / "#1732 T3 开着确认条点散夜后确认条关闭"`
flags=['web_calls_without_ui_token'] lines=22
```
  it("#1732 T3 开着确认条点散夜后确认条关闭", () => {
    const onSend = vi.fn();
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      canUndoLastChat: true,
      onSend,
    });
    const undo = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("撤回本轮")
    ) as HTMLButtonElement;
    act(() => undo.click());
    expect(host.querySelector('[aria-label="撤回召对确认"]')).not.toBeNull();

    const retreat = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("散夜")
    ) as HTMLButtonElement;
    act(() => retreat.click());

    expect(onSend).toHaveBeenCalledWith("周延儒", "退朝");
    expect(host.querySelector('[aria-label="撤回召对确认"]')).toBeNull();
  });
```

## [132] web/src/components/modals.test.tsx:447 `"ChatModal — #545 final composer contract" / "#1278 召对收夜钮称散夜，仍走 chat 口令「退朝」seam，不与拟诏台退朝撞名"`
flags=['web_calls_without_ui_token'] lines=18
```
  it("#1278 召对收夜钮称散夜，仍走 chat 口令「退朝」seam，不与拟诏台退朝撞名", () => {
    const onSend = vi.fn();
    const onClose = vi.fn();
    const host = renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", onSend, onClose });

    const buttons = Array.from(host.querySelectorAll("button"));
    const leave = buttons.find((button) => button.textContent?.includes("退出召对")) as HTMLButtonElement;
    const retreat = buttons.find((button) => button.textContent?.includes("散夜")) as HTMLButtonElement;
    expect(leave).toBeTruthy();
    expect(retreat).toBeTruthy();

    act(() => leave.click());
    expect(onClose).toHaveBeenCalledOnce();
    expect(onSend).not.toHaveBeenCalled();
    act(() => retreat.click());
    // 机制零改动：仍发后端 COURT_BREAK_COMMANDS 既认词
    expect(onSend).toHaveBeenCalledWith("周延儒", "退朝");
  });
```

## [133] web/src/components/modals.test.tsx:491 `"ChatModal — reply recovery controls" / "shows #505 system-layer reply retry control when replyRetry is set"`
flags=['web_calls_without_ui_token'] lines=23
```
  it("shows #505 system-layer reply retry control when replyRetry is set", () => {
    const retry = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [{ role: "user", content: "剿抚孰先？" }],
      replyRetries: [
        { chat_turn_id: 12, question: "剿抚孰先？" },
        { chat_turn_id: 13, question: "退朝", recovery_phase: "court_break", error_pack_path: "/tmp/post-reply-pack" },
      ],
      onRetryReply: retry,
    });
    const note = document.querySelector('[data-testid="reply-retry-12"]');
    expect(note?.textContent).toContain("剿抚孰先？");
    expect(document.querySelector('[data-testid="reply-retry-13"]')?.textContent).toContain("/tmp/post-reply-pack");
    const button = Array.from(document.querySelectorAll("button")).find(
      (node) => node.textContent === "重试",
    );
    expect(button).toBeTruthy();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith("殿上", 12);
  });
```

## [134] web/src/components/modals.test.tsx:578 `"ChatModal — soft scenes and selected-minister lens (#543 / #1511)" / "keeps a side interjection in the selected minister segment without window bleed"`
flags=['web_calls_without_ui_token'] lines=52
```
  it("keeps a side interjection in the selected minister segment without window bleed", async () => {
    const send = vi.fn();
    const undo = vi.fn();
    const retryReply = vi.fn();
    const yang = { ...MINISTER_MOCK, id: "yang", name: "杨嗣昌", summary: "兵部旧臣", favorite: false };
    const hong = { ...MINISTER_MOCK, id: "hong", name: "洪承畴", office: "三边总督", summary: "边臣", favorite: true };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "洪承畴", roster: [{ name: "洪承畴", present: true }], container: { time_of_day: "戌时", location: "乾清宫", audience_type: "越次召对" }, translation_retries: [{ chat_turn_id: 1, night_id: 23, minister_name: "洪承畴", kind: "translation_pending", retryable: true, error_pack_path: "/tmp/audience-turn-1" }], messages: [
      { role: "scene", speaker: "洪承畴", content: "", beat: "divider", soft_boundary: true, container: { audience_type: "越次召对" } },
      { role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "entrance", container: { audience_type: "越次召对" } },
      { role: "minister", speaker: "洪承畴", content: "臣自三边来。", beat: "dialogue", container: { audience_type: "越次召对" }, chat_turn_id: 1 },
      { role: "minister", speaker: "杨嗣昌", content: "殿侧容臣插一句。", beat: "dialogue", container: { audience_type: "越次召对" } },
      { role: "user", speaker: "朕", content: "辽饷何解？", beat: "dialogue", container: { audience_type: "越次召对" }, chat_turn_id: 12 },
      { role: "scene", speaker: "", content: "", beat: "divider", soft_boundary: true, container: { audience_type: "越次召对" } },
    ] }) }));

    // #1511 lens key = selected minister (洪), not a mismatched modal entry.
    const host = renderModal({
      minister: hong,
      ministers: [yang, hong],
      portraitPrefix: "minister_",
      currentNightId: 23,
      onSend: send,
      onUndo: undo,
      canUndoLastChat: true,
      replyRetries: [{ chat_turn_id: 12, question: "辽饷何解？" }],
      onRetryReply: retryReply,
      onRetryTranslation: vi.fn(),
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(host.querySelector(".minister-profile")).toBeNull();
    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_hong.png");
    expect(host.querySelector(".chat-secret-orders")).toBeNull();
    const ministerMessages = host.querySelectorAll(".chat-message.minister");
    expect(ministerMessages[ministerMessages.length - 1]?.textContent).toContain("杨嗣昌");
    const clickButton = (text: string) => act(() => Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.includes(text))?.click());
    // #1732 B：撤回就地确认
    clickButton("撤回本轮");
    clickButton("继续撤回");
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="reply-retry-12"] button')?.click());
    expect(undo).toHaveBeenCalledWith("洪承畴");
    expect(retryReply).toHaveBeenCalledWith("殿上", 12);
    const replyFailure = host.querySelector('[data-testid="reply-retry-12"]');
    expect(replyFailure?.closest('[data-audience-turn-id="12"]')).not.toBeNull();
    const translationFailure = host.querySelector('[data-testid="translation-retry-1"]');
    expect(translationFailure?.closest('[data-audience-turn-id="1"]')).not.toBeNull();
    expect(translationFailure?.textContent).toContain("/tmp/audience-turn-1");
    const divisions = Array.from(host.querySelectorAll(".beat-divider"));
    expect(divisions).toHaveLength(2);
    expect(divisions[0]?.textContent).toContain("洪承畴");
    expect(divisions[1]?.textContent).not.toMatch(/杨嗣昌|洪承畴/);
  });
```

## [135] web/src/components/modals.test.tsx:723 `"ChatModal — single night-scroll authority (#539)" / "restores at the tail, follows new content only while the player remains at the tail"`
flags=['web_calls_without_ui_token'] lines=35
```
  it("restores at the tail, follows new content only while the player remains at the tail", async () => {
    let resolveScroll!: (value: unknown) => void;
    const fetchMock = vi.fn().mockReturnValue(new Promise((resolve) => { resolveScroll = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    let updateChat!: (chat: ChatMessage[]) => void;
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [{ role: "user", content: "初问" }],
      registerChatUpdate: (update) => { updateChat = update; },
    });
    const log = host.querySelector(".chat-log") as HTMLDivElement;
    let scrollHeight = 600;
    Object.defineProperties(log, {
      scrollHeight: { get: () => scrollHeight },
      clientHeight: { get: () => 200 },
    });

    await act(async () => {
      resolveScroll({ ok: true, json: async () => ({ night_id: 17, protagonist: "", roster: [], translation_pending: false, messages: [{ role: "user", content: "卷首" }] }) });
      await Promise.resolve(); await Promise.resolve();
    });
    expect(log.scrollTop).toBe(600);

    scrollHeight = 700;
    await act(async () => { updateChat([{ role: "user", content: "完成一轮" }]); await Promise.resolve(); });
    expect(log.scrollTop).toBe(700);

    log.scrollTop = 100;
    act(() => log.dispatchEvent(new Event("scroll", { bubbles: true })));
    scrollHeight = 800;
    await act(async () => { updateChat([{ role: "user", content: "完成二轮" }]); await Promise.resolve(); });
    expect(log.scrollTop).toBe(100);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
```

## [136] web/src/components/modals.test.tsx:995 `"ChatModal — one-night audience scroll (#1849)" / "uses roster clicks as summon commands without changing panels"`
flags=['web_calls_without_ui_token'] lines=10
```
  it("uses roster clicks as summon commands without changing panels", async () => {
    const onSend = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "许誉卿", roster: [{ name: "洪承畴", present: true }, { name: "许誉卿", present: true }], messages: nightScroll }) }));
    renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23, onSend });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const summon = Array.from(document.querySelectorAll<HTMLButtonElement>(".audience-roster button"))
      .find((button) => button.textContent?.includes("洪承畴"));
    act(() => summon?.click());
    expect(onSend).toHaveBeenCalledWith("许誉卿", "宣洪承畴");
  });
```

## [137] web/src/components/modals.test.tsx:1181 `"ChatModal — one-night audience scroll (#1849)" / "shows a background translation failure beneath its turn without reopening the scroll"`
flags=['web_calls_without_ui_token'] lines=23
```
  it("shows a background translation failure beneath its turn without reopening the scroll", async () => {
    vi.useFakeTimers();
    const story = { role: "scene", content: "臣请据实核账。", chat_turn_id: 11 };
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => (++reads === 1
        ? { night_id: 23, messages: [story], translation_pending: true, translation_retries: [] }
        : { night_id: 23, messages: [story], translation_pending: true, translation_retries: [
            { chat_turn_id: 11, night_id: 23, minister_name: "洪承畴", kind: "translation_pending", retryable: true, error_pack_path: "/tmp/turn-11" },
          ] }),
    })));
    const retry = vi.fn();
    renderModal({ minister: hong, ministers: [hong], portraitPrefix: "minister_", currentNightId: 23, onRetryTranslation: retry });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.querySelector('[data-testid="translation-retry-11"]')).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    const turn = document.querySelector('[data-audience-turn-id="11"]');
    const button = turn?.querySelector<HTMLButtonElement>('[data-testid="translation-retry-11"] button');
    expect(button).not.toBeNull();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledWith(11);
  });
```

## [138] web/src/components/modals.test.tsx:1349 `"AudienceArchiveModal — read-only scene archive" / "keeps the selected night when an earlier night's translation retry finishes late"`
flags=['web_calls_without_ui_token'] lines=35
```
  it("keeps the selected night when an earlier night's translation retry finishes late", async () => {
    let releaseOldRetry: (() => void) | undefined;
    let releaseNewRetry: (() => void) | undefined;
    const oldRetryGate = new Promise<void>((resolve) => { releaseOldRetry = resolve; });
    const newRetryGate = new Promise<void>((resolve) => { releaseNewRetry = resolve; });
    const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === "/api/history/turns") return Promise.resolve({ ok: true, json: async () => ({ turns: [
        { kind: "night", night_id: 32, title: "乙夜", involved_people: [] },
        { kind: "night", night_id: 31, title: "甲夜", involved_people: [] },
      ] }) });
      if (url === "/api/audience/translation/retry" && options?.method === "POST") return (JSON.parse(String(options.body)).chat_turn_id === 31 ? oldRetryGate : newRetryGate).then(() => ({ ok: true, json: async () => ({}) }));
      const nightId = url.endsWith("31") ? 31 : 32;
      return Promise.resolve({ ok: true, json: async () => ({
        messages: [{ role: "user", content: nightId === 31 ? "甲夜奏对" : "乙夜奏对", chat_turn_id: nightId }],
        translation_retries: [{ chat_turn_id: nightId, night_id: nightId, minister_name: "洪承畴", kind: "translation_pending", retryable: true }],
      }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => { root.render(<AudienceArchiveModal ministers={[]} onClose={() => {}} />); await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { host.querySelector<HTMLButtonElement>('[data-testid="archive-translation-retry-31"] button')?.click(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/audience/translation/retry", expect.objectContaining({ method: "POST", body: JSON.stringify({ chat_turn_id: 31 }) }));
    await act(async () => { host.querySelector<HTMLButtonElement>(".history-turn-item:not(.active)")?.click(); await Promise.resolve(); await Promise.resolve(); });
    const newRetry = host.querySelector<HTMLButtonElement>('[data-testid="archive-translation-retry-32"] button');
    expect(newRetry?.disabled).toBe(false);
    await act(async () => { newRetry?.click(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/audience/translation/retry", expect.objectContaining({ method: "POST", body: JSON.stringify({ chat_turn_id: 32 }) }));
    await act(async () => { releaseOldRetry?.(); await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".history-turn-item.active")?.textContent).toContain("乙夜");
    expect(host.textContent).toContain("乙夜奏对");
    expect(host.textContent).not.toContain("甲夜奏对");
    expect(host.querySelector<HTMLButtonElement>('[data-testid="archive-translation-retry-32"] button')?.disabled).toBe(true);
    await act(async () => { releaseNewRetry?.(); await Promise.resolve(); await Promise.resolve(); });
  });
```

## [139] web/src/components/modals.test.tsx:1384 `"AudienceArchiveModal — read-only scene archive" / "retries a pending translation on its original closed night"`
flags=['web_calls_without_ui_token'] lines=24
```
  it("retries a pending translation on its original closed night", async () => {
    let pending = true;
    const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === "/api/history/turns") return Promise.resolve({ ok: true, json: async () => ({ turns: [
        { kind: "night", night_id: 31, title: "旧夜", involved_people: [] },
      ] }) });
      if (url === "/api/audience/translation/retry" && options?.method === "POST") {
        pending = false;
        return Promise.resolve({ ok: true, json: async () => ({ chat_turn_id: 8 }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ messages: [{ role: "minister", content: "旧夜奏对", chat_turn_id: 8 }], translation_retries: pending ? [
        { chat_turn_id: 8, night_id: 31, minister_name: "洪承畴", kind: "translation_pending", retryable: true },
      ] : [] }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => { root.render(<AudienceArchiveModal ministers={[]} onClose={() => {}} />); await Promise.resolve(); await Promise.resolve(); });
    const retry = host.querySelector<HTMLButtonElement>('[data-testid="archive-translation-retry-8"] button');
    expect(retry).not.toBeNull();
    await act(async () => { retry?.click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/audience/translation/retry", expect.objectContaining({ method: "POST", body: JSON.stringify({ chat_turn_id: 8 }) }));
    expect(host.querySelector('[data-testid="archive-translation-retry-8"]')).toBeNull();
  });
```

## [140] web/src/components/modals.test.tsx:1428 `"AudienceArchiveModal — read-only scene archive" / "selects closed scenes through the shared scroll endpoint without a composer"`
flags=['web_calls_without_ui_token'] lines=68
```
  it("selects closed scenes through the shared scroll endpoint without a composer", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/history/turns") return Promise.resolve({ ok: true, json: async () => ({ turns: [
        { kind: "month", turn: 7, year: 1, period: 11, has_report: true, has_attendant: false, has_directive: false },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 31, title: "1年11月 · 戌时乾清宫 · 越次召对 · 第1场", involved_people: ["杨嗣昌"] },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 32, title: "1年11月 · 戌时乾清宫 · 召对 · 第2场", involved_people: ["洪承畴", "王绍徽", "许誉卿", "杨嗣昌"] },
      ] }) });
      const id = url.endsWith("31") ? 31 : 32;
      return Promise.resolve({ ok: true, json: async () => ({ characters: id === 32 ? [{ ...MINISTER_MOCK, id: "former-attendant", name: "退场近臣", portrait_id: "portrait_court_03" }] : [], messages: id === 32 ? [
        { role: "user", speaker: "朕", content: `场次${id}`, beat: "dialogue", chat_turn_id: 8 },
        { role: "minister", speaker: "殿上", content: "群臣奏对", beat: "dialogue", chat_turn_id: 8 },
        { role: "attendant", speaker: "退场近臣", content: "旧臣御前低语", beat: "aside", chat_turn_id: 8, audibility: "御前低语" },
        { role: "user", speaker: "朕", content: "边务如何？", beat: "dialogue", chat_turn_id: 9 },
        { role: "minister", speaker: "洪承畴", content: "臣自三边来。", beat: "dialogue", chat_turn_id: 9 },
        { role: "attendant", speaker: "王承恩", content: "臣亦有虑。", beat: "aside", chat_turn_id: 9 },
        { role: "user", speaker: "朕", content: "卿有何见？", beat: "dialogue", chat_turn_id: 10 },
        { role: "minister", speaker: "王绍徽", content: "臣请核账。", beat: "dialogue", chat_turn_id: 10 },
        { role: "user", speaker: "朕", content: "无主问话", beat: "dialogue", chat_turn_id: 11 },
        { role: "attendant", speaker: "王承恩", content: "无主递话", beat: "aside", chat_turn_id: 11 },
        { role: "scene", speaker: "洪承畴", content: "", beat: "divider", soft_boundary: true },
        { role: "scene", speaker: "", content: "趋入殿中。", beat: "scene" },
        { role: "user", speaker: "朕", content: "剿抚孰先？", beat: "dialogue", chat_turn_id: 12 },
        { role: "minister", speaker: "洪承畴", content: "臣请先抚。", beat: "dialogue", chat_turn_id: 12 },
        { role: "minister", speaker: "杨嗣昌", content: "殿侧容臣插一句。", beat: "dialogue" },
        { role: "user", speaker: "朕", content: "钱粮如何？", beat: "dialogue", chat_turn_id: 13 },
        { role: "minister", speaker: "王绍徽", content: "臣请详查。", beat: "dialogue", chat_turn_id: 13 },
        { role: "attendant", speaker: "王承恩", content: "已闻其议。", beat: "aside", chat_turn_id: 13 },
        { role: "scene", speaker: "", content: "", beat: "divider", soft_boundary: true },
        { role: "user", speaker: "朕", content: "诸卿同议。", beat: "dialogue", chat_turn_id: 14 },
        { role: "minister", speaker: "洪承畴", content: "臣有一议。", beat: "dialogue", chat_turn_id: 14 },
        { role: "minister", speaker: "许誉卿", content: "臣愿附议。", beat: "dialogue", chat_turn_id: 14 },
      ] : [{ role: "user", content: `场次${id}` }] }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => { root.render(<AudienceArchiveModal ministers={[]} onClose={() => {}} />); await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { host.querySelector<HTMLButtonElement>(".history-turn-item.active")?.click(); });
    const filter = host.querySelector<HTMLSelectElement>('select[aria-label="按臣过滤"]')!;
    await act(async () => {
      filter.value = "洪承畴";
      filter.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.textContent).toContain("群臣奏对");
    expect(host.querySelector("textarea, input, .chat-composer")).toBeNull();
    const archivedAvatar = host.querySelector<HTMLImageElement>(".aside-avatar");
    expect(archivedAvatar?.getAttribute("src")).toBe("/portraits/minister_former-attendant.png");
    const visibleTurnIds = () => [...new Set(Array.from(
      host.querySelectorAll<HTMLElement>("[data-audience-turn-id]"),
      (node) => node.dataset.audienceTurnId,
    ).filter(Boolean))].sort();
    expect(visibleTurnIds()).toEqual(["12", "14", "8", "9"]);
    expect(host.querySelectorAll('[data-audience-turn-id="9"] .turn-segment.user')).toHaveLength(1);
    expect(host.querySelectorAll('[data-audience-turn-id="9"] .turn-segment.attendant')).toHaveLength(1);
    for (const [name, ids] of [
      ["王绍徽", ["10", "13", "8"]], ["许誉卿", ["14", "8"]], ["杨嗣昌", ["8"]],
    ] as const) {
      await act(async () => {
        filter.value = name;
        filter.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(visibleTurnIds()).toEqual(ids);
    }
    const buttons = Array.from(host.querySelectorAll(".history-turn-item")) as HTMLButtonElement[];
    await act(async () => { buttons[1].click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/audience/scroll?night_id=31");
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="按臣过滤"]')?.value).toBe("");
  });
```

## [141] web/src/components/modals.test.tsx:1510 `"AudienceArchiveModal — read-only scene archive" / "#671 史册月档经 HistoryModal fetch 呈现独立递话原文"`
flags=['web_calls_without_ui_token'] lines=114
```
  it("#671 史册月档经 HistoryModal fetch 呈现独立递话原文", async () => {
    const raw = "\n  **皇爷**，洪承畴本月抵京候旨。  \n";
    const decree = "着宁远补饷三十万两";
    const blank = "   \n\t  ";
    const monthTurn = { kind: "month" as const, turn: 7, year: 1, period: 11, has_report: true, has_attendant: true, has_directive: false };
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url === "/api/history/turns"
        ? { turns: [monthTurn] }
        : {
            turn: 7,
            exists: true,
            year: 1,
            period: 11,
            report: "一、人事除目",
            attendant_message: raw,
            decree_text: decree,
            directives: [],
          },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => {
      root.render(<HistoryModal onClose={() => {}} />);
    });
    // 等详情链落地后再断言递话原文（完成信号，非固定微任务次数）
    await act(async () => {
      await vi.waitFor(async () => {
        await Promise.resolve();
        expect(host.querySelector("[data-testid=history-attendant]")).not.toBeNull();
      });
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/history/turns");
    expect(fetchMock).toHaveBeenCalledWith("/api/history/turn/7");
    const section = host.querySelector("[data-testid=history-attendant]");
    // trim 仅判空；DOM 写原文（含空白与 markdown 标记）
    expect(section!.querySelector("pre")?.textContent).toBe(raw);
    expect(Array.from(host.querySelectorAll("pre.memorial-text"))
      .some((element) => element.textContent === decree)).toBe(true);

    // 纯空白递话：先等详情 report 正文落地，再断言 section 缺席
    fetchMock.mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url === "/api/history/turns"
        ? { turns: [monthTurn] }
        : {
            turn: 7,
            exists: true,
            year: 1,
            period: 11,
            report: "一、人事除目",
            attendant_message: blank,
            decree_text: "",
            directives: [],
          },
    }));
    const hostBlank = document.createElement("div"); document.body.appendChild(hostBlank);
    const rootBlank = createRoot(hostBlank); mountedRoots.push({ root: rootBlank, host: hostBlank });
    await act(async () => {
      rootBlank.render(<HistoryModal onClose={() => {}} />);
    });
    await act(async () => {
      await vi.waitFor(async () => {
        await Promise.resolve();
        const reportPre = Array.from(hostBlank.querySelectorAll("pre.memorial-text"))
          .find((el) => el.textContent === "一、人事除目");
        expect(reportPre).toBeTruthy();
      });
    });
    expect(hostBlank.querySelector("[data-testid=history-attendant]")).toBeNull();

    // 第三场景：纯空白 report + 非空递话 → 递话原文呈现，不画空奏报 section
    const attendantOnlyTurn = {
      kind: "month" as const,
      turn: 7,
      year: 1,
      period: 11,
      has_report: false,
      has_attendant: true,
... (34 more lines)
```

## [142] web/src/components/modals.test.tsx:1686 `"ChatModal — cancel button during busy (issue #353)" / "calls onCancel when cancel button is clicked"`
flags=['web_calls_without_ui_token'] lines=12
```
  it("calls onCancel when cancel button is clicked", () => {
    const onCancel = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
      onCancel,
    });
    const cancelBtn = document.querySelector(".composer-cancel") as HTMLButtonElement;
    act(() => cancelBtn.click());
    expect(onCancel).toHaveBeenCalledOnce();
  });
```

## [143] web/src/components/modals.test.tsx:1720 `"ReportModal — narrative settlement bulletin" / "#1387 底部有朕知道了主按钮可达关闭，不靠右上小 X"`
flags=['web_calls_without_ui_token'] lines=15
```
  it("#1387 底部有朕知道了主按钮可达关闭，不靠右上小 X", () => {
    const onClose = vi.fn();
    const host = renderReportModal({
      report: "一、边报\n\n二、钱粮\n\n三、探子回报\n下文应可滚完",
      onClose,
    });
    const dismiss = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了") || (b.textContent || "").includes("收卷"),
    ) as HTMLButtonElement | undefined;
    expect(dismiss).toBeTruthy();
    expect(host.querySelector(".gazette-document")).not.toBeNull();
    expect(host.querySelector(".gazette-dismiss")).not.toBeNull();
    act(() => dismiss!.click());
    expect(onClose).toHaveBeenCalledOnce();
  });
```

## [144] web/src/components/modals.test.tsx:1753 `"ReportModal — narrative settlement bulletin" / "#1356 空邸报态不崩：卷轴壳复用 pre + 朕知道了可关闭（无固定空注）"`
flags=['web_calls_without_ui_token'] lines=14
```
  it("#1356 空邸报态不崩：卷轴壳复用 pre + 朕知道了可关闭（无固定空注）", () => {
    const onClose = vi.fn();
    const host = renderReportModal({ report: "", onClose });
    expect(host.querySelector(".gazette-document")).not.toBeNull();
    expect(host.querySelector(".gazette-masthead")).not.toBeNull();
    // 空壳复用原 pre，不另写固定空态文案
    expect(host.querySelector("pre.memorial-text")).not.toBeNull();
    const dismiss = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了"),
    ) as HTMLButtonElement | undefined;
    expect(dismiss).toBeTruthy();
    act(() => dismiss!.click());
    expect(onClose).toHaveBeenCalledOnce();
  });
```

## [145] web/src/components/modals.test.tsx:1768 `"ReportModal — narrative settlement bulletin" / "#1398 朕知道了视口常显：不埋在长文滚底"`
flags=['web_calls_without_ui_token'] lines=19
```
  it("#1398 朕知道了视口常显：不埋在长文滚底", () => {
    const onClose = vi.fn();
    const longReport = Array.from({ length: 48 }, (_, i) =>
      `第${i + 1}段·边报钱粮探子回报——${"详文".repeat(24)}`,
    ).join("\n\n");
    const host = renderReportModal({ report: longReport, onClose });
    const scroll = host.querySelector(".gazette-document") as HTMLElement | null;
    const dismissWrap = host.querySelector(".gazette-dismiss") as HTMLElement | null;
    const dismissBtn = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了"),
    ) as HTMLButtonElement | undefined;
    expect(scroll).not.toBeNull();
    expect(dismissWrap).not.toBeNull();
    expect(dismissBtn).toBeTruthy();
    // 吸底/视口常显：dismiss 不得是滚容器后代（长文滚底才见）
    expect(scroll!.contains(dismissWrap)).toBe(false);
    act(() => dismissBtn!.click());
    expect(onClose).toHaveBeenCalledOnce();
  });
```

## [146] web/src/components/settlementGazettePanel.test.tsx:27 `"#1852 SettlementGazettePanel" / "本面落位：正文直写；朕知道了只调 onDismiss"`
flags=['web_calls_without_ui_token'] lines=23
```
  it("本面落位：正文直写；朕知道了只调 onDismiss", () => {
    const onDismiss = vi.fn();
    const host = mount(
      <SettlementGazettePanel
        report={"十月邸报\n一、边报"}
        attendantMessage="奴婢呈报。"
        periodLabel="天启七年十月"
        onDismiss={onDismiss}
      />,
    );
    expect(host.querySelector("[data-testid=settlement-gazette-panel]")).not.toBeNull();
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(host.querySelector("pre.memorial-text")?.textContent).toBe("十月邸报\n一、边报");
    expect(host.querySelector("[data-testid=gazette-attendant]")?.textContent).toContain("奴婢呈报。");
    expect(host.textContent).toContain("天启七年十月");

    const btn = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了"),
    );
    expect(btn).toBeTruthy();
    act(() => { btn!.click(); });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
```

## [147] web/src/useSettlementFlow.test.tsx:165 `"#1625 useSettlementFlow — observation refresh convergence" / "throttles inflight reloads and converges to the visible phase returned after waiting"`
flags=['web_calls_without_ui_token'] lines=54
```
  it("throttles inflight reloads and converges to the visible phase returned after waiting", async () => {
    vi.useFakeTimers();
    // Real prior phase while entry is in flight: accept sets settlement_display +
    // inflight before pre_settle writes SETTLING (still summoning/reviewing).
    const inflightState = {
      ...awaitingState,
      turn: { ...awaitingState.turn, phase: "summoning", settlement_display: true },
      pending_decisions: [],
      settlement_entry_inflight: true,
    } as GameState;
    const visibleDesk = [validDecision];
    const settledState = {
      ...awaitingState,
      pending_decisions: visibleDesk,
      settlement_entry_inflight: false,
    } as GameState;
    const pollError = new Error("transient poll failure");
    const loadState = vi
      .fn<() => Promise<GameState | null>>()
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(pollError)
      .mockResolvedValueOnce(settledState);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, cleanup } = mountHarness({ initial: inflightState, loadState });

    expect(loadState).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(loadState).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadState).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[data-testid="phase"]')?.textContent).toBe("summoning");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(loadState).toHaveBeenCalledTimes(2);
    expect(host.querySelector('[data-testid="phase"]')?.textContent).toBe("summoning");
    expect(host.querySelector('[data-testid="error"]')?.textContent).toBe("");
    expect(warn.mock.calls.some((call) => call.includes(pollError))).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(loadState).toHaveBeenCalledTimes(3);
    expect(host.querySelector('[data-testid="phase"]')?.textContent).toBe("awaiting_decision");
    expect(host.querySelector('[data-testid="pending-count"]')?.textContent).toBe("1");
    expect(host.querySelector('[data-testid="error"]')?.textContent).toBe("");
    expect(vi.getTimerCount()).toBe(0);
    cleanup();
  });
```

## [148] web/src/useSettlementFlow.test.tsx:222 `"#1845 ending summary stays background and becomes visible" / "opens with a pending summary and shows it when the tail lands"`
flags=['web_calls_without_ui_token'] lines=43
```
  it("opens with a pending summary and shows it when the tail lands", async () => {
    vi.useFakeTimers();
    const pendingEnding = {
      ...preClickState,
      ending: {
        status: "emperor_abdicate",
        label: "退位",
        summary: "",
        timeline: [],
        summary_pending: true,
      },
    } as GameState;
    const landed = {
      ...pendingEnding,
      ending: {
        ...pendingEnding.ending,
        summary: "史评",
        summary_pending: false,
      },
    } as GameState;
    const loadState = vi.fn<() => Promise<GameState | null>>().mockResolvedValue(landed);
    const { host, cleanup } = mountHarness({ initial: pendingEnding, loadState });

    const summary = () => host.querySelector(".ending-summary-text");
    expect(host.querySelector(".modal-bg-ending")).not.toBeNull();
    expect(summary()?.getAttribute("aria-busy")).toBe("true");
    expect(summary()?.textContent).toBe("");
    expect(loadState).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(loadState).toHaveBeenCalledTimes(1);
    expect(summary()?.getAttribute("aria-busy")).toBeNull();
    expect(summary()?.textContent).toBe("史评");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(loadState).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    cleanup();
  });
```

## [149] web/src/useSettlementFlow.test.tsx:268 `"#1845 background tail failure observation" / "shows a failed ending without a fabricated summary and retains retry"`
flags=['web_calls_without_ui_token'] lines=16
```
  it("shows a failed ending without a fabricated summary and retains retry", () => {
    const failed = {
      ...preClickState,
      ending: { status: "collapse", label: "社稷倾覆", summary: "", timeline: [], summary_pending: false },
      mechanical_tail_failure: { error: "模型调用耗尽", error_pack_path: "/tmp/pack.json" },
    } as GameState;
    const onRetry = vi.fn();
    const { host, cleanup } = mountHarness({ initial: failed, loadState: async () => failed, onRetry });

    expect(host.querySelector(".ending-summary-text")?.textContent).toBe("");
    const alert = host.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("模型调用耗尽");
    act(() => { alert?.querySelector("button")?.click(); });
    expect(onRetry).toHaveBeenCalledTimes(1);
    cleanup();
  });
```

## [150] web/src/useSettlementFlow.test.tsx:285 `"#1845 background tail failure observation" / "refreshes a non-ending month while the tail runs, then stops on persisted failure"`
flags=['web_calls_without_ui_token'] lines=15
```
  it("refreshes a non-ending month while the tail runs, then stops on persisted failure", async () => {
    vi.useFakeTimers();
    const running = { ...preClickState, mechanical_tail_pending: true } as GameState;
    const failed = {
      ...running, mechanical_tail_pending: false,
      mechanical_tail_failure: { error_pack_path: "/tmp/tail-error" },
    } as GameState;
    const loadState = vi.fn<() => Promise<GameState | null>>().mockResolvedValue(failed);
    const { cleanup } = mountHarness({ initial: running, loadState });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(loadState).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(loadState).toHaveBeenCalledTimes(1);
    cleanup();
  });
```

## [151] web/src/useSettlementFlow.test.tsx:303 `"#1351/#1560 useSettlementFlow — advanceWithoutEdict 令牌与 409 幂等" / "POST 携 state.turn 为 expected_turn"`
flags=['web_calls_without_ui_token'] lines=36
```
  it("POST 携 state.turn 为 expected_turn", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        state: advancedMonthState,
        advanced: true,
        pending_action_failures: [],
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });
    const loadState = vi.fn(async () => advancedMonthState);

    const { hookRef, cleanup } = mountHarness({
      loadState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/api/decree/advance_without_edict");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ expected_turn: 5 });
    // #1852：写成即推进走 loadState + 本面阅读，不整页 reload
    expect(reload).not.toHaveBeenCalled();
    expect(loadState).toHaveBeenCalled();
    cleanup();
  });
```

## [152] web/src/useSettlementFlow.test.tsx:340 `"#1351/#1560 useSettlementFlow — advanceWithoutEdict 令牌与 409 幂等" / "409 且服务端 turn>expected 时按已推进 reload，不设 error 条"`
flags=['web_calls_without_ui_token'] lines=29
```
  it("409 且服务端 turn>expected 时按已推进 reload，不设 error 条", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({
        detail: { message: "月份已变更（当前第 6 月），与退朝令牌不符，请刷新后再试。", turn: 6 },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { host, hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(reload).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-testid=error]")?.textContent).toBe("");
    cleanup();
  });
```

## [153] web/src/useSettlementFlow.test.tsx:370 `"#1351/#1560 useSettlementFlow — advanceWithoutEdict 令牌与 409 幂等" / "409 且服务端 turn<=expected 时仍报错条、不 reload"`
flags=['web_calls_without_ui_token'] lines=29
```
  it("409 且服务端 turn<=expected 时仍报错条、不 reload", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({
        detail: { message: "月末结算进行中，请待结算完成后再操作。" },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { host, hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(reload).not.toHaveBeenCalled();
    expect(host.querySelector("[data-testid=error]")?.textContent || "").not.toBe("");
    cleanup();
  });
```

## [154] web/src/useSettlementFlow.test.tsx:435 `"#1433 useSettlementFlow — 退朝 awaiting 消费面（禁盲 reload hop）" / "advance 回 awaiting_decision 时消费 decisions + loadState，不 reload"`
flags=['web_calls_without_ui_token'] lines=48
```
  it("advance 回 awaiting_decision 时消费 decisions + loadState，不 reload", async () => {
    const loadState = vi.fn(async () => awaitingState);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/api/decree/advance_without_edict")) {
          return {
            ok: true,
            json: async () => ({
              state: awaitingState,
              awaiting_decision: true,
              decisions: [validDecision],
              pending_action_failures: [],
            }),
          };
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    const { host, hookRef, cleanup } = mountHarness({
      loadState,
      initial: preClickState,
    });

    expect(host.querySelector("[data-testid=pending-count]")?.textContent).toBe("0");
    expect(host.querySelector("[data-testid=settlement-display]")?.textContent).toBe("false");

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(loadState).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
    // 批红面不丢：同会话停窗弹决策，HUD 读状态口投影
    expect(host.querySelector("[data-testid=pending-count]")?.textContent).toBe("1");
    expect(host.querySelector("[data-testid=settlement-display]")?.textContent).toBe("true");
    expect(host.querySelector("[data-testid=busy]")?.textContent).toBe("");
    expect(host.querySelector("[data-testid=error]")?.textContent).toBe("");

    cleanup();
  });
```

## [155] web/src/useSettlementFlow.test.tsx:510 `"#1277 useSettlementFlow — issueDecree 令牌与 409 幂等" / "POST 携 state.turn 为 expected_turn；409 且 serverTurn>expected → reload 不设 error"`
flags=['web_calls_without_ui_token'] lines=35
```
  it("POST 携 state.turn 为 expected_turn；409 且 serverTurn>expected → reload 不设 error", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || "{}"));
      // 首发成功路径不在本测；直接回 409 陈旧令牌以钉 reload 惯用法。
      expect(body.expected_turn).toBe(5);
      expect(body).toMatchObject({ cheat: "" });
      return sseErrorResponse({
        message: "月份已变更（当前第 6 月），与颁诏令牌不符，请刷新后再试。",
        turn: 6,
        status_code: 409,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { host, hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.issueDecree();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/api/decree/issue/stream");
    expect(reload).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-testid=error]")?.textContent).toBe("");
    cleanup();
  });
```

## [156] web/src/useSettlementFlow.test.tsx:548 `"#1234 useSettlementFlow — 同会话 awaiting 停窗消费状态口" / "decisions 分支 await loadState：·待批出现（#1323）+ 四键为月初值，且不 reload"`
flags=['web_calls_without_ui_token'] lines=39
```
  it("decisions 分支 await loadState：·待批出现（#1323）+ 四键为月初值，且不 reload", async () => {
    const loadState = vi.fn(async () => awaitingState);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/api/decree/issue/stream")) return sseDecisionsResponse();
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    const { host, hookRef, cleanup } = mountHarness({ loadState });

    // 点击前：无核账标
    expect(host.querySelector("[data-testid=settlement-display]")?.textContent).toBe("false");

    await act(async () => {
      await hookRef.current!.issueDecree();
    });

    expect(loadState).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();

    // 同会话不 reload：状态口投影驱动 HUD
    expect(host.querySelector("[data-testid=settlement-display]")?.textContent).toBe("true");
    expect(host.querySelector("[data-testid=treasury]")?.textContent).toBe("1781");
    expect(host.querySelector("[data-testid=inner]")?.textContent).toBe("320");
    expect(host.querySelector("[data-testid=minxin]")?.textContent).toBe("55");
    expect(host.querySelector("[data-testid=huangwei]")?.textContent).toBe("40");
    expect(host.querySelector("[data-testid=pending-count]")?.textContent).toBe("1");
    expect(host.querySelector("[data-testid=busy]")?.textContent).toBe("");

    cleanup();
  });
```

## [157] web/src/useSettlementFlow.test.tsx:590 `"#1843 未推进的过月终包" / "%s 留在账本核账态而非按完成 reload"`
flags=['web_calls_without_ui_token'] lines=33
```
  it.each([
    ["issueDecree", "/api/decree/issue/stream"],
    ["submitDecisions", "/api/decree/resolve_decisions/stream"],
    ["advanceWithoutEdict", "/api/decree/advance_without_edict"],
  ] as const)("%s 留在账本核账态而非按完成 reload", async (action, path) => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });
    const loadState = vi.fn(async () => settlingState);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url !== path) throw new Error(`unexpected fetch: ${url}`);
      return action === "advanceWithoutEdict"
        ? new Response(JSON.stringify({ advanced: false, state: settlingState }))
        : sseUnadvancedResponse();
    }));
    const { host, hookRef, cleanup } = mountHarness({
      loadState,
      initial: action === "submitDecisions" ? awaitingState : preClickState,
    });

    await act(async () => {
      if (action === "submitDecisions") await hookRef.current!.submitDecisions([]);
      else await hookRef.current![action]();
    });

    expect(loadState).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
    expect(host.querySelector('[data-testid="phase"]')?.textContent).toBe("settling");
    expect(host.querySelector('[data-testid="busy"]')?.textContent).toBe("");
    cleanup();
  });
```

## [158] web/src/useSettlementFlow.test.tsx:631 `"#1852 写成即推进：本面邸报阅读态，不整页 reload" / "%s advanced 终包：loadState + 阅读态，朕知道了只关阅读"`
flags=['web_calls_without_ui_token'] lines=39
```
  it.each([
    ["issueDecree", "/api/decree/issue/stream"],
    ["submitDecisions", "/api/decree/resolve_decisions/stream"],
  ] as const)("%s advanced 终包：loadState + 阅读态，朕知道了只关阅读", async (action, path) => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });
    const loadState = vi.fn(async () => advancedMonthState);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url !== path) throw new Error(`unexpected fetch: ${url}`);
      return sseAdvancedResponse("十月邸报·流终");
    }));
    const { host, hookRef, cleanup } = mountHarness({
      loadState,
      initial: action === "submitDecisions" ? awaitingState : preClickState,
    });

    await act(async () => {
      if (action === "submitDecisions") await hookRef.current!.submitDecisions([]);
      else await hookRef.current!.issueDecree();
    });

    expect(loadState).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
    expect(host.querySelector('[data-testid="busy"]')?.textContent).toBe("");
    expect(hookRef.current!.settlementGazetteReading?.report).toBe("十月邸报·流终");
    expect(hookRef.current!.settlementGazetteReading?.periodLabel).toBe("天启七年十月");
    expect(hookRef.current!.settlementGazetteReading?.attendantMessage).toBe("奴婢呈上月邸报。");

    act(() => {
      hookRef.current!.dismissSettlementGazette();
    });
    expect(hookRef.current!.settlementGazetteReading).toBeNull();
    expect(host.querySelector('[data-testid="phase"]')?.textContent).toBe("player");
    expect(reload).not.toHaveBeenCalled();
    cleanup();
  });
```

## [159] web/src/useSettlementFlow.test.tsx:671 `"#1852 写成即推进：本面邸报阅读态，不整页 reload" / "advanceWithoutEdict advanced：从 state 投影开阅读态，不 reload"`
flags=['web_calls_without_ui_token'] lines=25
```
  it("advanceWithoutEdict advanced：从 state 投影开阅读态，不 reload", async () => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });
    const loadState = vi.fn(async () => advancedMonthState);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url !== "/api/decree/advance_without_edict") throw new Error(`unexpected fetch: ${url}`);
      return new Response(JSON.stringify({
        advanced: true,
        state: advancedMonthState,
      }));
    }));
    const { hookRef, cleanup } = mountHarness({ loadState, initial: preClickState });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(reload).not.toHaveBeenCalled();
    expect(loadState).toHaveBeenCalled();
    expect(hookRef.current!.settlementGazetteReading?.report).toBe("十月邸报·已归档");
    cleanup();
  });
```

## [160] web/src/useSettlementFlow.test.tsx:697 `"#1852 写成即推进：本面邸报阅读态，不整页 reload" / "退局后迟到的新月刷新不得重挂上一局邸报"`
flags=['web_calls_without_ui_token'] lines=14
```
  it("退局后迟到的新月刷新不得重挂上一局邸报", async () => {
    let finishRefresh!: (state: GameState) => void;
    const loadState = vi.fn(() => new Promise<GameState>((resolve) => { finishRefresh = resolve; }));
    vi.stubGlobal("fetch", vi.fn(async () => sseAdvancedResponse("旧局邸报")));
    const { hookRef, cleanup } = mountHarness({ loadState });
    let issuing!: Promise<void>;
    await act(async () => { issuing = hookRef.current!.issueDecree(); });
    expect(loadState).toHaveBeenCalledTimes(1);
    await act(async () => hookRef.current!.clearSettlementHudError());
    await act(async () => { finishRefresh(advancedMonthState); await issuing; });
    expect(hookRef.current!.settlementGazetteReading).toBeNull();
    expect(hookRef.current!.suppressPostAdvanceOverlays).toBe(false);
    cleanup();
  });
```
