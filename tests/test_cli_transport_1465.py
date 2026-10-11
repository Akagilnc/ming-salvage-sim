"""#1465 切片③：CLI runner 真实入口走统一 transport。

真实缝 = HTTP `POST /api/audience/chat/stream`（channel="cli"，model 真是
`CliChat`，只把子进程换成脚本替身）。断言只落结构化字段：transport_attempts /
code / outcome / message_id / 夜未封 / 子进程调用次数。受控时钟，不跑真墙钟。
"""

from __future__ import annotations
