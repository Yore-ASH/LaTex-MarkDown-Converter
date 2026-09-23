"""Markdown 渲染辅助：数学公式保护、行内代码识别、样式预处理。

这一层只依赖标准库，方便单独测试。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MATH_MARK = "\x00KATEX"

# 行首可选的引用前缀（支持嵌套引用）
_QUOTE_PREFIX = re.compile(r"^(?:[ \t]{0,3}>[ \t]?)+")
# 围栏代码块：``` 或 ~~~，最多允许 3 个前导空格
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
# 分隔线：三个以上的 - * _，之间可有空格
_THEMATIC_BREAK = re.compile(r"^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
# 强调折叠产生的空标签
_EMPTY_EMPHASIS = re.compile(r"<(em|strong|b|i)>\s*</\1>")
# 公式编号
_TAG_COMMAND = re.compile(r"\\tag\s*\{([^{}]*)\}")


@dataclass
class MathItem:
    """一条被保护的公式。"""

    index: int
    tex: str
    display: bool
    tag: str | None = None
    html: str | None = None
    error: str | None = None

    @property
    def token(self) -> str:
        return f"{MATH_MARK}{self.index}\x00"

    @property
    def delimiter(self) -> str:
        return "$$" if self.display else "$"

    @property
    def source(self) -> str:
        return f"{self.delimiter}{self.tex}{self.delimiter}"


@dataclass
class ProtectResult:
    """保护后的 Markdown 文本与还原所需的数据。"""

    text: str
    items: list[MathItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)


def normalize_newlines(text: str) -> str:
    """统一换行符，去掉 BOM 与零宽空格。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\u200b", "").replace("\ufeff", "")


def _strip_quote_prefix(line: str) -> str:
    """去掉行首的引用前缀，用于在引用块内部识别围栏与缩进。"""
    return _QUOTE_PREFIX.sub("", line)


def _is_fence(line: str) -> tuple[bool, str, int]:
    """判断是否为围栏行。返回 (是否围栏, 围栏字符, 长度)。"""
    match = _FENCE.match(_strip_quote_prefix(line))
    if not match:
        return False, "", 0
    marker = match.group(1)
    info = match.group(2).strip()
    # ``` 后面紧跟文字是合法的 info string，只有 ` 与 ~ 混用才非法
    if marker[0] == "`" and "`" in info:
        return False, "", 0
    return True, marker[0], len(marker)


def _find_code_span(line: str, start: int) -> int:
    """若 line[start] 处存在反引号代码段，返回其结束位置（不含），否则返回 -1。"""
    if line[start] != "`":
        return -1
    run_end = start
    while run_end < len(line) and line[run_end] == "`":
        run_end += 1
    run_length = run_end - start
    probe = run_end
    while True:
        probe = line.find("`" * run_length, probe)
        if probe == -1:
            return -1
        after = probe + run_length
        if after >= len(line) or line[after] != "`":
            return after
        probe = probe + 1


def _pushes_right(text: str, index: int) -> bool:
    """判断 index 之后的首个字符是否“贴住”美元符号。"""
    return index < len(text) and not text[index].isspace()


def _pulls_left(text: str, index: int) -> bool:
    """判断 index 之前的字符是否“贴住”美元符号。"""
    return index > 0 and not text[index - 1].isspace()


def _looks_like_currency(text: str, dollar: int) -> bool:
    """形如 $100、US$100 的金额不当作公式起始。"""
    after = dollar + 1
    if after >= len(text) or not text[after].isdigit():
        return False
    before = text[dollar - 1] if dollar > 0 else ""
    return before == "" or before.isspace() or before in "(（[【:：,，"


def _find_inline_close(line: str, start: int) -> int:
    """从 start（指向起始 $）开始寻找行内公式的结束 $。"""
    i = start + 1
    length = len(line)
    while i < length:
        char = line[i]
        if char == "\\":
            i += 2
            continue
        if char == "`":
            end = _find_code_span(line, i)
            if end != -1:
                i = end
                continue
        if char == "$":
            if not _pulls_left(line, i):
                i += 1
                continue
            if i + 1 < length and line[i + 1] == "$":
                # 行内公式里出现 $$ 视为异常，放弃匹配
                return -1
            return i
        i += 1
    return -1


def _mask_inline_math(line: str, items: list[MathItem]) -> str:
    """处理一行中的行内公式，返回替换为占位符的行。

    该行不得处于围栏代码块内部。
    """
    out: list[str] = []
    i = 0
    length = len(line)
    while i < length:
        char = line[i]

        if char == "\\":
            # 反斜杠转义：原样跳过两个字符
            out.append(line[i : i + 2])
            i += 2
            continue

        if char == "`":
            end = _find_code_span(line, i)
            if end != -1:
                out.append(line[i:end])
                i = end
                continue
            out.append(char)
            i += 1
            continue

        if char == "$":
            if _looks_like_currency(line, i):
                out.append("$")
                i += 1
                continue
            if not _pushes_right(line, i + 1):
                out.append("$")
                i += 1
                continue

            close = _find_inline_close(line, i)
            if close == -1:
                out.append("$")
                i += 1
                continue

            tex = line[i + 1 : close]
            item = MathItem(index=len(items), tex=tex, display=False)
            items.append(item)
            out.append(item.token)
            i = close + 1
            continue

        out.append(char)
        i += 1

    return "".join(out)


