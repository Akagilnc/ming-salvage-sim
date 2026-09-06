"""#1465 切片③：CLI 子进程替身（禁起真 CLI 进程）。

生产读法 = `Popen` + 增量读 stdout（新字节刷新活动时刻，不设总墙钟）。
本替身按脚本吐 stdout 行 / stderr 文本 / 退出码，可挂受控钩子推进注入时钟或
阻塞成静默，供「持续出字跨旧 300s 不被杀」「静默超阈值判死」等契约用。
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

class SilentUntilKilled:
    """脚本哨兵：此处只静默、不出字，直到子进程被 kill（模拟挂死）。

    on_tick：每轮推进注入时钟，使「静默超阈值判死」在受控时钟下确定性成立
    （不靠真墙钟、不靠线程调度巧合）。
    """

    def __init__(
        self,
        on_tick: Optional[Callable[[], None]] = None,
        interval: float = 0.01,
    ) -> None:
        self.on_tick = on_tick
        self.interval = float(interval)


# 脚本项：str = 一行 stdout；callable = 钩子（返回 str 则当行，返回 None 则跳过）；
# SilentUntilKilled = 静默到被 kill
ScriptItem = Union[str, Callable[[], Optional[str]], SilentUntilKilled]


class _FakeStdin:
    """stdin 管道替身；`error` 注入写失败（子进程根本没拿到 prompt 的真实形状）。"""

    def __init__(self, error: Optional[BaseException] = None) -> None:
        self.written: List[str] = []
        self.closed = False
        self.error = error

    def write(self, text: str) -> int:
        if self.error is not None:
            raise self.error
        self.written.append(str(text))
        return len(str(text))

    def close(self) -> None:
        self.closed = True


class _ScriptedStream:
    """按脚本产行的管道替身；被 kill 后立刻断流（模拟 EOF）。"""

    def __init__(self, script: Sequence[ScriptItem], killed: threading.Event) -> None:
        self._script = list(script)
        self._killed = killed
        self.exhausted = False
        self.closed = False

    def __iter__(self):
        try:
            for item in self._script:
                if self._killed.is_set():
                    break
                if isinstance(item, SilentUntilKilled):
                    while not self._killed.wait(item.interval):
                        if item.on_tick is not None:
                            item.on_tick()
                    break
                if callable(item):
                    produced = item()
                    if produced is None:
                        continue
                    item = produced
                yield str(item)
        finally:
            self.exhausted = True

    def read(self) -> str:
        return "".join(
            str(x) for x in self._script
            if not callable(x) and not isinstance(x, SilentUntilKilled)
        )

    def close(self) -> None:
        self.closed = True


class FakeCliProcess:
    """`subprocess.Popen` 替身：只实现生产读取契约用到的面。"""

    def __init__(
        self,
        cmd: Optional[Sequence[str]] = None,
        *,
        stdout_script: Sequence[ScriptItem] = (),
        stderr_script: Sequence[ScriptItem] = (),
        returncode: int = 0,
        popen_kwargs: Optional[Dict[str, Any]] = None,
        stdin_error: Optional[BaseException] = None,
    ) -> None:
        self.cmd = list(cmd or [])
        self.popen_kwargs = dict(popen_kwargs or {})
        self.killed = threading.Event()
        self.terminated = False
        self.stdin = _FakeStdin(stdin_error)
        self.stdout = _ScriptedStream(stdout_script, self.killed)
        self.stderr = _ScriptedStream(stderr_script, self.killed)
        self._exit_code = int(returncode)
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self.returncode is not None:
            return self.returncode
        if self.stdout.exhausted and self.stderr.exhausted:
            self.returncode = self._exit_code
        elif self.killed.is_set():
            self.returncode = -9
        return self.returncode

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        return self.poll()

    def terminate(self) -> None:
        # 真 subprocess 对已退进程 terminate 是 no-op：退出码不得被收尾动作改写。
        self.terminated = True
        if self.poll() is None:
            self.killed.set()

    def kill(self) -> None:
        if self.poll() is None:
            self.killed.set()


class FakeCliRunnerScript:
    """按调用序发子进程替身；记录每次 argv/stdin，供「调用次数=N」断言。"""

    def __init__(self, runs: Sequence[Dict[str, Any]]) -> None:
        self._runs = list(runs)
        self.processes: List[FakeCliProcess] = []
        self.commands: List[List[str]] = []
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        return len(self.processes)

    def popen(self, cmd, **kwargs) -> FakeCliProcess:
        with self._lock:
            index = len(self.processes)
            spec = self._runs[min(index, len(self._runs) - 1)]
            proc = FakeCliProcess(
                cmd,
                stdout_script=spec.get("stdout", ()),
                stderr_script=spec.get("stderr", ()),
                returncode=int(spec.get("returncode", 0)),
                popen_kwargs=kwargs,
                stdin_error=spec.get("stdin_error"),
            )
            self.processes.append(proc)
            self.commands.append(list(cmd))
        return proc


def install_fake_cli_runner(monkeypatch, runs: Sequence[Dict[str, Any]]) -> FakeCliRunnerScript:
    """把 cli_backend 的子进程边界换成脚本替身（不起真 CLI）。"""
    import ming_sim.cli_backend as cb

    script = FakeCliRunnerScript(runs)
    monkeypatch.setattr(cb.subprocess, "Popen", script.popen)
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured: f"/fake/{name}")
    monkeypatch.setattr(cb, "_warm_keychain", lambda: None)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    return script
