import re


def _convert_blockquotes(soup) -> None:
    """Convert blockquotes to indented paragraphs."""
    for bq in soup.find_all("blockquote"):
        for child in bq.find_all(["p", "pre"]):
            existing = child.get("style", "")
            child["style"] = ("margin-left: 720;" + existing) if existing else "margin-left: 720;"
        bq.unwrap()


def _insert_blank_paragraphs(soup) -> None:
    """Insert blank paragraphs between consecutive <p> tags."""
    from bs4 import Tag

    top_tags = [c for c in soup.children if isinstance(c, Tag)]
    for i in range(len(top_tags) - 1, 0, -1):
        curr = top_tags[i]
        prev = top_tags[i - 1]
        if curr.name == "p" and prev.name == "p":
            prev.insert_after(soup.new_tag("p"))


def _expand_extra_newline_comments(soup) -> None:
    """Expand EXTRA_NL sentinel comments into blank <p> elements."""
    from bs4 import Comment

    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        m = re.match(r"\s*EXTRA_NL:(\d+)\s*", comment)
        if m:
            count = int(m.group(1))
            ref = comment
            for _ in range(count):
                new_p = soup.new_tag("p")
                ref.insert_after(new_p)
                ref = new_p
            comment.extract()


def postprocess_html(html: str) -> str:
    """Apply post-processing transformations to HTML generated from Markdown to ensure proper DOCX rendering."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        _convert_blockquotes(soup)
        _insert_blank_paragraphs(soup)
        _expand_extra_newline_comments(soup)
        return str(soup)

    except ImportError: # bs4 unavailable - simple string fallback
        html = re.sub(r"</p>\s*<p>", "</p>\n<p></p>\n<p>", html)
        html = re.sub(r"<!-- EXTRA_NL:(\d+) -->", lambda m: "<p></p>" * int(m.group(1)), html)
        return html
