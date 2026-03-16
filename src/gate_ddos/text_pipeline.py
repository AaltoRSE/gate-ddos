from pathlib import Path
from typing import Callable

from .models import TemplateSyntax
from .section_store import SectionStore
from .template_engine import TemplateEngine
from .ui import CliUI
from .utils import read_text


class TextPipeline:
    """Load a text template (.md/.txt), resolve placeholders, and write output."""

    def __init__(
        self,
        system_prompt: str,
        syntax: TemplateSyntax,
        store: SectionStore,
        generate: Callable[[str, str], str],
        *,
        force: bool = False,
        ui: CliUI | None = None,
    ):
        self.engine = TemplateEngine(system_prompt, syntax, store, generate, force=force, ui=ui)
        self.ui = ui

    def process(self, template_path: str | Path, output_path: str | Path) -> None:
        """Read *template_path*, replace placeholders, and write to *output_path*."""
        source = Path(template_path)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        text = read_text(source, "Template")
        if self.ui is not None:
            self.ui.start_template(source, output, self.engine.count(text))
        output.write_text(self.engine.replace(text), encoding="utf-8")
