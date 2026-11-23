"""A force scheduler's fields, as its master says them: its `all_fields`, the specs of Buildbot's parameters, nested as
its force form nests them (Buildbot's master/buildbot/schedulers/forcesched.py and data/forceschedulers.py, read on
2026-11-23). The platform's Force… form offers what the master's own web UI offers, each under the name the force
takes it by, and the force sends each value under that name alone, once it has been checked as its field says.

- A parameter's spec holds its name, its fullName, its label, its type, its default, whether it is required and
  hidden, and its type's own (a list's choices, and whether it is strict). A nest ("nested") holds its own in
  `fields`: the scheduler's first (the user's name, the reason, the priority; its name empty), each codebase's (its
  name the codebase's, labelled "Codebase: <name>" unless its master.cfg labels it), and those its master.cfg adds
  (its properties). A field's fullName is its nest's fullName, an underscore and its own name when both are set, else
  whichever is: a codebase app's branch is app_branch, the unnamed codebase's the plain branch.
- The force reads each value by its field's fullName and lets go of every other name it is sent, without a word, and
  a fixed field (FixedParameter) gives its own value whatever is sent: so a value is sent here only under a name the
  scheduler takes and does not fix, or it is refused in words before anything is sent.
- Offered: text, textarea and username (a line of text; a branch and a revision without a space), int (a whole
  number), bool (yes or no), list (one of its choices; any text for one that names none). Not offered: fixed (the
  scheduler's own value), a field the web UI hides, file (an upload) and a type of a parameter's own. A required
  field that is not offered leaves the scheduler without a form here, and its force is refused: the master's web UI
  forces it."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

TEXT_MOST = 200  # characters of a value typed on the page (a builder's name, a reason, a branch ...), at most
FIELDS_MOST = 40  # a scheduler's fields one form offers, at most: one with more is forced from the master's web UI
LEAVES_MOST = 200  # fields read of a scheduler's all_fields, at most
NESTS_MOST = 4  # nests within nests read, at most
CHOICES_MOST = 200  # a list's choices offered, at most
LABEL_MOST = 80  # characters of a label, at most
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")  # a field's fullName as this page sends it: a form field's name
OFFERED = {"text": "text", "textarea": "text", "username": "text", "int": "number", "bool": "choice",
           "list": "choice"}  # the types of Buildbot's parameters offered, as the platform's form fields them
YES, NO = ("true", "yes", "on", "1"), ("false", "no", "off", "0")
FIELD = "field:"  # a form's name for one of the scheduler's fields: its fullName after this (never the force's own)
SPACELESS = ("branch", "revision")  # the fields (by their own name) whose value holds no space


def typed(value, what: str, spaces: bool = True) -> str:
    """A value typed on the page: "" for none; ValueError in words for one too long, holding a line break or a control
    character, or a space where none goes (a branch, a revision)."""
    said = str(value if value is not None else "").strip()
    if not said:
        return ""
    if len(said) > TEXT_MOST:
        raise ValueError(f"{what} is {TEXT_MOST} characters at most")
    if any(ord(c) < 32 or ord(c) == 127 for c in said):
        raise ValueError(f"{what} holds a line break or a control character")
    if not spaces and any(c.isspace() for c in said):
        raise ValueError(f"{what} holds no space")
    return said


def label_of(value) -> str:
    """A label as the page says it: on one line, without the colon Buildbot's labels end in, its first letter a
    capital, LABEL_MOST characters at most; "" for none."""
    if not isinstance(value, str):
        return ""
    said = " ".join(value.split()).rstrip(":").strip()
    if len(said) > LABEL_MOST:
        said = said[:LABEL_MOST - 1] + "…"
    return said[:1].upper() + said[1:]


@dataclass(frozen=True)
class Field:
    """One of a force scheduler's fields (a leaf of its all_fields): its fullName (the name the force takes its value
    by), its own name, its label as the page says it (its nests' labels before its own: "Codebase: app · Branch"), its
    type as the master says it, its default, whether it is required, whether the web UI hides it (it or a nest it is
    in), a list's choices and whether they are all it takes (strict)."""

    full: str
    name: str
    label: str
    kind: str
    default: object = ""
    required: bool = False
    hidden: bool = False
    choices: tuple[str, ...] = ()
    strict: bool = True

    def not_offered(self) -> str:
        """Why the page offers no field for it, in words; "" when it offers one."""
        if self.kind == "fixed":
            return "the scheduler fixes its value"
        if self.hidden:
            return "the master's web UI hides it"
        if not NAME.match(self.full):
            return "its name is not one this page sends"
        if self.kind not in OFFERED:
            return f"a field of type {self.kind or 'none'} is not filled from this page"
        return ""

    def own(self) -> str:
        """What it takes when it is left empty, in words: the scheduler's own value, said when it has one."""
        d = self.default
        if isinstance(d, bool):
            shown = "yes" if d else "no"
        elif isinstance(d, int):
            shown = str(d)
        elif isinstance(d, str):
            shown = " ".join(d.split())[:60]
        else:
            shown = ""
        return f"the scheduler's own ({shown})" if shown else "the scheduler's own"

    def value(self, value):
        """The value typed, as the force takes it (a whole number for an int, true or false for a bool, a text else);
        ValueError in words for one that is not this field's."""
        what = f"{self.label} ({self.full})"
        if self.kind == "int":
            if isinstance(value, bool):
                raise ValueError(f"{what} is a whole number")
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                if value.is_integer():
                    return int(value)
                raise ValueError(f"{what} is a whole number")
            try:
                return int(typed(value, what, spaces=False))
            except ValueError:
                raise ValueError(f"{what} is a whole number") from None
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            said = typed(value, what, spaces=False).lower()
            if said in YES or said in NO:
                return said in YES
            raise ValueError(f"{what} is yes or no")
        if not isinstance(value, str):
            raise ValueError(f"{what} is a text")
        said = typed(value, what, spaces=self.name not in SPACELESS)
        if self.kind == "list" and self.strict and self.choices and said not in self.choices:
            shown = ", ".join(self.choices[:20]) + (" …" if len(self.choices) > 20 else "")
            raise ValueError(f"{what} is one of its choices: {shown}")
        return said


def fields_of(scheduler) -> list[Field]:
    """A force scheduler's fields (its all_fields' leaves), in the master's order: NESTS_MOST nests deep and
    LEAVES_MOST in all at most, each labelled with its nests' labels before its own."""
    out: list[Field] = []

    def walk(nodes, labels: tuple[str, ...], hidden: bool, depth: int) -> None:
        for node in nodes if isinstance(nodes, list) else ():
            if len(out) >= LEAVES_MOST:
                return
            if not isinstance(node, Mapping):
                continue
            kind = node.get("type") if isinstance(node.get("type"), str) else ""
            hide = hidden or node.get("hide") is True
            own = label_of(node.get("label"))
            if kind == "nested":
                if depth < NESTS_MOST:
                    walk(node.get("fields"), (*labels, own) if own else labels, hide, depth + 1)
                continue
            full = node.get("fullName")
            if not isinstance(full, str) or not full:
                continue
            name = node.get("name") if isinstance(node.get("name"), str) else ""
            given = node.get("choices")
            choices = tuple(c for c in given if isinstance(c, str))[:CHOICES_MOST] if isinstance(given, list) else ()
            out.append(Field(full, name, " · ".join((*labels, own or label_of(name) or full)), kind,
                             node.get("default"), node.get("required") is True, hide, choices,
                             node.get("strict") is not False))

    walk(scheduler.get("all_fields") if isinstance(scheduler, Mapping) else None, (), False, 0)
    return out


def offered(fields: list[Field]) -> list[Field]:
    """The fields a form offers, each fullName once (the first, as the force reads one value by it)."""
    seen: set[str] = set()
    out = []
    for f in fields:
        if not f.not_offered() and f.full not in seen:
            seen.add(f.full)
            out.append(f)
    return out


def unfillable(fields: list[Field]) -> Field | None:
    """The first field the scheduler needs that this page cannot fill (a required file, a required field the web UI
    hides, one of a type of its own); None when there is none."""
    return next((f for f in fields if f.required and f.kind != "fixed" and f.not_offered()), None)


def form_field(f: Field) -> dict:
    """The platform's form field for one of the scheduler's (liminal-platform's status.forms): named FIELD and its
    fullName, labelled as the web UI labels it, its default said as the scheduler's own; a bool and a list with
    choices are a choice, an int a number, the rest a text."""
    own = f.own()
    out = {"name": FIELD + f.full, "label": f.label, "note": f"sent as {f.full}" + (" (needed)" if f.required else ""),
           "required": f.required}
    if f.kind == "bool":
        choices = [("true", "yes"), ("false", "no")]
    elif f.kind == "list" and f.choices:
        choices = [(c, c) for c in f.choices]
    else:
        return {**out, "type": "number" if OFFERED.get(f.kind) == "number" else "text", "empty": own,
                "placeholder": own}
    rows = ([] if f.required else [{"value": "", "title": own}]) + [{"value": v, "title": t} for v, t in choices]
    return {**out, "type": "choice", "value": rows[0]["value"], "empty": own, "choices": rows}


def typed_fields(names, values) -> dict:
    """The values typed for a scheduler's fields by their fullNames (`names`: the names the form sent them under, ", "
    between them; `values`: one each, in that order), those left empty left out. ValueError in words, before anything
    is asked, for a name that is none or given twice, more values than names, a value that is neither a text, a number
    nor true or false, and a text too long or holding a line break."""
    listed = [n.strip() for n in str(names).split(",")] if names is not None and str(names).strip() else []
    bad = next((n for n in listed if not NAME.match(n)), None)
    if bad is not None:
        raise ValueError("the fields are named as the scheduler names them (letters, digits, _, . and -), a comma "
                         f"between them: not {bad[:60]!r}")
    twice = next((n for i, n in enumerate(listed) if n in listed[:i]), None)
    if twice is not None:
        raise ValueError(f"the field {twice} is named twice")
    if len(listed) > LEAVES_MOST:
        raise ValueError(f"{len(listed)} fields: {LEAVES_MOST} at most")
    if len(values) > len(listed):
        raise ValueError(f"{len(values)} values for {len(listed)} fields named: one value each, in their order")
    out: dict = {}
    for name, value in zip(listed, values):
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, (bool, int, float)):
            out[name] = value
        elif isinstance(value, str):
            out[name] = typed(value, f"the value for {name}")
        else:
            raise ValueError(f"the value for {name} is a text, a number, or true or false")
    return out
