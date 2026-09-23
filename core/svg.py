"""SVG 内嵌：把 ``![alt](x.svg)`` 变成真正的内联矢量图。

相比旧实现只靠 ``src="..."`` 反查，这里会正确解析 HTML 属性（单引号、实体编码、
URL 编码、``?query#fragment`` 后缀），并且：
* 剥离 SVG 内的脚本与外部事件属性，避免生成的独立 HTML 带安全隐患；
* 补上自适应尺寸样式，避免超宽图形撑破版面；
* 对同一文档内重复出现的 id 做加前缀处理，避免多个 SVG 互相干扰。
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

_IMG_TAG = re.compile(r"<img\b[^>]*?/?>", re.IGNORECASE)
_ATTR = re.compile(
    r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
)
_SVG_TAG = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_XML_DECL = re.compile(r"<\?xml[^>]*\?>", re.IGNORECASE)
_DOCTYPE = re.compile(r"<!DOCTYPE[^>[]*(\[[^]]*\])?[^>]*>", re.IGNORECASE)
_SCRIPT_BLOCK = re.compile(r"<script\b.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_EVENT_ATTR = re.compile(r"""\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*')""", re.IGNORECASE)
_HREF_JS = re.compile(r"""\s(?:xlink:)?href\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')""", re.IGNORECASE)
_ID_ATTR = re.compile(r"""\bid\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_URL_REF = re.compile(r"""url\(\s*(['"]?)#([^)'"\s]+)\1\s*\)""")
_HREF_REF = re.compile(r"""((?:xlink:)?href\s*=\s*)(["'])#([^"']+)\2""")


@dataclass
class SvgEmbedReport:
    embedded: int = 0
    skipped: int = 0
    missing: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.missing is None:
            self.missing = []


def parse_attributes(tag: str) -> dict[str, str]:
    """解析 HTML/SVG 标签里的属性，键统一小写。"""
    attributes: dict[str, str] = {}
    for match in _ATTR.finditer(tag):
        name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3) or ""
        attributes[name] = html.unescape(value)
    return attributes


def resolve_svg_path(src: str, search_dirs: list[Path]) -> Path | None:
    """把 Markdown 里的图片地址解析为本地 SVG 路径。"""
    raw = src.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        return None  # 远程地址不做内嵌

    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme not in ("", "file"):
        return None

    path_part = unquote(parsed.path if parsed.scheme else raw.split("?", 1)[0].split("#", 1)[0])
    path_part = unquote(path_part)
    if not path_part.lower().endswith(".svg"):
        return None

    candidate = Path(path_part)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None

    for directory in search_dirs:
        resolved = (directory / candidate).resolve()
        if resolved.is_file():
            return resolved
    return None


def _read_svg(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def sanitize_svg(content: str) -> str:
    """去掉脚本、事件属性等会破坏独立 HTML 的内容。"""
    content = _XML_DECL.sub("", content)
    content = _DOCTYPE.sub("", content)
    content = _SCRIPT_BLOCK.sub("", content)
    content = _EVENT_ATTR.sub("", content)
    content = _HREF_JS.sub("", content)
    return content.strip()


def _prefix_ids(content: str, prefix: str) -> str:
    """给 SVG 内部 id 及其引用加前缀，避免同页多个 SVG 冲突。"""
    ids = {
        (match.group(1) if match.group(1) is not None else match.group(2) or "")
        for match in _ID_ATTR.finditer(content)
    }
    ids.discard("")
    if not ids:
        return content

    content = _ID_ATTR.sub(
        lambda m: f'id="{prefix}{m.group(1) if m.group(1) is not None else m.group(2)}"',
        content,
    )
    content = _URL_REF.sub(lambda m: f"url(#{prefix}{m.group(2)})", content)
    content = _HREF_REF.sub(lambda m: f"{m.group(1)}{m.group(2)}#{prefix}{m.group(3)}{m.group(2)}", content)
    return content


def _make_responsive(svg_tag: str) -> str:
    """让 SVG 在容器内自适应，同时保留原始宽高比。"""
    attributes = parse_attributes(svg_tag)
    style = attributes.get("style", "").strip()
    additions = ["max-width:100%", "height:auto"]
    if not attributes.get("viewbox") and not attributes.get("preserveaspectratio"):
        additions = ["max-width:100%"]
    for rule in additions:
        if rule.split(":")[0] not in style:
            style = f"{style};{rule}" if style else rule
    tag = re.sub(r"""\sstyle\s*=\s*(?:"[^"]*"|'[^']*')""", "", svg_tag, flags=re.IGNORECASE)
    return tag[:-1].rstrip() + f' style="{style}">'


def embed_svg_images(
    html_content: str,
    markdown_path: Path | None,
    output_dir: Path | None,
    enabled: bool = True,
    logger=None,
) -> tuple[str, SvgEmbedReport]:
    """把 HTML 中的 ``<img>`` SVG 引用替换为内联图形。"""
    report = SvgEmbedReport()
    if not enabled:
        return html_content, report

    search_dirs: list[Path] = []
    for directory in (markdown_path.parent if markdown_path else None, output_dir):
        if directory is not None and directory not in search_dirs:
            search_dirs.append(directory)

    counter = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal counter
        tag = match.group(0)
        attributes = parse_attributes(tag)
        src = attributes.get("src", "")
        if not src or not src.split("?")[0].split("#")[0].lower().endswith(".svg"):
            return tag

        svg_path = resolve_svg_path(src, search_dirs)
        if svg_path is None:
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", src) is None:
                report.missing.append(src)
                if logger:
                    logger(f"SVG 未找到，保留原始引用：{src}", "warning")
            return tag

        try:
            content = _read_svg(svg_path)
        except OSError as exc:
            report.missing.append(src)
            if logger:
                logger(f"SVG 读取失败：{src}（{exc}）", "warning")
            return tag

        content = sanitize_svg(content)
        svg_tag_match = _SVG_TAG.search(content)
        if not svg_tag_match:
            if logger:
                logger(f"文件不含 <svg> 根元素，已跳过：{svg_path.name}", "warning")
            return tag

        caption = attributes.get("alt") or attributes.get("title") or svg_path.stem

        counter += 1
        content = _prefix_ids(content, f"svg{counter}-")
        content = _SVG_TAG.sub(lambda m: _make_responsive(m.group(0)), content, count=1)

        report.embedded += 1
        escaped_caption = html.escape(caption)
        return (
            f'<figure class="svg-figure">\n'
            f"{content}\n"
            f"  <figcaption>{escaped_caption}</figcaption>\n"
            f"</figure>"
        )

    html_content = _IMG_TAG.sub(replace, html_content)
    report.skipped = len(report.missing)
    return html_content, report
