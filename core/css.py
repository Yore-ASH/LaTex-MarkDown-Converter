"""样式表读取。

仓库里的样式表有的保存为 GB18030，直接按 UTF-8 打开会产生乱码，
这里做编码嗅探，保证取到的是可读的 CSS。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1")
_VERSION = re.compile(r"Version\s*[:：]\s*([0-9][0-9A-Za-z.\-]*)")
_WIDTH = re.compile(r"--md-width\s*:\s*([0-9.]+)(px|rem|em|%)?")
_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Theme:
    """一个可选样式表。"""

    path: Path
    group: str
    stem: str
    version: str | None

    @property
    def label(self) -> str:
        version = self.version or self.stem.replace("-", ".")
        return f"{self.group} {version}".strip()


def read_css(path: Path) -> str:
    """按嗅探到的编码读取样式表，并去掉 BOM。"""
    for encoding in _ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise OSError(f"无法读取样式表 {path}：{exc}") from exc
        return text.replace("\ufeff", "")
    return path.read_text(encoding="utf-8", errors="replace")


def theme_version(css: str) -> str | None:
    match = _VERSION.search(css[:2000])
    return match.group(1) if match else None


def discover_themes(static_root: Path) -> list[Theme]:
    """扫描样式目录，按分组与版本倒序排列。"""
    themes: list[Theme] = []
    if not static_root.is_dir():
        return themes

    for path in sorted(static_root.rglob("*.css")):
        try:
            css = read_css(path)
        except OSError:
            continue
        themes.append(
            Theme(
                path=path,
                group=path.parent.name,
                stem=path.stem,
                version=theme_version(css),
            )
        )

    def sort_key(theme: Theme) -> tuple[str, list[int]]:
        numbers = [int(part) for part in re.findall(r"\d+", theme.version or theme.stem)]
        return theme.group, numbers

    themes.sort(key=sort_key, reverse=True)
    return themes


def default_theme(static_root: Path) -> Theme | None:
    themes = discover_themes(static_root)
    if not themes:
        return None
    for theme in themes:
        if theme.group == "NoteStyle":
            return theme
    return themes[0]


def extract_doc_width(css: str, fallback: str = "900px") -> str:
    """从样式表里读取文档宽度变量，用于给预览窗口一个合适的初始尺寸。"""
    match = _WIDTH.search(css)
    if not match:
        return fallback
    unit = match.group(2) or "px"
    return f"{match.group(1)}{unit}"


def extract_title(css: str) -> str | None:
    match = _TITLE.search(css)
    return match.group(1).strip() if match else None
