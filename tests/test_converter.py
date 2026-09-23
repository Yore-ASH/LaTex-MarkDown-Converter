"""端到端转换测试：结构正确性、SVG 内嵌、统计信息。"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.converter import ConversionEngine, ConversionOptions, build_toc  # noqa: E402
from core.css import default_theme, discover_themes, read_css  # noqa: E402
from core.svg import resolve_svg_path  # noqa: E402

DOCUMENT = """\
# 主标题

正文里的行内公式 $a_b$ 与强调 $c*d*e$ 不应互相干扰。

## 小节

$$
\\oint_C f(z)\\,dz = 2\\pi i \\sum_{k=1}^{n} \\operatorname{Res}(f, z_k). \\tag{1.1}
$$

公式之后紧跟的一段文字。

### 子小节

- 列表项 $x_1$
- 列表项 $x_2$

| 名称 | 算式 |
| --- | --- |
| 质能 | $E = mc^2$ |
| 化学 | $\\ce{2H2 + O2 -> 2H2O}$ |

```python
def f(x):
    return x ** 2  # $这里不是公式$
```

价格是 \\$100。

---

## 第二个小节

![示意图](figure.svg)

结尾。
"""

SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" width="100" height="50">
  <defs><clipPath id="clip"><rect width="10" height="10"/></clipPath></defs>
  <rect width="100" height="50" fill="#eee" clip-path="url(#clip)"/>
  <g clip-path="url(#clip)"><circle cx="20" cy="20" r="10"/></g>
  <script>alert('x')</script>
</svg>
"""


class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tempdir.name)
        cls.source = cls.folder / "sample.md"
        cls.source.write_text(DOCUMENT, encoding="utf-8")
        (cls.folder / "figure.svg").write_text(SVG, encoding="utf-8")

        theme = default_theme(ROOT / "static")
        cls.engine = ConversionEngine()
        cls.result = cls.engine.convert(
            ConversionOptions(
                source=cls.source,
                output=cls.folder / "sample.html",
                css_path=theme.path if theme else None,
                add_toc=True,
            )
        )
        cls.html = cls.result.html
        cls.body = cls.html.split("<article", 1)[-1].split("</article>", 1)[0]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.close()
        cls.tempdir.cleanup()

    # ---------------------------------------------------------- 结构

    def test_no_invalid_paragraph_div(self) -> None:
        self.assertNotIn("<p><div", self.html)

    def test_headings_are_parsed(self) -> None:
        levels = [int(m) for m in re.findall(r"<h([1-6])\b", self.body)]
        self.assertEqual(levels, [1, 2, 3, 2])
        self.assertTrue(all(b - a <= 1 for a, b in zip(levels, levels[1:])))

    def test_thematic_break_survives(self) -> None:
        self.assertIn("<hr", self.body)

    def test_emphasis_is_not_broken_by_math(self) -> None:
        self.assertNotIn("c<em>d</em>e", self.html)

    def test_code_block_keeps_dollar_signs(self) -> None:
        self.assertIn("$这里不是公式$", self.html)

    def test_escaped_dollar_survives(self) -> None:
        self.assertIn("$100", self.html.replace("\\$", "$"))

    def test_toc_is_generated(self) -> None:
        self.assertIn('class="doc-toc"', self.html)
        self.assertIn('href="#', self.html)

    # ---------------------------------------------------------- 公式

    def test_all_formulas_rendered(self) -> None:
        self.assertEqual(self.result.math_failed, 0)
        self.assertEqual(self.result.math_inline + self.result.math_display, 7)

    def test_katex_markup_present(self) -> None:
        self.assertIn("katex-html", self.html)
        self.assertNotIn("KATEX", self.html)

    def test_no_bare_delimiters_in_text(self) -> None:
        visible = re.sub(r"<code\b.*?</code>", "", self.body, flags=re.DOTALL)
        visible = re.sub(r"<pre\b.*?</pre>", "", visible, flags=re.DOTALL)
        visible = re.sub(r"<[^>]+>", "", visible)
        visible = visible.replace("\\$", "")
        self.assertNotIn("$", visible)

    def test_tag_box_rendered(self) -> None:
        self.assertEqual(self.html.count('class="tag-box"'), 1)
        self.assertIn("1.1", self.html)

    def test_math_containers_scoped(self) -> None:
        self.assertIn('class="math-display"', self.html)
        self.assertIn('class="math-inline"', self.html)

    # ---------------------------------------------------------- 资源

    def test_katex_css_is_embedded(self) -> None:
        self.assertIn("font/woff2;base64", self.html)
        self.assertNotIn("cdn.jsdelivr.net", self.html)

    def test_svg_is_inlined_and_sanitized(self) -> None:
        self.assertEqual(self.result.svg_embedded, 1)
        self.assertIn("<svg", self.html)
        self.assertNotIn("<script>alert", self.html)

    def test_svg_ids_are_prefixed(self) -> None:
        self.assertIn("svg1-clip", self.html)
        self.assertNotIn('id="clip"', self.html)

    def test_svg_caption_comes_from_alt(self) -> None:
        self.assertIn("<figcaption>示意图</figcaption>", self.html)

    def test_output_file_written(self) -> None:
        self.assertTrue(self.result.output_path.is_file())
        self.assertGreater(self.result.output_path.stat().st_size, 1000)

    def test_single_style_block(self) -> None:
        self.assertEqual(self.html.count("</style>"), 1)


class HelperTests(unittest.TestCase):
    def test_build_toc_nested(self) -> None:
        tokens = [
            {
                "id": "a",
                "name": "A",
                "children": [{"id": "a1", "name": "A1", "children": []}],
            }
        ]
        toc = build_toc(tokens)
        self.assertIn('href="#a1"', toc)
        self.assertEqual(toc.count("<ul>"), 2)

    def test_build_toc_empty(self) -> None:
        self.assertEqual(build_toc([]), "")

    def test_theme_discovery(self) -> None:
        themes = discover_themes(ROOT / "static")
        self.assertTrue(themes)
        self.assertTrue(all(theme.path.is_file() for theme in themes))

    def test_theme_css_readable(self) -> None:
        theme = default_theme(ROOT / "static")
        self.assertIsNotNone(theme)
        css = read_css(theme.path)
        self.assertIn("markdown-body", css)
        self.assertNotIn("\ufffd", css)

    def test_svg_path_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            svg = base / "图片 1.svg"
            svg.write_text("<svg/>", encoding="utf-8")
            found = resolve_svg_path("图片%201.svg?x=1#y", [base])
            self.assertIsNotNone(found)
            self.assertEqual(found.name, svg.name)

    def test_remote_url_is_ignored(self) -> None:
        self.assertIsNone(resolve_svg_path("https://example.com/a.svg", [ROOT]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