def _find_display_close(lines: list[str], start_line: int, start_col: int) -> tuple[int, int] | None:
    """寻找块级公式的结束 $$，返回 (行号, 列号)，找不到返回 None。"""
    line_no = start_line
    col = start_col
    while line_no < len(lines):
        line = lines[line_no]
        while col < len(line):
            if line[col] == "\\":
                col += 2
                continue
            if line.startswith("$$", col):
                return line_no, col
            col += 1
        line_no += 1
        col = 0
    return None


def protect_math(text: str) -> ProtectResult:
    """把 Markdown 中的公式替换为占位符，避免解析器改坏公式。

    与旧实现不同，这里不插入任何 HTML 标签，因此不会产生
    ``<p><div>`` 这类非法嵌套，也不会打断标题层级。
    """
    lines = text.split("\n")
    items: list[MathItem] = []
    out_lines: list[str] = []

    fence_char = ""
    fence_len = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        is_fence, char, run = _is_fence(line)
        if is_fence:
            if not fence_char:
                fence_char, fence_len = char, run
            elif char == fence_char and run >= fence_len:
                fence_char, fence_len = "", 0
            out_lines.append(line)
            i += 1
            continue

        if fence_char:
            out_lines.append(line)
            i += 1
            continue

        quote = _QUOTE_PREFIX.match(line)
        prefix = quote.group(0) if quote else ""
        rest_start = len(prefix)
        rest = line[rest_start:]

        # 缩进 4 空格以上的整行内容按缩进代码块处理，不做公式保护
        if rest.strip() and (len(rest) - len(rest.lstrip(" "))) >= 4:
            out_lines.append(line)
            i += 1
            continue

        dollar = rest.find("$$")
        if dollar == -1:
            out_lines.append(prefix + _mask_inline_math(rest, items))
            i += 1
            continue

        # 本行存在 $$，检查是否可以跨行配平
        close = _find_display_close(lines, i, rest_start + dollar + 2)
        if close is None:
            # 没有配对：整行按普通文本处理，避免把 $$ 拆成两个行内公式
            out_lines.append(line)
            i += 1
            continue

        close_line, close_col = close
        head = prefix + _mask_inline_math(rest[:dollar], items)
        ends_on_this_line = close_line == i

        if ends_on_this_line:
            tex = lines[i][rest_start + dollar + 2 : close_col]
        else:
            chunks = [lines[i][rest_start + dollar + 2 :]]
            for mid in range(i + 1, close_line):
                chunks.append(lines[mid])
            chunks.append(lines[close_line][:close_col])
            tex = "\n".join(chunks)

        item = MathItem(index=len(items), tex=tex, display=True)
        items.append(item)

        # 公式两侧一律留空行：否则占位符会被当成段落内联内容，
        # markdown 会生成 <p><div ...> 这种非法嵌套。
        if head.strip():
            out_lines.append(head.rstrip())
            out_lines.append("")
        out_lines.append(item.token)

        if ends_on_this_line:
            # 闭合的 $$ 之后可能还有内容，把它缩到行首后重新走一遍本行；
            # 先补一个空行，保证同一行里相邻的两段公式不会落进同一个段落
            out_lines.append("")
            lines[i] = prefix + lines[i][close_col + 2 :]
            continue

        # 跨行公式：闭合行剩余的内容补一行空行，保持块级边界
        rest_of_close_line = lines[close_line][close_col + 2 :]
        out_lines.append("")
        if rest_of_close_line.strip():
            out_lines.append(rest_of_close_line)
            out_lines.append("")
        i = close_line + 1

    result = ProtectResult(text="\n".join(out_lines), items=items)
    for item in result.items:
        item.tag = extract_tag(item.tex)
        if item.tag is not None:
            item.tex = strip_tag(item.tex)
    return result


def extract_tag(tex: str) -> str | None:
    """取出 \\tag{...} 的编号，用于渲染到公式右侧。"""
    match = _TAG_COMMAND.search(tex)
    if not match:
        return None
    return match.group(1).strip()


def strip_tag(tex: str) -> str:
    """去掉 \\tag{...}，交由样式层呈现编号。"""
    return _TAG_COMMAND.sub("", tex).strip()


