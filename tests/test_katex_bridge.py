"""KaTeX 预渲染桥的测试。

没有 node 或 KaTeX 资源时自动跳过，不影响其他用例。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.assets import AssetError, embedded_katex_css, find_katex_dir  # noqa: E402
from core.katex import KatexRenderer, find_node  # noqa: E402

KATEX_DIR = find_katex_dir()
NODE = find_node()
AVAILABLE = bool(KATEX_DIR and NODE)


@unittest.skipUnless(AVAILABLE, "缺少 node 或 KaTeX 资源")
class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.renderer = KatexRenderer(node_path=NODE, katex_dir=KATEX_DIR)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.renderer.close()

    def test_simple_formula(self) -> None:
        [(html, error)] = self.renderer.render_many(["E = mc^2"], False)
        self.assertIsNone(error)
        self.assertIn("katex", html)

    def test_display_formula(self) -> None:
        [(html, error)] = self.renderer.render_many(["a = b"], True)
        self.assertIsNone(error)
        self.assertIn("katex-display", html)

    def test_large_batch(self) -> None:
        formulas = [f"x_{{{i}}} + \\frac{{a}}{{b}}" for i in range(450)]
        results = self.renderer.render_many(formulas, False)
        self.assertEqual(len(results), len(formulas))
        self.assertTrue(all(html for html, _ in results))

    def test_invalid_formula_reports_error(self) -> None:
        [(html, error)] = self.renderer.render_many(["\\frac{1}{"], False)
        self.assertIsNone(html)
        self.assertTrue(error)

    def test_mhchem_supported(self) -> None:
        [(html, error)] = self.renderer.render_many(["\\ce{2H2 + O2 -> 2H2O}"], False)
        self.assertIsNone(error)
        self.assertIn("katex", html)

    def test_unicode_content(self) -> None:
        [(html, error)] = self.renderer.render_many(["\\text{速度} = 3\\,\\text{m/s}"], False)
        self.assertIsNone(error)
        self.assertIn("katex", html)


class AssetTests(unittest.TestCase):
    @unittest.skipUnless(KATEX_DIR, "缺少 KaTeX 资源")
    def test_css_embedded_without_external_urls(self) -> None:
        css = embedded_katex_css(str(KATEX_DIR))
        self.assertIn("data:font/woff2;base64,", css)
        self.assertNotIn("url(fonts/", css)
        self.assertNotIn("font/ttf;base64", css)

    def test_missing_dir_raises(self) -> None:
        with self.assertRaises(AssetError):
            embedded_katex_css(str(ROOT / "不存在的目录"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
