# -*- coding: utf-8 -*-
"""公众号文字稿一键排版助手的自动化测试。"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "wechat-article-typesetter" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import typeset  # noqa: E402
import validate  # noqa: E402

SAMPLE = """# 测试标题

第一段，包含**加粗**和==高亮==，还有`代码`。

## 第一节

引用前的正文。

> 这是一段引用。

- 列表一
- 列表二

### 小标题

1. 第一步
2. 第二步

---

```text
print("hello")
```
"""


class TypesetTests(unittest.TestCase):
    def test_all_styles_generate_and_pass_validation(self):
        for style_id in typeset.STYLE_IDS:
            with self.subTest(style=style_id):
                document = typeset.render(SAMPLE, style_id=style_id)
                self.assertIn('id="wechat-article"', document)
                self.assertNotIn("<script", document.lower())
                report = validate.validate_html(document)
                failed = [c for c in report["checks"] if not c["passed"]]
                self.assertTrue(
                    report["passed"], msg=f"{style_id} 校验失败：{failed}"
                )

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            typeset.render("   \n\n", style_id="heytea")

    def test_title_fallback(self):
        document = typeset.render("# 我的标题\n\n正文", style_id="minimal")
        self.assertIn("<title>我的标题</title>", document)
        self.assertEqual(document.count("<h1"), 1)

    def test_title_argument_skips_markdown_title(self):
        document = typeset.render(
            "# 原标题\n\n正文", style_id="minimal", title="新标题"
        )
        self.assertIn("<title>新标题</title>", document)
        self.assertNotIn("原标题", document)

    def test_html_escaping(self):
        document = typeset.render(
            "# 标题\n\n<script>alert(1)</script>", style_id="heytea"
        )
        self.assertIn("&lt;script&gt;", document)
        self.assertNotIn("<script", document)

    def test_accent_override(self):
        document = typeset.render(SAMPLE, style_id="heytea", accent="#123456")
        self.assertIn("#123456", document)

    def test_invalid_accent_raises(self):
        with self.assertRaises(ValueError):
            typeset.render(SAMPLE, style_id="heytea", accent="orange")

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            typeset.render(SAMPLE, style_id="nope")

    def test_markdown_structures_rendered(self):
        document = typeset.render(SAMPLE, style_id="academic")
        for tag in (
            "<h2",
            "<h3",
            "<blockquote",
            "<ul",
            "<ol",
            "<hr",
            "<pre",
            "<strong",
            "<code",
        ):
            self.assertIn(tag, document)


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.document = typeset.render(SAMPLE, style_id="heytea")

    def _failed(self, report):
        return [c["id"] for c in report["checks"] if not c["passed"]]

    def test_clean_document_passes(self):
        self.assertTrue(validate.validate_html(self.document)["passed"])

    def test_external_resource_detected(self):
        broken = self.document.replace(
            '<div id="wechat-article"',
            '<img src="https://example.com/a.png" style="width:10px;">\n'
            '<div id="wechat-article"',
            1,
        )
        report = validate.validate_html(broken)
        self.assertFalse(report["passed"])
        self.assertIn("no-remote-resources", self._failed(report))

    def test_low_contrast_detected(self):
        broken = self.document.replace(
            "</div>\n</body>",
            '<p style="color:#EEEEEE;font-size:16px;line-height:1.8;">'
            "浅色文字</p>\n</div>\n</body>",
            1,
        )
        report = validate.validate_html(broken)
        self.assertIn("text-contrast", self._failed(report))

    def test_missing_inline_style_detected(self):
        broken = self.document.replace(
            "</div>\n</body>", "<p>无样式段落</p>\n</div>\n</body>", 1
        )
        report = validate.validate_html(broken)
        self.assertIn("inline-styles", self._failed(report))

    def test_contrast_ratio_known_values(self):
        self.assertAlmostEqual(
            validate.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=1
        )
        self.assertAlmostEqual(
            validate.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=2
        )


class CliTests(unittest.TestCase):
    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "article.md"
            output_path = Path(tmp) / "article.html"
            input_path.write_text(SAMPLE, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "typeset.py"),
                    str(input_path),
                    "--style",
                    "minimal",
                    "--output",
                    str(output_path),
                    "--validate",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(
                result.returncode, 0, msg=result.stdout + result.stderr
            )
            self.assertTrue(output_path.exists())
            self.assertIn("排版校验：通过", result.stdout)

    def test_missing_input_file_reports_error(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "typeset.py"),
                "不存在的文件.md",
                "--style",
                "heytea",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("无法读取文件", result.stdout + result.stderr)

    def test_validator_cli_reports_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "article.html"
            path.write_text(
                typeset.render(SAMPLE, style_id="academic"), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate.py"),
                    str(path),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(
                result.returncode, 0, msg=result.stdout + result.stderr
            )
            self.assertIn('"passed": true', result.stdout)


if __name__ == "__main__":
    unittest.main()
