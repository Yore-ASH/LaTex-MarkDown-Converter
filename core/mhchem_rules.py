"""mhchem 用法检查。

KaTeX / MathJax 的 mhchem 并不支持 ``\\overset`` ``\\underset``，
也不接受箭头标注里再套 ``\\text{}``。这些写法要么直接报错，
要么把命令原样输出到页面上，写的人很难自己发现。
这里在转换阶段把它们挑出来，并给出可直接替换的写法。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 箭头标注：->[...] 或 ->[...][...]
_ARROW_ARG = re.compile(r"(?:-+>|<--?|<=+>|<<?=>+)\s*\[")
_TEXT_IN_ARG = re.compile(r"\\(?:text|mathrm|textrm|mbox)\s*\{")
_CE_BLOCK = re.compile(r"\\ce\s*\{")
_ARROW = re.compile(r"(?:-+>|<--?|<=+>|<<?=>+)\s*\[([^\]]*)\](?:\s*\[([^\]]*)\])?")
# 花括号里出现这些写法说明作者想写数学，但 {} 是正体文本
_MATH_IN_TEXT = re.compile(r"(?:\^|_|\\[a-zA-Z]+)")


@dataclass
class ChemIssue:
    """一条可读的用法问题。"""

    pattern: str
    message: str
    suggestion: str
    example: str = ""


def _ce_spans(tex: str) -> list[tuple[int, int]]:
    """找出 ``\\ce{...}`` 覆盖的区间（按花括号配对）。"""
    spans: list[tuple[int, int]] = []
    for match in _CE_BLOCK.finditer(tex):
        depth = 1
        index = match.end()
        while index < len(tex) and depth:
            char = tex[index]
            if char == "\\":
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        spans.append((match.start(), index))
    return spans


def _arrow_groups(tex: str) -> list[str]:
    """取出所有箭头标注的原始内容（保留 [] 里的原样文本）。"""
    groups: list[str] = []
    for match in _ARROW.finditer(tex):
        for group in (1, 2):
            content = match.group(group)
            if content:
                groups.append(content)
    return groups


def _strip_math(content: str) -> str:
    """去掉标注里的 $...$ 片段，剩下的部分才是正体文本。"""
    return re.sub(r"\$[^$]*\$", "", content)


def _text_group_bodies(content: str) -> list[str]:
    """取出标注里 {...} 分组的内容（跳过最外层包裹）。"""
    bodies: list[str] = []
    depth = 0
    start = -1
    for index, char in enumerate(content):
        if char == "{":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start != -1:
                bodies.append(content[start:index])
                start = -1
    return bodies


def inspect(tex: str) -> list[ChemIssue]:
    """检查一段公式里的 mhchem 用法，返回需要提醒的问题。"""
    if "\\ce" not in tex:
        return []

    issues: list[ChemIssue] = []
    spans = _ce_spans(tex)

    def inside_ce(position: int) -> bool:
        return any(start <= position < end for start, end in spans)

    for match in re.finditer(r"\\(overset|underset)", tex):
        if not inside_ce(match.start()):
            continue
        command = match.group(1)
        issues.append(
            ChemIssue(
                pattern=f"\\{command}",
                message=f"mhchem 不支持在 \\ce{{}} 内部使用 \\{command}",
                suggestion=(
                    "箭头上下的说明改用 mhchem 的方括号语法："
                    "\\ce{A ->[上方][下方] B}；"
                    "确实要上下叠字时，把 \\ce{} 包在 $...$ 里再叠"
                ),
                example=r"$\underset{\text{还原}}{...}$",
            )
        )

    for content in _arrow_groups(tex):
        if _TEXT_IN_ARG.search(content):
            issues.append(
                ChemIssue(
                    pattern="\\text{}",
                    message="箭头标注里的 \\text{} 会被当成普通字符，渲染失败",
                    suggestion=(
                        "标注直接写在 {} 里即可（自动正体）；"
                        "要斜体数学变量再用 $...$，例如 ->[{$\\Delta$}]"
                    ),
                    example=r"\ce{A ->[{浓硫酸}][{170^\circ C}] B}",
                )
            )

        # {} 里是正体文本，数学写法必须再包一层 $...$
        for body in _text_group_bodies(_strip_math(content)):
            if _MATH_IN_TEXT.search(body):
                issues.append(
                    ChemIssue(
                        pattern="标注内数学写法",
                        message=(
                            "箭头标注的花括号里是正体文本，"
                            f"“{body.strip()[:24]}” 中的 ^ _ \\circ 等不会被当作数学"
                        ),
                        suggestion="把这段数学内容单独用 $...$ 包起来",
                        example=r"\ce{A ->[{升温}][{$170^\circ$C}] B}",
                    )
                )

    # 去重：同一类问题只提示一次
    unique: list[ChemIssue] = []
    seen: set[str] = set()
    for issue in issues:
        if issue.pattern in seen:
            continue
        seen.add(issue.pattern)
        unique.append(issue)
    return unique


def describe(tex: str) -> str:
    """把问题汇总成一句给日志用的话。"""
    issues = inspect(tex)
    if not issues:
        return ""
    parts = [f"{issue.message}；建议：{issue.suggestion}" for issue in issues]
    preview = tex.strip().replace("\n", " ")[:50]
    return f"化学式用法提示（{preview}）：" + " / ".join(parts)
