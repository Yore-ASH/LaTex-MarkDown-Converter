"""KaTeX 静态资源内嵌。

把 ``tools/katex`` 下的 KaTeX 样式与字体读进内存，转成可直接写进 HTML 的
自包含样式块（字体以 data URI 形式内嵌），这样生成的 HTML 断网也能正常显示公式。
"""

from __future__ import annotations

import base64
import functools
import re
from pathlib import Path

# url(fonts/xxx.woff2) / url("fonts/xxx.woff2") / url(fonts/xxx.ttf)
_FONT_URL = re.compile(r"""url\(\s*['"]?([^'")]+?\.(?:woff2|woff|ttf))['"]?\s*\)""")
# @font-face 块，便于整块丢弃不需要的格式
_FONT_FACE = re.compile(r"@font-face\s*\{.*?\}", re.DOTALL)

_MIME = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
}

# 同一进程内只做一次，KaTeX 样式内嵌字体后约 350 KB
_CACHE: dict[str, str] = {}

# 现代浏览器都支持 woff2，为了控制体积只内嵌 woff2
_PREFERRED = "woff2"


class AssetError(RuntimeError):
    """KaTeX 资源缺失。"""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def find_katex_dir(extra_hint: str | Path | None = None) -> Path | None:
    """定位包含 katex.min.css 的目录。"""
    candidates: list[Path] = []
    if extra_hint:
        candidates.append(Path(extra_hint))

    root = project_root()
    candidates.append(root / "tools" / "katex" / "node_modules" / "katex" / "dist")

    for base in (root, root / "tools" / "katex"):
        for pattern in ("**/katex.min.css", "**/katex.css"):
            try:
                candidates.extend(sorted(base.glob(pattern)))
            except OSError:
                continue

    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and path.name.endswith(".css"):
            return path.parent
        if (path / "katex.min.css").is_file():
            return path
        if (path / "katex.css").is_file():
            return path
    return None


def katex_script_path(katex_dir: Path) -> Path | None:
    for name in ("katex.min.js", "katex.js"):
        path = katex_dir / name
        if path.is_file():
            return path
    return None


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise AssetError(f"无法解码文件：{path}")


@functools.lru_cache(maxsize=4)
def embedded_katex_css(katex_dir_str: str) -> str:
    """返回把字体内嵌为 data URI 的 KaTeX 样式。

    只内嵌 woff2：体积最小，且所有现代浏览器都支持，
    因此不需要同时带上 woff / ttf 两套备份。
    """
    if katex_dir_str in _CACHE:
        return _CACHE[katex_dir_str]

    katex_dir = Path(katex_dir_str)
    css_path = katex_dir / "katex.min.css"
    if not css_path.is_file():
        css_path = katex_dir / "katex.css"
    if not css_path.is_file():
        raise AssetError(f"未找到 KaTeX 样式文件：{katex_dir}")

    css = _read_text(css_path)
    css = _drop_legacy_font_formats(css)
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        relative = match.group(1)
        if relative.startswith("data:"):
            return match.group(0)
        font_path = (katex_dir / relative).resolve()
        if not font_path.is_file():
            missing.append(relative)
            return match.group(0)
        mime = _MIME.get(font_path.suffix.lower(), "application/octet-stream")
        payload = base64.b64encode(font_path.read_bytes()).decode("ascii")
        return f"url(data:{mime};base64,{payload})"

    css = _FONT_URL.sub(replace, css)
    if missing:
        # 缺字体不影响排版主流程，调用方自行决定是否提示
        pass

    _CACHE[katex_dir_str] = css
    return css


def _drop_legacy_font_formats(css: str) -> str:
    """丢掉同时提供 woff2 的 woff / ttf 声明，避免重复内嵌同一字体。"""

    def clean(block: str) -> str:
        if ".woff2" not in block:
            return block
        return re.sub(
            r",\s*url\([^)]*\.(?:woff|ttf)[^)]*\)\s*format\([^)]*\)", "", block
        )

    return _FONT_FACE.sub(lambda m: clean(m.group(0)), css)


def katex_css_size(katex_dir: Path) -> int:
    """内嵌字体的样式大小，供展示与排查用。"""
    try:
        return len(embedded_katex_css(str(katex_dir)).encode("utf-8"))
    except AssetError:
        return 0
