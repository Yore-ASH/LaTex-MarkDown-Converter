"""mhchem 用法检查的回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.mhchem_rules import describe, inspect  # noqa: E402


class MhchemRuleTests(unittest.TestCase):
    def test_overset_inside_ce_is_flagged(self) -> None:
        issues = inspect(r"\ce{A \overset{cat}-> B}")
        self.assertTrue(any("overset" in issue.pattern for issue in issues))

    def test_underset_inside_ce_is_flagged(self) -> None:
        issues = inspect(r"\ce{\underset{x}{C}O2}")
        self.assertTrue(any("underset" in issue.pattern for issue in issues))

    def test_overset_outside_ce_is_allowed(self) -> None:
        self.assertEqual(inspect(r"\overset{a}{b}"), [])

    def test_text_inside_arrow_argument_is_flagged(self) -> None:
        issues = inspect(r"\ce{A ->[\text{浓硫酸}] B}")
        self.assertTrue(any(issue.pattern == "\\text{}" for issue in issues))

    def test_plain_arrow_argument_is_clean(self) -> None:
        self.assertEqual(inspect(r"\ce{A ->[{浓硫酸}][{$170^\circ$C}] B}"), [])

    def test_math_inside_braces_is_flagged(self) -> None:
        # {} 里是正体文本，170^\circ 会被当成普通字符导致报错
        issues = inspect(r"\ce{A ->[{浓硫酸}][{170^\circ C}] B}")
        self.assertTrue(any(issue.pattern == "标注内数学写法" for issue in issues))

    def test_degree_in_math_mode_is_clean(self) -> None:
        self.assertEqual(inspect(r"\ce{A ->[{浓硫酸}][{$170^\circ$C}] B}"), [])

    def test_subscript_in_braces_is_flagged(self) -> None:
        issues = inspect(r"\ce{A ->[{x_1}] B}")
        self.assertTrue(any(issue.pattern == "标注内数学写法" for issue in issues))

    def test_chinese_in_braces_is_clean(self) -> None:
        self.assertEqual(inspect(r"\ce{A ->[{高温高压}] B}"), [])

    def test_math_in_arrow_argument_is_clean(self) -> None:
        self.assertEqual(inspect(r"\ce{A ->[$\Delta$] B}"), [])

    def test_reversible_arrow_clean(self) -> None:
        self.assertEqual(
            inspect(r"\ce{N2 + 3H2 <=>[{cat}][{高压}] 2NH3}"), []
        )

    def test_non_ce_formula_is_ignored(self) -> None:
        self.assertEqual(inspect(r"\frac{\text{a}}{\text{b}}"), [])

    def test_duplicate_issues_collapse(self) -> None:
        issues = inspect(r"\ce{\overset{a}{b}} \ce{\overset{c}{d}}")
        self.assertEqual(len([i for i in issues if "overset" in i.pattern]), 1)

    def test_nested_braces_in_ce_are_parsed(self) -> None:
        # 花括号嵌套时不应把外面的 \overset 误判为在 \ce 内
        self.assertEqual(inspect(r"\ce{CH3-CH(CH3)-CH3} \overset{a}{b}"), [])

    def test_describe_returns_readable_text(self) -> None:
        text = describe(r"\ce{A \overset{x}-> B}")
        self.assertIn("建议", text)
        self.assertIn("mhchem", text)

    def test_describe_empty_for_clean_formula(self) -> None:
        self.assertEqual(describe(r"\ce{H2O}"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
