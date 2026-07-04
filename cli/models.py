"""Renderer-neutral structured models shared by the CLI and the HTML visualizer.

Both the interactive CLI (`router.py`) and the HTML diagnostics panel
(`visualizer.py`) describe the same underlying workflow tasks. Historically each
built its own ad-hoc strings, which let the two surfaces drift out of sync. These
dataclasses hold the description in a presentation-neutral form and expose one
renderer per surface, so a task is only ever *described* once.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Any
import html as _html

from cli.knowledge import type_display_name


@dataclass
class MechanicSection:
    """A titled group of plain-text bullet lines describing task mechanics."""
    heading: str
    bullets: List[str] = field(default_factory=list)


@dataclass
class PayloadBlock:
    """A live-data payload record: ordered key/value rows plus an optional note."""
    heading: str
    rows: List[Tuple[str, Any]] = field(default_factory=list)
    note: str = ''


@dataclass
class TaskInsight:
    """A presentation-neutral description of a single workflow task."""
    task_id: str
    name: str
    type_code: str
    bo: str = ''
    subtitle: str = ''
    mechanics: List[MechanicSection] = field(default_factory=list)
    synopsis: str = ''
    payload_blocks: List[PayloadBlock] = field(default_factory=list)
    routes: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    def display_subtitle(self):
        return self.subtitle or type_display_name(self.type_code)

    @staticmethod
    def format_payload_rows_cli(rows, indent="        "):
        """Shared 3-column payload row formatter used by the CLI renderer."""
        lines = []
        items = list(rows)
        for idx in range(0, len(items), 3):
            chunk = items[idx:idx + 3]
            row_str = "  |  ".join([f"{k}: '{v}'" for k, v in chunk])
            lines.append(f"{indent}* {row_str}")
        return lines

    def render_cli(self):
        out = [f"Deep Logic Analysis: '{self.name}' (ID: {self.task_id}, Type {self.type_code}, BO: {self.bo})"]
        for sec in self.mechanics:
            out.append(f"  [{sec.heading}]:")
            for bullet in sec.bullets:
                out.append(f"    - {bullet}")
        if self.synopsis:
            out.append("")
            out.append("  [Plain English Synopsis]:")
            out.append(f"    {self.synopsis}")
        for blk in self.payload_blocks:
            out.append("")
            out.append(f"  [{blk.heading}]:")
            if blk.note:
                out.append(f"    {blk.note}")
            out.extend(self.format_payload_rows_cli(blk.rows))
        if self.routes:
            out.append(f"  - Routes To: {', '.join(self.routes)}")
        for flag in self.flags:
            out.append(f"  [!] {flag}")
        return "\n".join(out)

    def render_html(self):
        def esc(value):
            return _html.escape(str(value))

        parts = [
            f"<h3>Task: {esc(self.name)}</h3>",
            f"<b>Type:</b> {esc(self.type_code)} ({esc(self.display_subtitle())})<br/>",
            f"<b>ID:</b> {esc(self.task_id)}<br/>",
            f"<b>Context:</b> {esc(self.bo)}<hr/>",
        ]

        body = []
        for sec in self.mechanics:
            bullets = "<br/>".join([f"&bull; {esc(b)}" for b in sec.bullets])
            body.append(f"<b>{esc(sec.heading)}:</b><br/>{bullets}")
        if self.synopsis:
            body.append(f"<b>Synopsis:</b><br/>{esc(self.synopsis)}")
        for blk in self.payload_blocks:
            note = f"<i>{esc(blk.note)}</i><br/>" if blk.note else ""
            rows = "<br/>".join([f"&bull; {esc(k)}: {esc(v)}" for k, v in blk.rows])
            body.append(f"<b>{esc(blk.heading)}:</b><br/>{note}{rows}")
        if self.routes:
            body.append("<b>Routes To:</b><br/>" + "<br/>".join([f"&bull; {esc(r)}" for r in self.routes]))

        if not body:
            body.append("<i>No explicit payload mechanics mapped for this task.</i>")

        parts.append("<br/><br/>".join(body))
        return "".join(parts)