def restore_math(
    html: str,
    result: ProtectResult,
    renderer=None,
    logger=None,
) -> str:
    """把占位符还原为渲染结果。

    ``renderer`` 是可调用对象，签名为
    ``renderer(tex, display) -> (html | None, error | None)``。
    通常公式已由 ``ConversionEngine`` 批量预渲染并写入 ``MathItem.html``，
    此时传 None 即可。
    """
    for item in result.items:
        if renderer is not None:
            item.html, item.error = renderer(item.tex, item.display)
            if item.html is None and logger is not None:
                preview = item.tex.strip().replace("\n", " ")[:60]
                logger(f"公式渲染失败：{item.error}（{preview}）", "warning")

    html = _replace_tokens_in_paragraphs(html, result.items)
    html = _substitute_tokens(html, result.items)
    return _collapse_empty_emphasis(html)


def _substitute_tokens(html: str, items: list[MathItem]) -> str:
    """一次性替换剩余占位符。

    逐个 ``str.replace`` 在长文档上会反复扫描整个 HTML，
    这里合并成一次正则扫描。
    """
    if not items or MATH_MARK not in html:
        return html

    mapping = {
        item.token: _display_block(item) if item.display else _inline_span(item)
        for item in items
    }
    pattern = re.compile("|".join(re.escape(token) for token in mapping))
    return pattern.sub(lambda match: mapping[match.group(0)], html)


_PARAGRAPH = re.compile(r"<p>", re.IGNORECASE)


def _replace_tokens_in_paragraphs(html: str, items: list[MathItem]) -> str:
    """把段落内部的块级公式占位符拆出来，避免出现 ``<p><div>``。

    KaTeX 的渲染结果里本身还嵌着 ``<div>``，用正则判断闭合位置并不可靠，
    这里直接定位段落边界：只有落在 ``<p>`` 与 ``</p>`` 之间的块级公式
    才需要搬出来。
    """
    display_items = [item for item in items if item.display]
    if not display_items:
        return html

    mapping = {item.token: _display_block(item) for item in display_items}
    tokens = set(mapping)
    parts: list[str] = []
    cursor = 0
    search_from = 0

    while True:
        opening = _PARAGRAPH.search(html, search_from)
        if opening is None:
            break
        closing = html.find("</p>", opening.end())
        if closing == -1:
            break

        inner = html[opening.end() : closing]
        if not any(token in inner for token in tokens):
            search_from = closing + 4
            continue

        parts.append(html[cursor : opening.start()])
        parts.append(_split_paragraph(inner, mapping))
        cursor = closing + 4
        search_from = cursor

    if not parts:
        return html
    parts.append(html[cursor:])
    return "".join(parts)


def _split_paragraph(text: str, mapping: dict[str, str]) -> str:
    """把只含空白的部分丢掉，其余内容与块级公式各自成段。"""
    pieces: list[str] = []
    pattern = re.compile("|".join(re.escape(token) for token in mapping))

    position = 0
    for match in pattern.finditer(text):
        piece = text[position : match.start()].strip()
        if piece:
            pieces.append(piece if piece.startswith("<p>") else f"<p>{piece}</p>")
        pieces.append(mapping[match.group(0)])
        position = match.end()

    tail = text[position:].strip()
    if tail:
        pieces.append(tail if tail.startswith("<p>") else f"<p>{tail}</p>")
    return "\n".join(pieces)


def _render_or_source(item: MathItem) -> str:
    # 渲染失败时展示原始写法：既让读者看得懂，也避免页面上出现 KaTeX 的报错红字
    if item.html and not item.error:
        return item.html
    return _raw_source(item)


def _raw_source(item: MathItem) -> str:
    escaped = item.source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<code class="math-raw">{escaped}</code>'


def _display_block(item: MathItem) -> str:
    tag = ""
    if item.tag:
        tag = f'\n  <span class="tag-box">{item.tag}</span>'
    classes = "math-display"
    if item.error:
        classes += " math-error"
    return (
        f'<div class="{classes}" data-tex="{_attr_escape(item.source)}">\n'
        f"  {_render_or_source(item)}{tag}\n"
        f"</div>"
    )


def _inline_span(item: MathItem) -> str:
    classes = "math-inline"
    if item.error:
        classes += " math-error"
    return (
        f'<span class="{classes}" data-tex="{_attr_escape(item.source)}">'
        f"{_render_or_source(item)}</span>"
    )


def _attr_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _collapse_empty_emphasis(html: str) -> str:
    """Markdown 会把 ``*a*_b_`` 之类解析成空强调标签，清掉以免出现奇怪空行。"""
    previous = None
    while previous != html:
        previous = html
        html = _EMPTY_EMPHASIS.sub("", html)
    return html


def is_thematic_break(line: str) -> bool:
    """是否为 Markdown 分隔线。"""
    return bool(_THEMATIC_BREAK.match(_strip_quote_prefix(line)))
