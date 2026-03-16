import re


def _convert_blockquotes(soup) -> None:
    """Convert blockquotes to indented paragraphs."""
    for bq in soup.find_all("blockquote"):
        for child in bq.find_all(["p", "pre"]):
            existing = child.get("style", "")
            child["style"] = ("margin-left: 720;" + existing) if existing else "margin-left: 720;"
        bq.unwrap()


def _flatten_list_item_paragraphs(soup) -> None:
    """Unwrap the leading paragraph in a list item so numbering stays inline."""
    from bs4 import Tag

    for li in soup.find_all("li"):
        child_tags = [child for child in li.children if isinstance(child, Tag)]
        if not child_tags or child_tags[0].name != "p":
            continue

        first_paragraph = child_tags[0]
        for child in tuple(first_paragraph.contents):
            first_paragraph.insert_before(child.extract())
        first_paragraph.extract()


def _ordered_list_content_with_space(node):
    """Ensure the first visible token in a node starts with a separating space."""
    from bs4 import Tag
    from bs4.element import NavigableString

    if isinstance(node, NavigableString):
        if node and not node[0].isspace():
            return NavigableString(" " + str(node))
        return node

    if isinstance(node, Tag):
        first_text = node.find(string=True)
        if first_text is not None and first_text and not first_text[0].isspace():
            first_text.replace_with(NavigableString(" " + str(first_text)))
    return node


def _append_numbered_content(paragraph, node, *, first_content_done: bool) -> bool:
    """Append ordered-list content to a numbered paragraph and track first content."""
    from bs4 import Tag

    if isinstance(node, Tag) and node.name == "p":
        for nested in tuple(node.contents):
            if not first_content_done and str(nested).strip():
                nested = _ordered_list_content_with_space(nested)
                first_content_done = True
            paragraph.append(nested.extract())
        return first_content_done

    if not first_content_done and str(node).strip():
        node = _ordered_list_content_with_space(node)
        first_content_done = True
    paragraph.append(node)
    return first_content_done


def _convert_ordered_list_item(soup, li, number: int):
    """Convert one ordered-list item into a numbered paragraph plus nested lists."""
    from bs4 import Tag

    paragraph = soup.new_tag("p")
    paragraph.append(f"{number}.")
    nested_lists = []
    first_content_done = False

    for child in tuple(li.contents):
        if isinstance(child, Tag) and child.name in ("ul", "ol"):
            nested_lists.append(child.extract())
            continue
        first_content_done = _append_numbered_content(paragraph, child.extract(), first_content_done=first_content_done)

    if not first_content_done:
        paragraph.append(" ")
    return [paragraph, *nested_lists]


def _convert_ordered_lists_to_numbered_paragraphs(soup) -> None:
    """Replace <ol> lists with explicit numbered paragraphs to avoid DOCX list carry-over."""
    for ol in soup.find_all("ol"):
        if ol.find_parent("div", class_="footnote") is not None:
            continue

        replacement_nodes = []
        start = int(ol.get("start", 1) or 1)
        for offset, li in enumerate(ol.find_all("li", recursive=False)):
            replacement_nodes.extend(_convert_ordered_list_item(soup, li, start + offset))

        for node in reversed(replacement_nodes):
            ol.insert_after(node)
        ol.extract()


def _normalize_semantic_inline_tags(soup) -> None:
    """Map semantic inline tags to style-rich spans for reliable DOCX conversion."""
    for tag in soup.find_all("del"):
        tag.name = "span"
        existing = tag.get("style", "")
        tag["style"] = f"text-decoration: line-through;{existing}" if existing else "text-decoration: line-through;"

    for tag in soup.find_all("sup"):
        tag.name = "span"
        existing = tag.get("style", "")
        tag["style"] = f"vertical-align: super; font-size: 75%;{existing}" if existing else "vertical-align: super; font-size: 75%;"

    for tag in soup.find_all("sub"):
        tag.name = "span"
        existing = tag.get("style", "")
        tag["style"] = f"vertical-align: sub; font-size: 75%;{existing}" if existing else "vertical-align: sub; font-size: 75%;"


def _convert_horizontal_rules(soup) -> None:
    """Convert <hr> into a visible paragraph separator in DOCX output."""
    for hr in soup.find_all("hr"):
        p = soup.new_tag("p")
        p.string = "________________________________________"
        hr.insert_after(p)
        hr.extract()


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
        _flatten_list_item_paragraphs(soup)
        _convert_ordered_lists_to_numbered_paragraphs(soup)
        _normalize_semantic_inline_tags(soup)
        _convert_horizontal_rules(soup)
        _insert_blank_paragraphs(soup)
        _expand_extra_newline_comments(soup)
        return str(soup)

    except ImportError: # bs4 unavailable - simple string fallback
        html = re.sub(r"<li>\s*<p>(.*?)</p>(\s*<(?:ul|ol)>)", r"<li>\1\2", html, flags=re.DOTALL)
        html = re.sub(r"</p>\s*<p>", "</p>\n<p></p>\n<p>", html)
        html = re.sub(r"<!-- EXTRA_NL:(\d+) -->", lambda m: "<p></p>" * int(m.group(1)), html)
        return html
