"""KaTeX 预渲染：在转换阶段就把公式渲染成 HTML，页面无需再执行脚本。

Python 侧通过 ``tools/katex/render.js`` 这个常驻子进程调用 KaTeX，
一次转换只启动一次 Node，批量提交公式。
Node 或 KaTeX 不可用时由调用方决定降级策略。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from .assets import find_katex_dir

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _trace(message: str) -> None:
    """设置 MDCONV_TRACE=1 时把渲染流程写进日志，便于排查卡顿。"""
    if os.environ.get("MDCONV_TRACE") != "1":
        return
    import time
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parent.parent / "_katex_trace.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.perf_counter():8.2f}  {message}\n")


class KatexUnavailable(RuntimeError):
    """找不到 Node 或 KaTeX 资源。"""


def find_node() -> str | None:
    """定位 node 可执行文件。"""
    env_node = os.environ.get("MDCONV_NODE")
    if env_node and Path(env_node).is_file():
        return env_node
    found = shutil.which("node")
    if found:
        return found
    for candidate in (
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def bridge_script() -> Path:
    return Path(__file__).resolve().parent.parent / "tools" / "katex" / "render.js"


class KatexRenderer:
    """常驻 Node 渲染进程的封装。

    线程安全：每个转换任务应各自持有实例（GUI 里在 worker 线程中创建）。
    """

    # 单次提交的公式条数上限，避免管道缓冲区写满导致死锁
    BATCH_SIZE = 200

    def __init__(self, node_path: str | None = None, katex_dir: Path | None = None):
        self.node = node_path or find_node()
        self.katex_dir = katex_dir or find_katex_dir()
        self.script = bridge_script()
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._counter = 0
        self._available = False
        self.unavailable_reason = ""

        if not self.node:
            self.unavailable_reason = "未找到 node，可执行文件不在 PATH 中"
            return
        if not self.script.is_file():
            self.unavailable_reason = f"缺少渲染脚本：{self.script}"
            return
        if self.katex_dir is None:
            self.unavailable_reason = "未找到 KaTeX 资源目录（tools/katex/node_modules/katex/dist）"
            return
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process

        env = dict(os.environ)
        # 让 render.js 里的 require('katex') 能解析到本地安装的副本
        module_root = self.katex_dir.parent.parent if self.katex_dir else None
        if module_root is not None:
            env["NODE_PATH"] = str(module_root)

        self._process = subprocess.Popen(
            [self.node or "node", str(self.script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(self.script.parent),
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
        # 首行握手：确认 katex 已加载
        handshake = self._process.stdout.readline() if self._process.stdout else ""
        if not handshake:
            stderr = ""
            if self._process.stderr:
                stderr = self._process.stderr.read()
            self._available = False
            self.unavailable_reason = f"渲染子进程启动失败：{stderr.strip()[:200]}"
            self._terminate()
            raise KatexUnavailable(self.unavailable_reason)
        return self._process

    def _terminate(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._terminate()

    def __enter__(self) -> "KatexRenderer":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def render_many(self, formulas: list[str], display: bool) -> list[tuple[str | None, str | None]]:
        """批量渲染，返回与 formulas 等长的 (html, error) 列表。

        分批提交：一次性写入上万条请求会写满管道缓冲区，
        子进程又会因为没人读它的输出而阻塞，最终互相等待。
        """
        if not formulas:
            return []
        results: list[tuple[str | None, str | None]] = []
        for start in range(0, len(formulas), self.BATCH_SIZE):
            chunk = formulas[start : start + self.BATCH_SIZE]
            with self._lock:
                results.extend(self._render_locked(chunk, display))
        return results

    def _render_locked(self, formulas: list[str], display: bool) -> list[tuple[str | None, str | None]]:
        results: list[tuple[str | None, str | None]] = [(None, "未渲染")] * len(formulas)
        _trace(f"需要启动子进程, {len(formulas)} 条 display={display}")
        try:
            process = self._ensure_process()
        except KatexUnavailable as exc:
            return [(None, str(exc))] * len(formulas)
        _trace("子进程就绪")

        assert process.stdin is not None and process.stdout is not None

        ids: list[int] = []
        positions: dict[int, int] = {}
        chunks: list[str] = []
        for index, tex in enumerate(formulas):
            self._counter += 1
            request_id = self._counter
            ids.append(request_id)
            positions[request_id] = index
            chunks.append(
                json.dumps(
                    {"id": request_id, "text": tex, "display": bool(display)},
                    ensure_ascii=False,
                )
            )

        # 一次性写入整批：逐行 write 在文本管道上会因缓冲区未刷新而阻塞
        payload = "\n".join(chunks) + "\n"
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            self._available = False
            self.unavailable_reason = f"写入渲染进程失败：{exc}"
            return [(None, self.unavailable_reason)] * len(formulas)
        _trace(f"写入 {len(formulas)} 条 / {len(payload)} 字节完成")

        pending = set(ids)
        while pending:
            line = process.stdout.readline()
            if not line:
                stderr = ""
                if process.stderr:
                    try:
                        stderr = process.stderr.read()
                    except Exception:
                        stderr = ""
                self._available = False
                self.unavailable_reason = f"渲染进程提前退出：{stderr.strip()[:200]}"
                break
            line = line.strip()
            if not line:
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = response.get("id")
            if request_id in pending:
                pending.discard(request_id)
                results[positions[request_id]] = (response.get("html"), response.get("error"))

        if pending:
            for request_id in pending:
                results[positions[request_id]] = (
                    None,
                    self.unavailable_reason or "渲染进程无响应",
                )
        return results


def create_renderer(prefer_node: bool = True) -> KatexRenderer:
    """构造渲染器；调用方需要自行判断 ``available``。"""
    return KatexRenderer(node_path=find_node() if prefer_node else None)


__all__ = ["KatexRenderer", "KatexUnavailable", "create_renderer", "find_node", "bridge_script"]
