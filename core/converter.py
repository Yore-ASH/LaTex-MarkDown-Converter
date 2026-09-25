"""Markdown → 单文件 HTML 转换引擎。

设计要点：
* 数学公式先被替换为占位符，Markdown 解析器完全看不到 ``$``，因此不会再出现
  ``<p><div>`` 这类非法嵌套、标题层级被打断、以及 LaTeX 源码裸露的问题；
* 公式在转换阶段由 KaTeX 预渲染成 HTML，生成的页面打开即正确，不依赖网络；
* 公式编号（``\\tag{}``）在 Python 侧解析并交给样式层呈现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import markdown

from .assets import find_katex_dir
from .chem import ChemRenderer, preprocess_structures
from .css import read_css
from .katex import KatexRenderer, KatexUnavailable
from . import mhchem_rules
from .math import normalize_newlines, protect_math, restore_math
from .svg import embed_svg_images
from .template import CLIENT_FALLBACK, build_document

EXTENSIONS = [
    "extra",
    "sane_lists",
    "codehilite",
    "toc",
    "fenced_code",
    "footnotes",
    "nl2br",
]

EXTENSION_CONFIGS = {
    "codehilite": {
        "guess_lang": False,
        "css_class": "highlight",
        "linenums": False,
    },
    "toc": {
        "permalink": False,
        "toc_depth": "1-6",
    },
}

FALLBACK_CSS = """
:root { --md-width: 900px; }
.markdown-body {
    max-width: var(--md-width);
    margin: 0 auto;
    padding: 40px 48px;
    font-family: "Times New Roman", "宋体", serif;
    font-size: 16px;
    line-height: 1.8;
    color: #1f1f1f;
}
.markdown-body pre {
    background: #f6f8fa;
    border: 1px solid #e1e4e8;
    border-radius: 4px;
    padding: 16px 20px;
    overflow-x: auto;
}
.markdown-body code {
    font-family: "Cascadia Code", Consolas, monospace;
}
.markdown-body table { border-collapse: collapse; width: 100%; }
.markdown-body th, .markdown-body td { border: 1px solid #d0d7de; padding: 8px 12px; }
.markdown-body .svg-figure { text-align: center; margin: 16px 0; }
.markdown-body .svg-figure svg { max-width: 100%; height: auto; }
.markdown-body .chem-figure { text-align: center; margin: 18px 0; }
.markdown-body .chem-figure svg { max-width: 100%; height: auto; }
.markdown-body .chem-inline svg { height: 1.5em; width: auto; vertical-align: -0.4em; }
.markdown-body .chem-figure figcaption { margin-top: 8px; font-size: 0.9em; color: #555; }
.markdown-body .chem-raw { color: #b42318; }
"""

# 存在无法预渲染的公式时插在页面顶部的提示，样式随主题走
FALLBACK_NOTICE = (
    '<div class="build-notice">'
    "本文档有 {count} 处公式未能渲染，已在原位置显示 LaTeX 写法，"
    "请检查这几处公式的语法。"
    "</div>"
)


@dataclass
class ConversionOptions:
    """一次转换的全部输入。"""

    source: Path
    output: Path | None = None
    css_path: Path | None = None
    embed_svg: bool = True
    embed_structures: bool = True
    document_title: str | None = None
    add_footer: bool = False
    add_toc: bool = False
    katex_dir: Path | None = None
    offline: bool = True


@dataclass
class ConversionResult:
    """转换产出与统计信息。"""

    output_path: Path
    html: str
    markdown_chars: int = 0
    html_chars: int = 0
    math_inline: int = 0
    math_display: int = 0
    math_failed: int = 0
    structures: int = 0
    svg_embedded: int = 0
    svg_missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration: float = 0.0


class ConversionEngine:
    """可复用的转换引擎（持有常驻 KaTeX 子进程）。

    实例不是线程安全的，请在每个工作线程里各自创建。
    """

    def __init__(
        self,
        katex_dir: Path | None = None,
        use_katex: bool = True,
        use_chem: bool = True,
        browser: str | None = None,
    ):
        self.katex_dir = katex_dir if katex_dir is not None else find_katex_dir()
        self._renderer: KatexRenderer | None = None
        self._renderer_checked = False
        self._use_katex = use_katex
        self.katex_note = ""

        self._use_chem = use_chem
        self._browser = browser
        self._chem: ChemRenderer | None = None
        self._chem_checked = False
        self.chem_note = ""

    # ------------------------------------------------------------------ 资源

    @property
    def renderer(self) -> KatexRenderer | None:
        if not self._use_katex:
            return None
        if not self._renderer_checked:
            self._renderer_checked = True
            renderer = KatexRenderer(katex_dir=self.katex_dir)
            if renderer.available:
                self._renderer = renderer
            else:
                self.katex_note = renderer.unavailable_reason
        return self._renderer

    @property
    def chem_renderer(self) -> ChemRenderer:
        if not self._chem_checked:
            self._chem_checked = True
            renderer = ChemRenderer(browser=self._browser, enabled=self._use_chem)
            self._chem = renderer
            if not renderer.available:
                self.chem_note = renderer.unavailable_reason
        assert self._chem is not None
        return self._chem

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
            self._renderer_checked = False
        if self._chem is not None:
            self._chem.close()
            self._chem = None
            self._chem_checked = False

    def __enter__(self) -> "ConversionEngine":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------ 主体

    def convert(
        self,
        options: ConversionOptions,
        progress=None,
        logger=None,
    ) -> ConversionResult:
        import time

        started = time.perf_counter()
        warnings: list[str] = []

        def note(message: str, level: str = "info") -> None:
            if logger:
                logger(message, level)
            if level == "warning":
                warnings.append(message)

        def step(message: str) -> None:
            if progress:
                progress(message)

        source = Path(options.source)
        step("读取 Markdown")
        try:
            raw = source.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raw = source.read_text(encoding="utf-8", errors="replace")
            note("源文件不是标准 UTF-8，已按容错方式读取，个别字符可能被替换。", "warning")

        text = normalize_newlines(raw)
        markdown_chars = len(text)

        output_dir = Path(options.output).parent if options.output else source.parent

        step("解析结构式")
        chem_entries: list[tuple[str, str]] = []
        structures = 0
        if options.embed_structures:
            image_dir = output_dir / f"{source.stem}-assets"
            text, chem_entries = preprocess_structures(
                text,
                self.chem_renderer if self._use_chem else None,
                image_dir=image_dir,
                logger=logger,
            )
            structures = sum(1 for _, payload in chem_entries if "chem-raw" not in payload)

        step("解析公式")
        protected = protect_math(text)
        inline_items = [item for item in protected.items if not item.display]
        display_items = [item for item in protected.items if item.display]

        step("渲染公式")
        failed = self._render_formulas(protected, note)

        step("解析 Markdown")
        parser = markdown.Markdown(
            extensions=EXTENSIONS,
            extension_configs=EXTENSION_CONFIGS,
            output_format="html",
        )
        body = parser.convert(protected.text)
        toc_html = ""
        if options.add_toc:
            toc_html = build_toc(getattr(parser, "toc_tokens", None) or [])
        parser.reset()

        step("还原公式与结构式")
        body = restore_math(body, protected, renderer=None, extra_tokens=chem_entries)

        step("处理 SVG")
        body, svg_report = embed_svg_images(
            body,
            markdown_path=source,
            output_dir=output_dir,
            enabled=options.embed_svg,
            logger=logger,
        )

        step("组装页面")
        theme_css = FALLBACK_CSS
        if options.css_path and Path(options.css_path).is_file():
            theme_css = read_css(Path(options.css_path))
        else:
            note("未指定样式表，已使用内置基础样式。", "warning")

        katex_css = ""
        if protected.count:
            katex_css = self._katex_css()

        # 失败公式在页面里以原始写法呈现，这里只需提示；
        # 只有整批公式都没能预渲染（通常是缺少 node）才启用在线兜底。
        fallback = ""
        header = ""
        if failed:
            if failed == protected.count and protected.count:
                fallback = CLIENT_FALLBACK
                note(
                    f"{failed} 处公式全部未预渲染，页面将依赖在线渲染，请保持联网。",
                    "warning",
                )
            else:
                note(
                    f"{failed} 处公式语法不被 KaTeX 接受，页面中显示为原始写法。",
                    "warning",
                )
            if katex_css:
                header = FALLBACK_NOTICE.format(count=failed) + "\n"

        footer = ""
        if options.add_footer:
            footer = (
                f'\n<footer class="doc-footer">{source.name}'
                " · 由 ASH Markdown Converter 生成</footer>\n"
            )

        title = options.document_title or source.stem
        html = build_document(
            body=body,
            title=title,
            theme_css=theme_css,
            katex_css=katex_css,
            fallback_script=fallback,
            header=header,
            footer=footer,
            toc=toc_html,
        )

        output_path = Path(options.output) if options.output else source.with_suffix(".html")
        step("写入文件")
        _write_text(output_path, html)

        return ConversionResult(
            output_path=output_path,
            html=html,
            markdown_chars=markdown_chars,
            html_chars=len(html),
            math_inline=len(inline_items),
            math_display=len(display_items),
            math_failed=failed,
            structures=structures,
            svg_embedded=svg_report.embedded,
            svg_missing=list(svg_report.missing),
            warnings=warnings,
            duration=time.perf_counter() - started,
        )

    # ------------------------------------------------------------------ 内部

    def _render_formulas(self, protected, note) -> int:
        """把所有公式一次性交给 KaTeX 预渲染，返回失败数量。"""
        if not protected.items:
            return 0

        renderer = self.renderer
        if renderer is None:
            reason = self.katex_note or "KaTeX 未就绪"
            note(f"未启用公式预渲染：{reason}", "warning")
            return len(protected.items)

        failed = 0
        for display in (False, True):
            group = [item for item in protected.items if item.display is display]
            if not group:
                continue
            results = renderer.render_many([item.tex for item in group], display)
            for item, (html, error) in zip(group, results):
                item.html = html
                item.error = error
                if html is None:
                    failed += 1

        for item in protected.items:
            if item.error:
                preview = item.tex.strip().replace("\n", " ")[:70]
                note(f"公式渲染失败：{item.error}（{preview}）", "warning")
            # 化学式写法检查：这类问题往往不报错，但会渲染成乱码
            advice = mhchem_rules.describe(item.tex)
            if advice:
                note(advice, "warning")

        return failed

    def _katex_css(self) -> str:
        if self.katex_dir is None:
            return ""
        from .assets import embedded_katex_css

        try:
            return embedded_katex_css(str(self.katex_dir))
        except Exception as exc:  # noqa: BLE001 - 资源问题不应中断转换
            self.katex_note = str(exc)
            return ""


def build_toc(tokens: list[dict], max_depth: int = 3) -> str:
    """把 markdown 的标题结构渲染成目录。"""
    lines: list[str] = []

    def walk(items: list[dict], depth: int) -> None:
        if depth > max_depth or not items:
            return
        lines.append("<ul>")
        for item in items:
            identifier = item.get("id", "")
            name = item.get("name", "")
            lines.append(f'<li><a href="#{identifier}">{name}</a>')
            children = item.get("children") or []
            if children and depth < max_depth:
                walk(children, depth + 1)
            lines.append("</li>")
        lines.append("</ul>")

    walk(tokens, 1)
    if not lines:
        return ""
    return '<nav class="doc-toc">\n' + "\n".join(lines) + "\n</nav>\n"


def _write_text(path: Path, content: str) -> None:
    """先写临时文件再替换，避免中途失败留下半个文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def check_katex_environment(katex_dir: Path | None = None) -> tuple[bool, str]:
    """供界面启动时提示用：检查预渲染环境是否完整。"""
    try:
        renderer = KatexRenderer(katex_dir=katex_dir)
    except KatexUnavailable as exc:
        return False, str(exc)
    try:
        if not renderer.available:
            return False, renderer.unavailable_reason
        results = renderer.render_many(["x^2"], False)
        html, error = results[0] if results else (None, "无响应")
        if html is None:
            return False, error or "未知错误"
        return True, ""
    finally:
        renderer.close()
