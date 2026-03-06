import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from docx import Document

from gate_ddos.docx import process_template_docx
from gate_ddos.docx.styles import ensure_required_styles
from gate_ddos.docx.html import postprocess_html
from gate_ddos.docx.markdown import normalize_newlines
from gate_ddos.models import SectionRecord, TemplateSyntax
from gate_ddos.section_store import SectionStore


class DocxPipelineTests(unittest.TestCase):
    def test_multiline_placeholder_spanning_paragraphs(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.docx"
            output_path = Path(tmp) / "output.docx"

            template = Document()
            template.add_paragraph("{{ SYSTEM_DESCRIPTION || Describe the system")
            template.add_paragraph("from a non-technical point of view. }}")
            template.save(template_path)

            def fake_generate(system_prompt, prompt, model):
                self.assertIn("non-technical", prompt)
                return "Generated description"

            process_template_docx(template_path=template_path, output_path=output_path, system_prompt="sys", model="m", syntax=TemplateSyntax(), store=SectionStore(), generate=fake_generate)

            result = Document(output_path)
            joined = "\n".join(p.text for p in result.paragraphs)
            self.assertIn("Generated description", joined)
            self.assertNotIn("{{", joined)

    def test_empty_placeholder_output_removes_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.docx"
            output_path = Path(tmp) / "output.docx"

            template = Document()
            template.add_paragraph("Before")
            template.add_paragraph("{{ MISSING }}")
            template.add_paragraph("After")
            template.save(template_path)

            process_template_docx(template_path=template_path, output_path=output_path, system_prompt="sys", model="m", syntax=TemplateSyntax(), store=SectionStore(), generate=lambda *_: "unused")

            result = Document(output_path)
            non_empty = [paragraph.text.strip() for paragraph in result.paragraphs if paragraph.text.strip()]
            self.assertEqual(non_empty, ["Before", "After"])

    def test_multiple_placeholders_preserve_position(self):
        """Regression: content must appear at the position of its placeholder."""
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.docx"
            output_path = Path(tmp) / "output.docx"

            template = Document()
            template.add_paragraph("Header")
            template.add_paragraph("{{ NAME || Name of system: }}")
            template.add_paragraph("")
            template.add_paragraph("{{ LICENSE }}")
            template.add_paragraph("")
            template.add_paragraph("Section heading")
            template.add_paragraph("{{ DESCRIPTION || Describe the system.")
            template.add_paragraph("Consider users and installation.")
            template.add_paragraph("}}")
            template.save(template_path)

            store = SectionStore({
                "NAME": SectionRecord(prompt="Name of system:", output="ACME Tool", source="json"),
                "LICENSE": SectionRecord(prompt="", output="MIT", source="json"),
                "DESCRIPTION": SectionRecord(
                    prompt="Describe the system.\nConsider users and installation.",
                    output="A great tool.",
                    source="json",
                ),
            })

            process_template_docx(template_path=template_path, output_path=output_path, system_prompt="sys", model="m", syntax=TemplateSyntax(), store=store, generate=lambda *_: "unused")

            result = Document(output_path)
            texts = [p.text for p in result.paragraphs]
            self.assertEqual(texts, ["Header", "ACME Tool", "", "MIT", "", "Section heading", "A great tool."])

    def testensure_required_styles_adds_missing_styles(self):
        """ensure_required_styles must add List Bullet / List Number when absent."""
        from docx.oxml.ns import qn

        doc = Document()
        # Remove List Bullet and List Number from the styles XML.
        styles_elem = doc.styles._element
        for style_el in styles_elem:
            name_el = style_el.find(qn("w:name"))
            if name_el is not None and name_el.get(qn("w:val")) in ("List Bullet", "List Number"):
                styles_elem.remove(style_el)

        existing_before = {s.name for s in doc.styles}
        self.assertNotIn("List Bullet", existing_before)
        self.assertNotIn("List Number", existing_before)

        ensure_required_styles(doc)

        existing_after = {s.name for s in doc.styles}
        self.assertIn("List Bullet", existing_after)
        self.assertIn("List Number", existing_after)

    def test_bulleted_list_output_does_not_crash(self):
        """A placeholder output containing a Markdown bullet list must not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.docx"
            output_path = Path(tmp) / "output.docx"

            template = Document()
            # Strip list styles to simulate a sparse template.
            from docx.oxml.ns import qn as _qn
            styles_elem = template.styles._element
            for el in styles_elem:
                name_el = el.find(_qn("w:name"))
                if name_el is not None and name_el.get(_qn("w:val")) in ("List Bullet", "List Number"):
                    styles_elem.remove(el)
            template.add_paragraph("{{ ITEMS || List items }}")
            template.save(template_path)

            store = SectionStore({
                "ITEMS": SectionRecord(
                    prompt="List items",
                    output="- Alpha\n- Beta\n- Gamma",
                    source="json",
                ),
            })

            process_template_docx(template_path=template_path, output_path=output_path, system_prompt="sys", model="m", syntax=TemplateSyntax(), store=store, generate=lambda *_: "unused")

            result = Document(output_path)
            joined = " ".join(p.text for p in result.paragraphs)
            self.assertIn("Alpha", joined)
            self.assertIn("Beta", joined)
            self.assertIn("Gamma", joined)


class NormalizeNewlinesTests(unittest.TestCase):
    """Tests for normalize_newlines edge cases."""

    def test_single_newline_becomes_hard_break(self):
        """A lone \\n should be converted to a Markdown hard break."""
        result = normalize_newlines("line1\nline2")
        self.assertEqual(result, "line1  \nline2")

    def test_double_newline_unchanged(self):
        """\\n\\n is a standard Markdown paragraph break kept as-is."""
        result = normalize_newlines("para1\n\npara2")
        self.assertEqual(result, "para1\n\npara2")

    def test_triple_newline_inserts_sentinel(self):
        """\\n\\n\\n should produce a sentinel for 1 extra blank paragraph."""
        result = normalize_newlines("a\n\n\nb")
        self.assertIn("<!-- EXTRA_NL:1 -->", result)

    def test_quad_newline_inserts_sentinel_2(self):
        """\\n\\n\\n\\n should produce a sentinel for 2 extra blank paragraphs."""
        result = normalize_newlines("a\n\n\n\nb")
        self.assertIn("<!-- EXTRA_NL:2 -->", result)

    def test_fenced_code_block_preserved(self):
        """Newlines inside fenced code blocks must NOT be altered."""
        code = "```\nline1\nline2\n```"
        result = normalize_newlines(code)
        self.assertEqual(result, code)

    def test_fenced_code_with_language(self):
        """Fenced code block with language specifier is preserved."""
        code = "```python\ndef foo():\n    pass\n```"
        result = normalize_newlines(code)
        self.assertEqual(result, code)

    def test_text_around_fenced_code(self):
        """Newlines outside code blocks are normalised; inside are not."""
        text = "before\nstuff\n```\na\nb\n```\nafter\nmore"
        result = normalize_newlines(text)
        self.assertIn("before  \nstuff", result)
        self.assertIn("```\na\nb\n```", result)
        self.assertIn("after  \nmore", result)

    def test_tilde_fenced_code_preserved(self):
        """~~~ fenced code blocks are also preserved."""
        code = "~~~\ncode\n~~~"
        result = normalize_newlines(code)
        self.assertEqual(result, code)

    def test_no_newlines(self):
        """Plain text without newlines passes through unchanged."""
        self.assertEqual(normalize_newlines("hello"), "hello")

    def test_empty_string(self):
        self.assertEqual(normalize_newlines(""), "")

    def test_newline_before_bullet_list_upgraded_to_blank(self):
        """\n before the FIRST bullet item must become \n\n; between items stays bare."""
        result = normalize_newlines("prose\n- item1\n- item2")
        self.assertNotIn("  \n-", result)
        self.assertIn("\n\n- item1", result)
        # Consecutive list items must NOT get \n\n -> tight list, no <p> per item.
        self.assertNotIn("\n\n- item2", result)
        self.assertIn("\n- item2", result)

    def test_newline_before_numbered_list_upgraded_to_blank(self):
        result = normalize_newlines("intro\n1. first\n2. second")
        self.assertNotIn("  \n1", result)
        self.assertIn("\n\n1. first", result)
        # Items within the list stay tight.
        self.assertNotIn("\n\n2. second", result)
        self.assertIn("\n2. second", result)

    def test_newline_before_heading_stays_bare(self):
        """# headings can interrupt paragraphs leave the \n bare (not hard break, not \n\n)."""
        result = normalize_newlines("text\n## Heading")
        self.assertNotIn("  \n#", result)
        self.assertNotIn("\n\n#", result)
        self.assertIn("\n## Heading", result)

    def test_newline_before_table_row_upgraded_to_blank(self):
        result = normalize_newlines("text\n| a | b |\n|---|---|")
        self.assertNotIn("  \n|", result)
        self.assertIn("\n\n| a | b |", result)

    def test_newline_before_blockquote_stays_bare(self):
        "> blockquotes can interrupt paragraphs leave the \n bare."
        result = normalize_newlines("text\n> quoted")
        self.assertNotIn("  \n>", result)
        self.assertNotIn("\n\n>", result)
        self.assertIn("\n> quoted", result)

    def test_bold_inline_not_mistaken_for_list(self):
        """**bold** starting a line is prose, not a list gets a hard break."""
        result = normalize_newlines("line1\n**bold** text")
        self.assertIn("  \n**bold**", result)


class PostprocessHtmlTests(unittest.TestCase):
    """Tests for postprocess_html behaviour."""

    def test_blank_p_between_consecutive_paragraphs(self):
        """An empty <p> should be inserted between adjacent <p> tags."""
        html = "<p>first</p>\n<p>second</p>"
        result = postprocess_html(html)
        self.assertIn("<p></p>", result)

    def test_no_blank_between_heading_and_paragraph(self):
        """A heading followed by a paragraph should NOT get a blank <p>."""
        html = "<h2>Title</h2>\n<p>Body</p>"
        result = postprocess_html(html)
        self.assertNotIn("<p></p>", result)

    def test_extra_nl_sentinel_expanded(self):
        """EXTRA_NL:2 sentinel should produce 2 blank <p> elements."""
        html = "<p>A</p>\n<!-- EXTRA_NL:2 -->\n<p>B</p>"
        result = postprocess_html(html)
        # Should have the sentinel expanded AND the consecutive-<p> blank.
        self.assertEqual(result.count("<p></p>"), 3) # 1 from adjacency + 2 from sentinel

    def test_blockquote_unwrapped(self):
        """<blockquote> paragraphs should get left-margin style."""
        html = "<blockquote><p>quoted</p></blockquote>"
        result = postprocess_html(html)
        self.assertNotIn("<blockquote>", result)
        self.assertIn("margin-left", result)


class DocxNewlineOutputTests(unittest.TestCase):
    """End-to-end tests that verify newline handling produces correct DOCX output."""

    def test_double_newline_produces_blank_paragraph(self):
        """\\n\\n in content should produce a visible gap (empty paragraph) in DOCX."""
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.docx"
            output_path = Path(tmp) / "output.docx"

            template = Document()
            template.add_paragraph("{{ CONTENT || Provide content }}")
            template.save(template_path)

            store = SectionStore({
                "CONTENT": SectionRecord(
                    prompt="Provide content",
                    output="First paragraph\n\nSecond paragraph",
                    source="json",
                ),
            })

            process_template_docx(template_path=template_path, output_path=output_path, system_prompt="sys", model="m", syntax=TemplateSyntax(), store=store, generate=lambda *_: "unused")

            result = Document(output_path)
            texts = [p.text for p in result.paragraphs]
            # There should be an empty paragraph between the two content paragraphs
            self.assertIn("First paragraph", texts)
            self.assertIn("Second paragraph", texts)
            first_idx = texts.index("First paragraph")
            second_idx = texts.index("Second paragraph")
            self.assertGreater(second_idx - first_idx, 1, "Expected blank paragraph between content")

    def test_triple_newline_produces_extra_blank(self):
        """\\n\\n\\n should produce more spacing than \\n\\n."""
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.docx"
            output_path = Path(tmp) / "output.docx"

            template = Document()
            template.add_paragraph("{{ CONTENT || Provide content }}")
            template.save(template_path)

            store = SectionStore({
                "CONTENT": SectionRecord(
                    prompt="Provide content",
                    output="Top\n\n\nBottom",
                    source="json",
                ),
            })

            process_template_docx(template_path=template_path, output_path=output_path, system_prompt="sys", model="m", syntax=TemplateSyntax(), store=store, generate=lambda *_: "unused")

            result = Document(output_path)
            texts = [p.text for p in result.paragraphs]
            self.assertIn("Top", texts)
            self.assertIn("Bottom", texts)
            top_idx = texts.index("Top")
            bottom_idx = texts.index("Bottom")
            gap = bottom_idx - top_idx
            self.assertGreater(gap, 2, "Expected at least 2 blank paragraphs for \\n\\n\\n")


if __name__ == "__main__":
    unittest.main()
