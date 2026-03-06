from copy import deepcopy

from docx import Document


REQUIRED_STYLES = (
    "List Bullet",
    "List Number",
    "Heading 1",
    "Heading 2",
    "Heading 3",
    "Heading 4",
    "Heading 5",
    "Heading 6",
    "Table Grid",
)


def _copy_numbering_part_if_missing(doc: Document, baseline: Document) -> None:
    """Copy the numbering part from baseline to doc if doc is missing it."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.parts.numbering import NumberingPart

    try:
        doc.part.numbering_part
        return
    except KeyError:
        pass

    try:
        bl_num = baseline.part.numbering_part
    except KeyError:
        return

    new_part = NumberingPart(
        PackURI("/word/numbering.xml"),
        bl_num.content_type,
        deepcopy(bl_num._element),
        doc.part.package,
    )
    doc.part.relate_to(new_part, RT.NUMBERING)


def ensure_required_styles(doc: Document) -> None:
    """Ensure the document has all styles required for Markdown conversion."""
    existing_names = {s.name for s in doc.styles}
    missing = [n for n in REQUIRED_STYLES if n not in existing_names]
    if not missing:
        return

    baseline = Document()
    styles_elem = doc.styles._element

    for name in missing:
        try:
            styles_elem.append(deepcopy(baseline.styles[name].element))
        except KeyError:
            pass # not in baseline either

    # List styles reference numbering IDs copy the numbering part too.
    _copy_numbering_part_if_missing(doc, baseline)
