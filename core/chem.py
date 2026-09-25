"""结构式渲染：把 SMILES 画成骨架式（键线式）。

两种用法：

* 块级：`` ```smiles `` 围栏代码块，整段作为一张图；
* 行内：``\\smiles{CC(=O)O}``。

渲染在转换阶段完成，结果为真 SVG（可离线、可缩放），
也可以选 PNG 以方便插入 Word。
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

_FENCE_OPEN = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>smiles-png|smiles)(?![-\w])(?P<extra>[^\n]*)$"
)
# 收尾行只能是纯围栏，不能带 info string，
# 否则会把下一个代码块的开头当成上一个的结尾
_FENCE_CLOSE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*$")
_INLINE = re.compile(r"\\smiles\{([^{}]*)\}")

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DEFAULT_BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

# 去掉 SVG 里的随机 id，避免同页多张图互相串用渐变/遮罩
_ID_ATTR = re.compile(r"""\bid\s*=\s*"([^"]*)\"""")
_URL_REF = re.compile(r"""url\(#([^)]*)\)""")
_HREF_REF = re.compile(r"""((?:xlink:)?href\s*=\s*")#([^"]*)\"""")


class ChemUnavailable(RuntimeError):
    """结构式渲染环境不完整。"""


def find_browser() -> str | None:
    """定位可用于无头渲染的浏览器。"""
    env_browser = os.environ.get("MDCONV_BROWSER")
    if env_browser and Path(env_browser).is_file():
        return env_browser
    for candidate in DEFAULT_BROWSERS:
        if Path(candidate).is_file():
            return candidate
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def bridge_script() -> Path:
    return Path(__file__).resolve().parent.parent / "tools" / "chem" / "render.js"


def _sanitize_svg(svg: str) -> str:
    """给 SVG 内部 id 统一加前缀，避免多图同页时互相干扰。"""
    ids = {match.group(1) for match in _ID_ATTR.finditer(svg)}
    ids = {value for value in ids if value}
    if not ids:
        return svg

    prefix = "c" + hashlib.md5(svg.encode("utf-8")).hexdigest()[:6] + "-"
    for identifier in sorted(ids, key=len, reverse=True):
        svg = re.sub(
            rf'(?<=id="){re.escape(identifier)}(?=")', prefix + identifier, svg
        )
        svg = _URL_REF.sub(
            lambda m: f"url(#{prefix}{m.group(1)})" if m.group(1) in ids else m.group(0),
            svg,
        )
        svg = _HREF_REF.sub(
            lambda m: f"{m.group(1)}#{prefix}{m.group(2)}" if m.group(2) in ids else m.group(0),
            svg,
        )
    return svg


class ChemRenderer:
    """常驻 Node 渲染进程的封装（每个线程一份）。"""

    BATCH_SIZE = 60

    def __init__(self, browser: str | None = None, enabled: bool = True):
        self.browser = browser or find_browser()
        self.script = bridge_script()
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._counter = 0
        self._available = False
        self.unavailable_reason = ""

        if not enabled:
            self.unavailable_reason = "本机未启用结构式渲染"
            return
        if not self.browser:
            self.unavailable_reason = "未找到 Edge / Chrome，无法渲染结构式"
            return
        if not self.script.is_file():
            self.unavailable_reason = f"缺少渲染脚本：{self.script}"
            return
        if not (self.script.parent / "node_modules" / "smiles-drawer").is_dir():
            self.unavailable_reason = "未安装 smiles-drawer，请在 tools/chem 下执行 npm install"
            return
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process

        env = dict(os.environ)
        env["MDCONV_BROWSER"] = self.browser or ""
        self._process = subprocess.Popen(
            ["node", str(self.script)],
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
        handshake = self._process.stdout.readline() if self._process.stdout else ""
        if not handshake:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            self._available = False
            self.unavailable_reason = f"渲染子进程启动失败：{stderr.strip()[:200]}"
            self._terminate()
            raise ChemUnavailable(self.unavailable_reason)
        return self._process

    def _terminate(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        finally:
            # 关掉管道，避免解释器退出时报未关闭文件的警告
            for stream in (process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            self._terminate()

    def __enter__(self) -> "ChemRenderer":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def render_many(self, requests: list[dict]) -> list[dict]:
        """批量渲染，返回与 requests 等长的结果列表。"""
        if not requests:
            return []
        results: list[dict] = []
        for start in range(0, len(requests), self.BATCH_SIZE):
            chunk = requests[start : start + self.BATCH_SIZE]
            with self._lock:
                results.extend(self._render_locked(chunk))
        return results

    def _render_locked(self, requests: list[dict]) -> list[dict]:
        failure = {"error": self.unavailable_reason or "渲染不可用"}
        try:
            process = self._ensure_process()
        except ChemUnavailable as exc:
            return [{**failure, "error": str(exc)} for _ in requests]

        assert process.stdin is not None and process.stdout is not None

        import json

        positions: dict[int, int] = {}
        payloads: list[str] = []
        for index, request in enumerate(requests):
            self._counter += 1
            request_id = self._counter
            positions[request_id] = index
            payloads.append(
                json.dumps({"id": request_id, **request}, ensure_ascii=False)
            )

        try:
            process.stdin.write("\n".join(payloads) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            self._available = False
            self.unavailable_reason = f"写入渲染进程失败：{exc}"
            return [{**failure, "error": self.unavailable_reason} for _ in requests]

        results: list[dict] = [dict(failure) for _ in requests]
        pending = set(positions)
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
                data = json.loads(line)
            except ValueError:
                continue
            request_id = data.get("id")
            if request_id in pending:
                pending.discard(request_id)
                results[positions[request_id]] = data

        for request_id in pending:
            results[positions[request_id]] = {
                "error": self.unavailable_reason or "渲染进程无响应"
            }
        return results


def _inside_code_span(text: str, position: int) -> bool:
    """判断 position 是否落在反引号代码段内部。

    代码段可以跨行，但实际写作里几乎不会，这里按整篇文本统计反引号即可。
    """
    line_start = text.rfind("\n", 0, position) + 1
    return text.count("`", line_start, position) % 2 == 1


def _figure(svg: str, caption: str, name: str) -> str:
    cap = f"\n  <figcaption>{html.escape(caption)}</figcaption>" if caption else ""
    return (
        f'<figure class="chem-figure" data-smiles="{html.escape(name, quote=True)}">\n'
        f"  {svg}{cap}\n"
        f"</figure>"
    )


def _inline(svg: str, name: str) -> str:
    return (
        f'<span class="chem-inline" data-smiles="{html.escape(name, quote=True)}">'
        f"{svg}</span>"
    )


def preprocess_structures(
    text: str,
    renderer: ChemRenderer | None,
    image_dir: Path | None = None,
    logger=None,
) -> tuple[str, list[tuple[str, str]]]:
    """把 SMILES 代码块与 ``\\smiles{}`` 换成渲染结果。

    返回 (处理后的文本, [(token, 替换片段)])。
    渲染不可用时退回显示 SMILES 原文，不打断整篇转换。
    """
    entries: list[tuple[str, str]] = []
    counters = {"svg": 0, "png": 0, "raw": 0}

    def next_token(kind: str) -> str:
        counters[kind] += 1
        return f"\x00CHEM{kind.upper()}{counters[kind]}\x00"

    def note(message: str, level: str = "warning") -> None:
        if logger:
            logger(message, level)

    if not text or ("smiles" not in text and "\\smiles{" not in text):
        return text, entries

    available = renderer is not None and renderer.available
    if not available and (renderer is not None or "smiles" in text):
        note(
            (renderer.unavailable_reason if renderer else "未启用结构式渲染")
            + "，SMILES 将按原文显示",
            "warning",
        )

    # ---- 收集所有请求 ----
    # 逐行扫描围栏块：正则跨越两个代码块会把中间的内容一起吞掉，
    # 也会把代码段里的 \smiles{} 示例误当成真实调用。
    blocks: list[tuple[int, int, str, str, str]] = []  # (起点, 终点, SMILES, 图注, 模式)
    lines = text.split("\n")
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1

    index = 0
    while index < len(lines):
        opening = _FENCE_OPEN.match(lines[index])
        if not opening:
            index += 1
            continue

        fence = opening.group("fence")
        mode = "png" if opening.group("info") == "smiles-png" else "svg"
        caption = opening.group("extra").strip().lstrip("#").strip()

        closing = None
        for probe in range(index + 1, len(lines)):
            candidate = _FENCE_CLOSE.match(lines[probe])
            if candidate and candidate.group("fence")[0] == fence[0] and len(
                candidate.group("fence")
            ) >= len(fence):
                closing = probe
                break

        if closing is None:
            index += 1
            continue

        body = "\n".join(lines[index + 1 : closing]).strip()
        start = offsets[index]
        end = offsets[closing] + len(lines[closing])
        if body:
            blocks.append((start, end, body, caption, mode))
        index = closing + 1

    inline_hits: list[tuple[int, int, str]] = []
    pending: list[dict] = []

    for _, _, smiles, _, mode in blocks:
        pending.append({"smiles": smiles, "mode": mode, "scale": 3})
    for match in _INLINE.finditer(text):
        smiles = match.group(1).strip()
        # 写在代码段里的 `\smiles{...}` 是在讲语法，不是真要画图
        if smiles and not _inside_code_span(text, match.start()):
            pending.append({"smiles": smiles, "mode": "svg"})
            inline_hits.append((match.start(), match.end(), smiles))

    if not pending:
        return text, entries

    if available:
        assert renderer is not None
        results = renderer.render_many(pending)
    else:
        results = [{"error": renderer.unavailable_reason if renderer else "结构式渲染不可用"} for _ in pending]

    # ---- 生成块级替换 ----
    block_replacements: list[tuple[int, int, str]] = []
    for order, (start, end, smiles, caption, _) in enumerate(blocks):
        data = results[order]
        if data.get("svg"):
            token = next_token("svg")
            payload = _figure(_sanitize_svg(data["svg"]), caption, smiles)
        elif data.get("png") and image_dir is not None:
            token = next_token("png")
            payload = _figure(_write_png(data, smiles, caption, image_dir), caption, smiles)
        else:
            note(f"结构式渲染失败：{data.get('error')}（{smiles[:60]}）")
            token = next_token("raw")
            payload = f'<pre class="chem-raw"><code>{html.escape(smiles)}</code></pre>'
        entries.append((token, payload))
        block_replacements.append((start, end, token))

    for start, end, token in sorted(block_replacements, reverse=True):
        text = text[:start] + token + text[end:]

    # ---- 生成行内替换 ----
    # 块级替换改变了长度，行内偏移已经失效，所以用占位符整体拼接
    inline_payloads: list[str] = []
    for order, (_, _, smiles) in enumerate(inline_hits):
        data = results[len(blocks) + order]
        if data.get("svg"):
            inline_payloads.append(_inline(_sanitize_svg(data["svg"]), smiles))
        else:
            note(f"结构式渲染失败：{data.get('error')}（{smiles[:60]}）")
            inline_payloads.append(f'<code class="chem-raw">{html.escape(smiles)}</code>')

    for order, payload in enumerate(inline_payloads):
        entries.append((f"\x00CHEMINLINE{order + 1}\x00", payload))

    cursor = 0
    pieces: list[str] = []
    for order, (start, end, _) in enumerate(inline_hits):
        pieces.append(text[cursor:start])
        pieces.append(f"\x00CHEMINLINE{order + 1}\x00")
        cursor = end
    pieces.append(text[cursor:])
    text = "".join(pieces)
    return text, entries


def _write_png(data: dict, smiles: str, caption: str, image_dir: Path) -> str:
    """把 PNG 落到磁盘，返回可直接内嵌的 img 标签。"""
    image_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", caption or smiles)[:40].strip("-") or "structure"
    digest = hashlib.md5(smiles.encode("utf-8")).hexdigest()[:8]
    filename = f"{stem}-{digest}.png"
    target = image_dir / filename
    if not target.is_file():
        target.write_bytes(base64.b64decode(data["png"]))
    width = data.get("width") or 0
    height = data.get("height") or 0
    size = f' width="{width}" height="{height}"' if width and height else ""
    return f'<img class="chem-png" src="{html.escape(filename)}"{size} alt="{html.escape(caption or smiles)}">'


def check_environment() -> tuple[bool, str]:
    """供界面自检使用。"""
    renderer = ChemRenderer()
    if not renderer.available:
        return False, renderer.unavailable_reason
    renderer.close()
    return True, ""
