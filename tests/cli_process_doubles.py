"""#1465 切片③：CLI 子进程替身（禁起真 CLI 进程）。

生产读法 = `Popen` + 增量读 stdout（新字节刷新活动时刻，不设总墙钟）。
本替身按脚本吐 stdout/stderr **字节块**（不必带换行）与退出码，可挂受控钩子
推进注入时钟或阻塞成静默，供「持续出字跨旧 300s 不被杀」「无换行长单行不判死」
「静默超阈值判死」等契约用。
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


# 脚本项：str/bytes = 一块 stdout（可无换行）；callable = 钩子（返回块则交付，None 跳过）；
# SilentUntilKilled = 静默到被 kill
ScriptItem = Union[str, bytes, Callable[[], Optional[Union[str, bytes]]], SilentUntilKilled]


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
    """按脚本产字节块的管道替身；被 kill 后立刻断流（模拟 EOF）。"""

    def __init__(self, script: Sequence[ScriptItem], killed: threading.Event) -> None:
        self._script = list(script)
        self._index = 0
        self._killed = killed
        self.exhausted = False
        self.closed = False

    def _as_bytes(self, item: Union[str, bytes]) -> bytes:
        if isinstance(item, bytes):
            return item
        return str(item).encode("utf-8")

    def _next_chunk(self) -> bytes:
        if self.closed or self._killed.is_set():
            self.exhausted = True
            return b""
        while self._index < len(self._script):
            if self._killed.is_set():
                self.exhausted = True
                return b""
            item = self._script[self._index]
            self._index += 1
            if isinstance(item, SilentUntilKilled):
                while not self._killed.wait(item.interval):
                    if item.on_tick is not None:
                        item.on_tick()
                self.exhausted = True
                return b""
            if callable(item):
                produced = item()
                if produced is None:
                    continue
                item = produced
            return self._as_bytes(item)
        self.exhausted = True
        return b""

    def read1(self, size: int = 4096) -> bytes:
        return self._next_chunk()

    def __iter__(self):
        # 与真 text 流 readline 同形：无换行不交付；EOF 才吐剩余半行。
        # 生产读法走 read1（按块），不得靠本迭代把无换行块伪装成行。
        try:
            buf = ""
            while True:
                chunk = self._next_chunk()
                if not chunk:
                    if buf:
                        yield buf
                    break
                buf += chunk.decode("utf-8")
                while True:
                    nl = buf.find("\n")
                    if nl < 0:
                        break
                    line, buf = buf[: nl + 1], buf[nl + 1 :]
                    yield line
        finally:
            self.exhausted = True

    def read(self, size: int = -1) -> bytes:
        if size is not None and size >= 0:
            return self._next_chunk()
        parts = []
        while True:
            chunk = self._next_chunk()
            if not chunk:
                break
            parts.append(chunk)
        return b"".join(parts)

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
