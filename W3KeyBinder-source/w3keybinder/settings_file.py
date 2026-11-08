"""Reading and writing Witcher 3 ``input.settings`` files (and mod snippets in the same format).

Format::

    [Exploration]
    IK_W=(Action=GI_AxisLeftY,State=Axis,Value=1)
    IK_Q=(Action=CastSign,State=Duration,IdleTime=0.2)

Anything that is not a section header or a binding line (comments, blank lines,
prose in a mod README) is kept verbatim so we never destroy data we don't understand.
"""
from __future__ import annotations

import codecs
import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Union

SECTION_RE = re.compile(r"^\s*\[([A-Za-z0-9_ .\-]+)\]\s*$")
# IK_Key=(params) with an optional trailing comment: "// note", "; note" or "# note"
ENTRY_RE = re.compile(r"^\s*(IK_[A-Za-z0-9_]+)\s*=\s*\(((?:[^()]|\([^()]*\))*)\)\s*;?\s*((?://|;|#|--).*)?$")


def normalize_params(params: str) -> str:
    """Canonical form of the text inside the parentheses (no stray whitespace)."""
    return ",".join(p.strip() for p in params.split(",") if p.strip())


def parse_params(params: str) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {}
    for part in params.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part] = None
    return out


@dataclass
class Entry:
    key: str
    params: str  # normalized text inside the parentheses
    comment: str = ""  # trailing comment, kept as written

    def __post_init__(self) -> None:
        self.params = normalize_params(self.params)

    @property
    def parsed(self) -> dict[str, Optional[str]]:
        return parse_params(self.params)

    @property
    def action(self) -> Optional[str]:
        return self.parsed.get("Action")

    @property
    def value(self) -> Optional[str]:
        v = self.parsed.get("Value")
        if v is None:
            return None
        try:  # "1.0" and "1" are the same axis half
            f = float(v)
            return str(int(f)) if f == int(f) else str(f)
        except ValueError:
            return v

    @property
    def action_id(self) -> Optional[str]:
        a = self.action
        if not a:
            return None
        v = self.value
        return f"{a}|{v}" if v is not None else a

    def line(self) -> str:
        return f"{self.key}=({self.params})" + (f" {self.comment}" if self.comment else "")

    @property
    def marked_for_removal(self) -> bool:
        """Mod instructions mark lines to take out with a comment such as '// DELETE'."""
        c = self.comment.lower()
        if re.search(r"\b(?:do\s*n[o']?t|never|don't)\s+(?:delete|remove)", c):
            return False  # "// do not remove"
        return bool(re.search(r"\b(?:delete|remove)\b", c))

    def same(self, other: "Entry") -> bool:
        return self.key == other.key and self.params == other.params


Item = Union[Entry, str]


@dataclass
class Section:
    name: str
    items: list[Item] = field(default_factory=list)

    def entries(self) -> Iterator[Entry]:
        for it in self.items:
            if isinstance(it, Entry):
                yield it

    def has(self, entry: Entry) -> bool:
        return any(e.same(entry) for e in self.entries())


@dataclass
class SettingsDoc:
    preamble: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    encoding: str = "utf-8"
    newline: str = "\r\n"
    orphan_entries: int = 0  # binding lines seen before any [Section]

    # ---------- queries ----------
    def section(self, name: str, create: bool = False) -> Optional[Section]:
        for s in self.sections:
            if s.name == name:
                return s
        if create:
            s = Section(name)
            self.sections.append(s)
            return s
        return None

    def iter_entries(self) -> Iterator[tuple[str, Entry]]:
        for s in self.sections:
            for e in s.entries():
                yield s.name, e

    def entry_count(self) -> int:
        return sum(1 for _ in self.iter_entries())

    def context_names(self) -> list[str]:
        return [s.name for s in self.sections]

    def clone(self) -> "SettingsDoc":
        return copy.deepcopy(self)

    # ---------- edits ----------
    def add(self, context: str, entry: Entry, index: Optional[int] = None) -> bool:
        """Add entry if an identical line isn't already in the section. Returns True if added."""
        sec = self.section(context, create=True)
        assert sec is not None
        if sec.has(entry):
            return False
        if index is None:
            # insert after the last entry so trailing blank lines stay at the end
            last = max((i for i, it in enumerate(sec.items) if isinstance(it, Entry)), default=-1)
            sec.items.insert(last + 1, entry)
        else:
            sec.items.insert(index, entry)
        return True

    # ---------- serialization ----------
    def to_text(self) -> str:
        lines: list[str] = list(self.preamble)
        for s in self.sections:
            lines.append(f"[{s.name}]")
            for it in s.items:
                lines.append(it.line() if isinstance(it, Entry) else it)
            if not lines or lines[-1].strip() != "":
                lines.append("")
        return self.newline.join(lines)


def parse_text(text: str) -> SettingsDoc:
    doc = SettingsDoc()
    current: Optional[Section] = None
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        m = SECTION_RE.match(line)
        if m:
            name = m.group(1).strip()
            current = doc.section(name) or doc.section(name, create=True)
            continue
        m = ENTRY_RE.match(line)
        if m and current is not None:
            current.items.append(Entry(m.group(1), m.group(2), (m.group(3) or "").strip()))
            continue
        if m and current is None:
            doc.orphan_entries += 1
        if current is None:
            doc.preamble.append(line)
        else:
            current.items.append(line)
    # strip trailing blank lines inside sections; to_text re-adds one separator
    for s in doc.sections:
        while s.items and isinstance(s.items[-1], str) and not s.items[-1].strip():
            s.items.pop()
    while doc.preamble and not doc.preamble[-1].strip():
        doc.preamble.pop()
    return doc


def read_text_any(path: Union[str, Path]) -> tuple[str, str]:
    """Read a text file whatever its encoding. Returns (text, encoding-used-for-writing)."""
    data = Path(path).read_bytes()
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16"), "utf-16"
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    # UTF-16 without BOM: lots of NUL bytes in odd positions
    if len(data) >= 4 and data[1:200:2].count(0) > len(data[1:200:2]) * 0.8:
        return data.decode("utf-16-le", errors="replace"), "utf-16-le"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def load(path: Union[str, Path]) -> SettingsDoc:
    text, enc = read_text_any(path)
    doc = parse_text(text)
    doc.encoding = enc
    doc.newline = "\r\n" if "\r\n" in text or "\n" not in text else "\n"
    return doc


def save(doc: SettingsDoc, path: Union[str, Path]) -> None:
    text = doc.to_text()
    if not text.endswith(doc.newline):
        text += doc.newline
    # newline="" so Python doesn't turn \r\n into \r\r\n on Windows
    with open(path, "w", encoding=doc.encoding, newline="") as f:
        f.write(text)
