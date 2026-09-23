"""公式保护与还原的回归测试。

覆盖的都是旧实现会出错的输入：段落中的块级公式、标题后的分隔线、
代码块里的美元符号、未配对的定界符等。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.math import (  # noqa: E402
    extract_tag,
    is_thematic_break,
    normalize_newlines,
    protect_math,
    restore_math,
    strip_tag,
)


class ProtectMathTests(unittest.TestCase):
    def test_inline_math_detected(self) -> None:
        result = protect_math("质能方程 $E = mc^2$ 很简洁。")
        self.assertEqual(result.count, 1)
        self.assertFalse(result.items[0].display)
        self.assertEqual(result.items[0].tex, "E = mc^2")

    def test_display_math_spans_lines(self) -> None:
        result = protect_math("前文\n\n$$\na = b\nc = d\n$$\n\n后文")
        self.assertEqual(result.count, 1)
        self.assertTrue(result.items[0].display)
        self.assertIn("a = b", result.items[0].tex)

    def test_multiple_display_blocks_in_sequence(self) -> None:
        result = protect_math("$$\na=b\n$$\n\n$$\nc=d\n$$\n\n$$\ne=f\n$$")
        self.assertEqual(result.count, 3)
        self.assertTrue(all(item.display for item in result.items))

    def test_content_after_closing_fence_is_kept(self) -> None:
        result = protect_math("$$\na=b\n$$ 紧接着的文字\n\n结尾")
        self.assertEqual(result.count, 1)
        self.assertIn("紧接着的文字", result.text)

    def test_display_math_gets_blank_line_boundaries(self) -> None:
        result = protect_math("设 $k=1$，则\n\n$$\nE=mc^2\n$$\n后续文字\n")
        lines = result.text.split("\n")
        token_index = next(i for i, line in enumerate(lines) if "KATEX" in line)
        self.assertEqual(lines[token_index - 1].strip(), "")
        self.assertEqual(lines[token_index + 1].strip(), "")

    def test_fenced_code_is_untouched(self) -> None:
        text = "```python\nx = $notmath$ + $2\n```\n"
        result = protect_math(text)
        self.assertEqual(result.count, 0)
        self.assertIn("$notmath$", result.text)

    def test_inline_code_is_untouched(self) -> None:
        result = protect_math("用 `$x$` 表示变量，而 $y$ 是另一个。")
        self.assertEqual(result.count, 1)
        self.assertEqual(result.items[0].tex, "y")

    def test_escaped_dollar_is_kept(self) -> None:
        result = protect_math("成本 \\$100 与公式 $P$ 。")
        self.assertEqual(result.count, 1)
        self.assertIn("\\$100", result.text)

    def test_currency_is_not_math(self) -> None:
        result = protect_math("售价 $100 到 $200 之间。")
        self.assertEqual(result.count, 0)

    def test_unmatched_display_delimiter_is_kept(self) -> None:
        result = protect_math("$$\n没有闭合的公式\n")
        self.assertEqual(result.count, 0)

    def test_tag_is_extracted_and_stripped(self) -> None:
        result = protect_math("$$\nE = mc^2 \\tag{1.7}\n$$")
        self.assertEqual(result.items[0].tag, "1.7")
        self.assertNotIn("\\tag", result.items[0].tex)

    def test_thematic_break_detection(self) -> None:
        self.assertTrue(is_thematic_break("---"))
        self.assertTrue(is_thematic_break("  ***  "))
        self.assertFalse(is_thematic_break("--"))
        self.assertFalse(is_thematic_break("正文 --- 结尾"))

    def test_normalize_newlines(self) -> None:
        self.assertEqual(normalize_newlines("a\r\nb\rc\ufeff"), "a\nb\nc")

    def test_extract_and_strip_tag_helpers(self) -> None:
        self.assertEqual(extract_tag("x \\tag{A-1}"), "A-1")
        self.assertEqual(strip_tag("x \\tag{A-1}").strip(), "x")
        self.assertIsNone(extract_tag("x"))


class RestoreMathTests(unittest.TestCase):
    def test_display_block_is_not_wrapped_in_paragraph(self) -> None:
        result = protect_math("正文\n\n$$\na=b\n$$\n")
        html = f"<p>{result.items[0].token}</p>"
        restored = restore_math(html, result)
        self.assertNotIn("<p><div", restored)
        self.assertIn('class="math-display"', restored)

    def test_inline_token_becomes_span(self) -> None:
        result = protect_math("前 $x$ 后")
        html = f"<p>前 {result.items[0].token} 后</p>"
        restored = restore_math(html, result)
        self.assertIn('class="math-inline"', restored)
        self.assertNotIn("KATEX", restored)

    def test_unrendered_formula_keeps_source(self) -> None:
        result = protect_math("$x$")
        restored = restore_math("<p>TOKEN</p>".replace("TOKEN", result.items[0].token), result)
        self.assertIn("$x$", restored)
        self.assertIn("math-raw", restored)

    def test_tag_box_is_emitted(self) -> None:
        result = protect_math("$$\ny=1 \\tag{2}\n$$")
        item = result.items[0]
        restored = restore_math(f"<p>{item.token}</p>", result)
        self.assertIn('class="tag-box"', restored)
        self.assertIn(">2<", restored)


if __name__ == "__main__":
    unittest.main(verbosity=2)
