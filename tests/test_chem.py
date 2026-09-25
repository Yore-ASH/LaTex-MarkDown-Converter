"""结构式（SMILES）渲染的回归测试。

没有浏览器或 smiles-drawer 时自动跳过需要真实渲染的用例。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.chem import (  # noqa: E402
    ChemRenderer,
    _sanitize_svg,
    find_browser,
    preprocess_structures,
)

AVAILABLE = bool(find_browser()) and (
    ROOT / "tools" / "chem" / "node_modules" / "smiles-drawer"
).is_dir()


class PreprocessTests(unittest.TestCase):
    """不依赖浏览器：只验证占位与降级行为。"""

    def test_no_smiles_returns_input(self) -> None:
        text = "# 标题\n\n正文 $x$\n"
        result, entries = preprocess_structures(text, None)
        self.assertEqual(result, text)
        self.assertEqual(entries, [])

    def test_missing_renderer_degrades_to_source(self) -> None:
        text = "结构：\n\n```smiles\nCC(=O)O\n```\n"
        result, entries = preprocess_structures(text, None)
        # 代码块被换成占位符，占位符的替换内容是 SMILES 原文
        self.assertNotIn("```", result)
        self.assertEqual(len(entries), 1)
        token, payload = entries[0]
        self.assertIn(token, result)
        self.assertIn("CC(=O)O", payload)
        self.assertIn("chem-raw", payload)

    def test_inline_without_renderer_degrades(self) -> None:
        result, entries = preprocess_structures(r"乙酸 \smiles{CC(=O)O} 在此", None)
        self.assertNotIn(r"\smiles{", result)
        self.assertEqual(len(entries), 1)
        token, payload = entries[0]
        self.assertIn(token, result)
        self.assertIn("CC(=O)O", payload)
        self.assertIn("chem-raw", payload)

    def test_inline_replacement_keeps_surrounding_text(self) -> None:
        result, _ = preprocess_structures(r"前 \smiles{c1ccccc1} 后", None)
        self.assertTrue(result.startswith("前 "))
        self.assertTrue(result.endswith(" 后"))

    def test_inline_inside_code_span_is_ignored(self) -> None:
        # 写在代码段里的示例是讲语法，不应该被渲染
        result, entries = preprocess_structures(r"写法是 `\smiles{SMILES}`。", None)
        self.assertEqual(entries, [])
        self.assertIn(r"\smiles{SMILES}", result)

    def test_fenced_blocks_do_not_swallow_each_other(self) -> None:
        text = (
            "```smiles # 甲\nCCO\n```\n\n"
            "```smiles # 乙\nCCN\n```\n\n"
            "```smiles # 丙\nCCC\n```\n"
        )
        _, entries = preprocess_structures(text, None)
        self.assertEqual(len(entries), 3)
        payloads = [payload for _, payload in entries]
        self.assertTrue(any("CCO" in item for item in payloads))
        self.assertTrue(any("CCN" in item for item in payloads))
        self.assertTrue(any("CCC" in item for item in payloads))

    def test_png_fence_is_recognized(self) -> None:
        # 无渲染器时降级为原文，但代码块本身必须被识别并替换成占位符
        text = "```smiles-png # 苯\nc1ccccc1\n```\n"
        with tempfile.TemporaryDirectory() as folder:
            result, entries = preprocess_structures(text, None, image_dir=Path(folder))
        self.assertEqual(len(entries), 1)
        token, payload = entries[0]
        self.assertIn(token, result)
        self.assertIn("c1ccccc1", payload)

    def test_png_mode_used_for_png_fence(self) -> None:
        text = "```smiles-png # 苯\nc1ccccc1\n```\n"
        _, entries = preprocess_structures(text, None, image_dir=Path("."))
        self.assertEqual(len(entries), 1)

    def test_sanitize_svg_prefixes_ids(self) -> None:
        svg = '<svg><defs><radialGradient id="ab12-atom-0"/></defs><g mask="url(#ab12-mask)"/><mask id="ab12-mask"/></svg>'
        sanitized = _sanitize_svg(svg)
        self.assertNotIn('id="ab12-atom-0"', sanitized)
        self.assertIn("url(#c", sanitized)
        self.assertIn('-ab12-mask)', sanitized)

    def test_sanitize_svg_without_ids_is_unchanged(self) -> None:
        svg = "<svg><line x1='0' y1='0' x2='1' y2='1'/></svg>"
        self.assertEqual(_sanitize_svg(svg), svg)


@unittest.skipUnless(AVAILABLE, "缺少浏览器或 smiles-drawer")
class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.renderer = ChemRenderer()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.renderer.close()

    def test_simple_molecule(self) -> None:
        [data] = self.renderer.render_many([{"smiles": "CC(=O)O", "mode": "svg"}])
        self.assertIsNone(data.get("error"))
        self.assertIn("<svg", data.get("svg", ""))
        self.assertGreater(data.get("width", 0), 0)

    def test_benzene_ring(self) -> None:
        [data] = self.renderer.render_many([{"smiles": "c1ccccc1", "mode": "svg"}])
        self.assertIsNone(data.get("error"))

    def test_stereochemistry(self) -> None:
        [data] = self.renderer.render_many([{"smiles": "C[C@H](N)C(=O)O", "mode": "svg"}])
        self.assertIsNone(data.get("error"))

    def test_invalid_smiles_reports_error(self) -> None:
        [data] = self.renderer.render_many([{"smiles": "C(((", "mode": "svg"}])
        self.assertTrue(data.get("error"))

    def test_png_mode_returns_base64(self) -> None:
        [data] = self.renderer.render_many(
            [{"smiles": "c1ccccc1", "mode": "png", "scale": 2}]
        )
        self.assertIsNone(data.get("error"))
        self.assertTrue(data.get("png"))
        import base64

        raw = base64.b64decode(data["png"])
        self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_batch_render(self) -> None:
        smiles = ["CCO", "c1ccccc1", "CC(=O)O", "CCN", "CCCl"]
        results = self.renderer.render_many(
            [{"smiles": value, "mode": "svg"} for value in smiles]
        )
        self.assertEqual(len(results), len(smiles))
        self.assertTrue(all(not item.get("error") for item in results))

    def test_preprocess_produces_tokens(self) -> None:
        text = "```smiles # 乙酸\nCC(=O)O\n```\n\n行内 \\smiles{c1ccccc1}\n"
        result, entries = preprocess_structures(text, self.renderer)
        self.assertIn("CHEM", result)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all("svg" in payload for _, payload in entries))
        self.assertIn("乙酸", result.join([payload for _, payload in entries]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
