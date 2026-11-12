"""
test_editor_i18n.py: the page of `docpipe edit` in German.

The promise, in one sentence: every text the page shows has a German version
in its catalogue (docpipe/editor/ui/src/i18n/de.json). Each part of it is a
test of its own, with a case that breaks it by construction:

1. Every text the sources of the page write goes through t() or tn() with a
   literal, AND every such literal has a German entry.
2. No text a person reads stands in the sources outside t(), tn() or tr():
   no JSX text, no visible attribute (label, title, placeholder, ...), no
   visible property of an object (label:, title:, ...), no words handed to
   a dialog or an error.
3. Every explanation the server sends the page for both profiles (the
   library of the flow, its conditions, numbers, switches and notes, the
   rules of every tab and of the graph, the help of the spec form, the
   details of the sources, the notes of the prompts) has a German entry,
   as it stands or, where the server fills in names, by one of the
   server's templates (i18n/templates.json).
4. A German entry keeps the {names} of its English key; a template is none
   of the page's own texts AND has words of its own besides its names.
5. Every sentence the page is told about the request logs (the numbers of
   the flow, `measured.SAID`) comes in each of its forms AND finds its German
   by its template.
6. A server text the page shows as an element goes through rich(), so its
   `code` shows as code and not as backticks.

What comes from a source (the spec, the ontology, a prompt, a document, a
check of the pipeline) is shown as it is and is not asked for here.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "docpipe" / "editor" / "ui" / "src"
CATALOGUE = UI / "i18n" / "de.json"
TEMPLATES = UI / "i18n" / "templates.json"

VISIBLE_ATTRS = {"label", "title", "placeholder", "description",
                 "aria-label", "alt", "error"}
VISIBLE_PROPS = {"label", "title", "placeholder", "description", "message",
                 "word", "says", "help", "text"}
DIALOGS = {"askConfirm", "showInfo", "showError", "askText", "Error"}
# the literal arguments of each translating call: t(text, vars),
# tn(count, one, many, vars)
LITERALS = {"t": (0,), "tn": (1, 2)}
LETTER = re.compile(r"[A-Za-zÄÖÜäöüß]")
ENTITY = re.compile(r"&#?\w+;")
NAME = re.compile(r"\{(\w+)\}")


def wordy(text: str) -> bool:
    return bool(LETTER.search(ENTITY.sub("", text)))


class Scan:
    """One file of the page's sources, read as TypeScript with JSX: the keys
    of its t()/tn() calls, and the texts a person reads that do not go
    through them (`bare`). A line that carries `i18n-ignore` is shown as it
    is on purpose."""

    def __init__(self, text: str, name: str = "<text>.tsx"):
        self.s, self.name, self.i = text, name, 0
        self.jsx = name.endswith(".tsx")     # a .ts file has no elements
        self.keys: list = []       # (key, where)
        self.bare: list = []       # (text, where, why)
        self.prev = self.prev2 = None
        self.stack: list = []      # open brackets: {"name", "arg", "seen"}
        self.code(None)

    # -- where ---------------------------------------------------------------
    def where(self, at: int) -> str:
        return f"{self.name}:{self.s.count(chr(10), 0, at) + 1}"

    def ignored(self, at: int) -> bool:
        start = self.s.rfind("\n", 0, at) + 1
        end = self.s.find("\n", at)
        return "i18n-ignore" in self.s[start:len(self.s) if end < 0 else end]

    def flag(self, text: str, at: int, why: str) -> None:
        if wordy(text) and not self.ignored(at):
            self.bare.append((" ".join(text.split()), self.where(at), why))

    # -- reading -------------------------------------------------------------
    def string(self) -> str:
        quote, i, out = self.s[self.i], self.i + 1, []
        while self.s[i] != quote:
            if self.s[i] == "\\":
                nxt = self.s[i + 1]
                out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                i += 2
                continue
            out.append(self.s[i])
            i += 1
        self.i = i + 1
        return "".join(out)

    def template(self) -> str:
        i, out = self.i + 1, []
        while self.s[i] != "`":
            if self.s[i] == "\\":
                out.append(self.s[i + 1])
                i += 2
            elif self.s.startswith("${", i):
                self.i = i + 2
                self.code("}", fresh=True)
                i = self.i
                out.append("{}")
            else:
                out.append(self.s[i])
                i += 1
        self.i = i + 1
        return "".join(out)

    def regex(self) -> None:
        i, klass = self.i + 1, False
        while True:
            c = self.s[i]
            if c == "\\":
                i += 2
                continue
            if c == "[":
                klass = True
            elif c == "]":
                klass = False
            elif c == "/" and not klass:
                break
            i += 1
        i += 1
        while i < len(self.s) and self.s[i].isalpha():
            i += 1
        self.i = i

    def regex_here(self) -> bool:
        p = self.prev
        marks = set("(,=:[!&|?{};+-*%<>~^") | {"=>", "&&", "||", "??"}
        return (p is None or (p[0] == "p" and p[1] in marks)
                or (p[0] == "w" and p[1] in ("return", "typeof", "case")))

    def jsx_here(self) -> bool:
        p, nxt = self.prev, self.s[self.i + 1:self.i + 2]
        if not self.jsx or not (nxt.isalpha() or nxt == ">"):
            return False
        if not (p is None or (p[0] == "p" and p[1] in
                              ("(", ",", "=", ":", "?", "[", "{", ";", "&&",
                               "||", "??", "=>", "!"))
                or (p[0] == "w" and p[1] == "return")):
            return False
        # a generic <T,> or <T extends U> of an arrow function
        m = re.match(r"<\s*\w+\s*(,|extends\b)", self.s[self.i:])
        return m is None

    # -- the token stream ----------------------------------------------------
    def token(self, kind: str, value, at: int) -> None:
        top = self.stack[-1] if self.stack else None
        if top is not None and top["name"] in LITERALS:
            if top["seen"] == 0 and top["arg"] in LITERALS[top["name"]]:
                if kind == "str":
                    self.keys.append((value, self.where(at)))
                    top["key_at"] = top["arg"]
                elif not self.ignored(at):
                    self.bare.append((str(value), self.where(at),
                                      f"{top['name']}() without a literal"))
            elif top.get("key_at") == top["arg"] and kind == "p" \
                    and value == "+":
                self.bare.append(("+", self.where(at),
                                  f"{top['name']}() literal glued to more"))
            top["seen"] += 1
        elif top is not None:
            if kind in ("str", "tmpl") and top["seen"] == 0 \
                    and top["name"] in DIALOGS:
                self.flag(value, at, f"words handed to {top['name']}()")
            top["seen"] += 1
        if kind in ("str", "tmpl") and self.prev == ("p", ":") \
                and self.prev2 is not None and self.prev2[0] == "w" \
                and self.prev2[1] in VISIBLE_PROPS and top is not None \
                and top["name"] == "{":
            self.flag(value, at, f"visible property {self.prev2[1]}:")
        self.prev2, self.prev = self.prev, (kind, value)

    def code(self, until, fresh: bool = False) -> None:
        """Reads code up to the "}" that closes *until* (None: the end)."""
        base = len(self.stack)
        if fresh:
            self.prev = self.prev2 = None
        s = self.s
        while self.i < len(s):
            c, at = s[self.i], self.i
            if c.isspace():
                self.i += 1
            elif s.startswith("//", at):
                end = s.find("\n", at)
                self.i = len(s) if end < 0 else end
            elif s.startswith("/*", at):
                self.i = s.index("*/", at) + 2
            elif c in "\"'":
                self.token("str", self.string(), at)
            elif c == "`":
                self.token("tmpl", self.template(), at)
            elif c.isalpha() or c in "_$":
                m = re.match(r"[\w$]+", s[at:])
                word = m.group(0)
                self.i += len(word)
                self.token("w", word, at)
            elif c.isdigit():
                m = re.match(r"[\w.]+", s[at:])
                self.i += len(m.group(0))
                self.token("n", m.group(0), at)
            elif c == "<" and self.jsx_here():
                self.token("jsx", None, at)
                self.element()
                self.prev = ("jsx", None)
            elif c == "/" and self.regex_here():
                self.regex()
                self.token("re", None, at)
            elif c in "([{":
                name = self.prev[1] if c == "(" and self.prev is not None \
                    and self.prev[0] == "w" else c
                if c == "(" and self.prev2 == ("p", "."):
                    name = "." + name     # obj.t( is not t(
                self.token("p", c, at)
                self.stack.append({"name": name, "arg": 0, "seen": 0})
                self.i += 1
                self.prev = ("p", c)
            elif c in ")]}":
                if c == "}" and until == "}" and len(self.stack) == base:
                    self.i += 1
                    return
                if self.stack:
                    self.stack.pop()
                self.i += 1
                self.prev2, self.prev = self.prev, ("p", c)
            elif c == ",":
                if self.stack:
                    self.stack[-1]["arg"] += 1
                    self.stack[-1]["seen"] = 0
                self.i += 1
                self.prev2, self.prev = self.prev, ("p", c)
            else:
                m = re.match(r"=>|&&|\|\||\?\?|\?\.|\.\.\.|[^\w\s]", s[at:])
                op = m.group(0)
                self.i += len(op)
                self.token("p", op, at)

    # -- JSX -----------------------------------------------------------------
    def name_here(self) -> str:
        m = re.match(r"[\w$.:-]*", self.s[self.i:])
        self.i += len(m.group(0))
        return m.group(0)

    def blank(self) -> None:
        while self.s[self.i].isspace():
            self.i += 1

    def element(self) -> None:
        """Reads one element from its "<" to its end."""
        self.i += 1
        if self.s[self.i] == ">":
            self.i += 1
            self.children()
            return
        self.name_here()
        while True:
            self.blank()
            c = self.s[self.i]
            if self.s.startswith("/>", self.i):
                self.i += 2
                return
            if c == ">":
                self.i += 1
                self.children()
                return
            if c == "{":
                self.i += 1
                self.code("}", fresh=True)
                continue
            attr, at = self.name_here(), self.i
            if not attr:
                raise SyntaxError(f"{self.where(self.i)}: cannot read {c!r}")
            self.blank()
            if self.s[self.i] != "=":
                continue
            self.i += 1
            self.blank()
            c, at = self.s[self.i], self.i
            if c in "\"'":
                value = self.string()
                if attr in VISIBLE_ATTRS:
                    self.flag(value, at, f"attribute {attr}")
            elif c == "{":
                self.i += 1
                self.code("}", fresh=True)
            elif c == "<":
                self.element()

    def children(self) -> None:
        while True:
            start = self.i
            while self.s[self.i] not in "<{":
                self.i += 1
            self.flag(self.s[start:self.i], start, "JSX text")
            if self.s[self.i] == "{":
                self.i += 1
                self.code("}", fresh=True)
                continue
            if self.s.startswith("</", self.i):
                self.i = self.s.index(">", self.i) + 1
                return
            self.element()


def sources() -> list:
    """The page's sources, without the one that defines t() and tr()."""
    return sorted(p for p in UI.rglob("*") if p.suffix in (".ts", ".tsx")
                  and p != UI / "lib" / "i18n.tsx")


def scans() -> list:
    return [Scan(p.read_text(encoding="utf-8"), p.relative_to(UI).as_posix())
            for p in sources()]


def catalogue() -> dict:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def server_templates() -> list:
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))


def template_words(key: str) -> int:
    """Letters of a key besides its {names}: a template needs six at least,
    or "{subject} {prop}" would fit any text (as `templateWords`)."""
    return len(LETTER.findall(NAME.sub("", key)))


def german(text: str, german_of: dict, templates: list | None = None):
    """The German of a server text: the entry of the text, or of the
    server's template it fits; None where there is none (as `tr` in
    lib/i18n.tsx)."""
    if text in german_of:
        return german_of[text]
    if templates is None:
        templates = server_templates()
    for key in sorted((k for k in templates if k in german_of
                       and NAME.search(k) and template_words(k) >= 6),
                      key=lambda k: -len(NAME.sub("", k))):
        body = "".join("(.+?)" if NAME.fullmatch(part) else re.escape(part)
                       for part in re.split(r"(\{\w+\})", key))
        if re.fullmatch(body, text, re.S):
            return german_of[key]
    return None


# -- what the server sends ----------------------------------------------------

def _texts_of(shown, paths: tuple) -> list:
    """The strings at *paths* of an answer: "a.b[].c" walks keys and lists,
    "*" every value of an object."""
    out = []

    def walk(node, parts):
        if not parts:
            if isinstance(node, str) and node:
                out.append(node)
            elif isinstance(node, list):
                out.extend(x for x in node if isinstance(x, str) and x)
            return
        head, rest = parts[0], parts[1:]
        if node is None:
            return
        if head in ("*", "*[]"):
            for value in (node.values() if isinstance(node, dict) else node):
                if head == "*":
                    walk(value, rest)
                elif isinstance(value, list):
                    for item in value:
                        walk(item, rest)
        elif head.endswith("[]"):
            for item in (node.get(head[:-2]) or []):
                walk(item, rest)
        elif isinstance(node, dict):
            walk(node.get(head), rest)

    for path in paths:
        walk(shown, path.split("."))
    return out


ANSWERS = {
    "/api/flow": (
        "library.boxes[].label", "library.boxes[].says",
        "library.boxes[].fixed", "library.boxes[].marks",
        "library.boxes[].settings[].label", "library.boxes[].settings[].help",
        "library.boxes[].settings[].words.*", "library.each.*",
        "library.each_titles.*", "library.which.*", "library.order_words.*",
        "library.arrows.*", "conditions[].label", "conditions[].props[].label",
        "conditions[].props[].words.*", "numbers[].help", "notes[].says",
        "switches.*.label", "switches.*.none", "never.*",
        # every question is "Ask the model" with a preset (owner decision
        # 2026-11-12 evening): the presets, the forms of an answer, the
        # targets and how an input is shown
        "library.presets[].label", "library.presets[].says",
        "library.presets[].settings[].label",
        "library.presets[].settings[].help",
        "library.presets[].settings[].words.*",
        "library.forms.*.label", "library.forms.*.says",
        "library.targets.*.label", "library.targets.*.says",
        "shows.*.label", "shows.*.says"),
    "/api/spec": ("form.*[].help", "form.*[].about"),
    "/api/prompts": ("traces_note", "try.why"),
    "/api/graph": ("rules[].group", "rules[].help", "skipped",
                   "bricks[].does", "bricks[].takes", "bricks[].gives",
                   "bricks[].settings[].help"),
    "/api/sources": ("kinds.*.stands", "differences.skipped",
                     "differences.fields[].rows[].detail",
                     "differences.fields[].rows[].entries[].why",
                     "differences.unasked[].detail"),
}
# Rows of the sources comparison that taking into the spec refuses, one per
# reason that needs no shapes (`sourcespage.take`).
REFUSED_ROWS = ({"id": "no_kind|x", "action": "add"},
                {"id": "list_missing|x", "action": "add"},
                {"id": "list_missing|no_field||path|iri", "action": "add"},
                {"id": "definition_rewritten|no_field||key",
                 "action": "replace"},
                {"id": "not_asked|no_shape|path", "action": "merge"})
RULE_TABS = ("spec", "prompts", "flow", "sources", "graph")
# What the server explains of one flow of a follow-up pass.
PASS_ANSWER = ("library.boxes[].label", "library.boxes[].says",
               "library.boxes[].fixed", "library.boxes[].marks",
               "library.boxes[].settings[].label",
               "library.boxes[].settings[].help",
               "library.boxes[].settings[].words.*", "library.each.*",
               "library.each_titles.*", "problems[].message",
               "not_started", "library.presets[].label",
               "library.presets[].says",
               "library.presets[].settings[].label",
               "library.presets[].settings[].help",
               "library.presets[].settings[].words.*",
               "library.forms.*.label", "library.forms.*.says",
               "library.targets.*.label", "library.targets.*.says")


def server_texts() -> dict:
    """{text: where} of every explanation the server sends the page of
    both profiles, and the fixed sentences of its reports."""
    from docpipe.editor import (flow as flow_view, flowtry, graphpage,
                                phrases, prompts, rulespage, server,
                                sourcespage, trying)
    from docpipe.profile import load_profile

    out: dict = {}
    for name in ("kwp", "scenarios"):
        profile = load_profile(name)
        app = server.App(profile, None, REPO)
        app.spec_path = Path(profile.package_dir) / "extraction_spec.json"
        for url, paths in ANSWERS.items():
            status, shown = app.call("GET", url, {}, None)
            assert status == 200, (name, url, shown)
            for text in _texts_of(shown, paths):
                out.setdefault(text, f"{name} {url}")
        # Every flow of a follow-up pass, as the server sends it by name.
        status, passes = app.call("GET", "/api/flow/passes", {}, None)
        assert status == 200, (name, passes)
        for one in passes["passes"]:
            status, shown = app.call("GET", "/api/flow/pass",
                                     {"name": one["name"]}, None)
            assert status == 200, (name, one["name"], shown)
            for text in _texts_of(shown, PASS_ANSWER):
                out.setdefault(text, f"{name} pass {one['name']}")
        for tab in RULE_TABS:
            status, shown = app.call("GET", "/api/rules", {"tab": tab},
                                     None)
            assert status == 200, (name, tab, shown)
            for text in _texts_of(shown, ("rules[].group", "rules[].help",
                                          "cost")):
                out.setdefault(text, f"{name} rules {tab}")
        spec_raw = json.loads(app.spec_path.read_text(encoding="utf-8"))
        taken = sourcespage.take(spec_raw, list(REFUSED_ROWS), None, profile,
                                 [])
        for refused in taken["refused"]:
            out.setdefault(refused["why"], f"{name} sources take")
    for text in (*rulespage.COST.values(), flow_view.STALE, graphpage.COST,
                 graphpage.GATE, sourcespage.COST, prompts.NO_STALE,
                 phrases.NO_STALE, trying.NO_MODEL, flowtry.ORDER_SAID):
        out.setdefault(text, "report")
    for text in measured_texts():
        out.setdefault(text, "measured")
    return out


def measured_texts() -> list:
    """Every sentence `measured.says` and `measured.notes` write, in each of
    their forms: what request logs of one request of each kind say, of two,
    and of none asked again."""
    from docpipe.editor import measured

    numbers = {"search_pieces": 3, "listed_field_factor": 2,
               "search_per_request": 1, "follow_ups": 1, "replies": 1,
               "list_meanings": 1}
    out = []
    for n, noted in ((1, True), (2, False), (1_234, True)):
        found = {
            "requests": n, "steps": {},
            "searches": [{"requests": 2, "noted": noted, "after": after,
                          "found": True} for after in range(1, n + 1)],
            "docfields": {"plain": [4] * n, "listed": [7] * n},
            "read": {1: n} if n == 1 else {1: n - 1, 2: 1},
            "unreadable": {"syntax": n},
            "follow": {"find": n} if noted else {},
            "lists": [2] * n}
        for said in measured.says(found, numbers).values():
            out.extend(said)
        out.extend(measured.notes(found))
    return out


# -- 1. the page's own texts --------------------------------------------------

def test_every_text_of_the_page_has_its_german():
    german_of = catalogue()
    keys = [(key, where) for scan in scans() for key, where in scan.keys]
    assert keys, "the page writes no text through t()"
    missing = sorted({f"{where}: {key!r}" for key, where in keys
                      if not german_of.get(key)})
    assert not missing, "no German for:\n" + "\n".join(missing)
    # the failure by construction: a key the catalogue does not have
    made_up = Scan("const a = t('A sentence no catalogue has, made up.');")
    assert [k for k, _ in made_up.keys if not german_of.get(k)] \
        == ["A sentence no catalogue has, made up."]


def test_a_count_takes_both_of_its_texts():
    found = Scan("x = tn(n, '{n} document', '{n} documents', { a: 1 });")
    assert [k for k, _ in found.keys] == ["{n} document", "{n} documents"]
    assert not found.bare
    # the failure by construction: a text built from a variable
    loose = Scan("x = t(word); y = t('Saved ' + file);")
    assert [why for _, _, why in loose.bare] == [
        "t() without a literal", "t() literal glued to more"]


# -- 2. nothing a person reads outside the catalogue --------------------------

def test_no_text_of_the_page_stands_outside_the_catalogue():
    bare = [f"{where}: {text!r} ({why})" for scan in scans()
            for text, where, why in scan.bare]
    assert not bare, "\n".join(bare)


@pytest.mark.parametrize("source, why", [
    ("const a = <Text>Save the file</Text>;", "JSX text"),
    ('const a = <Button title="Save it" />;', "attribute title"),
    ("const a = <Tooltip label='Undo'><b /></Tooltip>;", "attribute label"),
    ("const o = { value: 'x', label: 'Numbers' };",
     "visible property label:"),
    ("askConfirm('Discard changes', t('Sure?'), t('Discard'));",
     "words handed to askConfirm()"),
    ("throw new Error('The server cannot be reached');",
     "words handed to Error()"),
    ("const f = (n) => cond ? <A /> : <p>{n} items left</p>;", "JSX text"),
])
def test_a_bare_text_is_found(source, why):
    # the failures by construction: each source shows a text untranslated
    assert [w for _, _, w in Scan(source).bare] == [why]


def test_what_is_no_text_is_left_alone():
    source = """
        const id = (s: string) => s.replace(/a<b/g, 'x');
        const clone = <T,>(v: T): T => v;
        if (a < b && c > d) x = useState<Set<string>>(new Set());
        const o = { value: 'numbers', label: t('Numbers'), color: 'teal' };
        const e = <Box className="dp-x" data-x="y">{t('Text')} · →</Box>;
        const n = <Text>{/* a comment */}{count}&nbsp;</Text>;
        const k = { label: 'Deutsch' }; // i18n-ignore
    """
    found = Scan(source)
    assert found.bare == []
    assert [k for k, _ in found.keys] == ["Numbers", "Text"]


# -- 3. what the server explains ----------------------------------------------

@pytest.fixture(scope="module")
def explained():
    return server_texts()


def test_every_explanation_of_the_server_has_its_german(explained):
    german_of = catalogue()
    assert len(explained) > 100, "the server explains almost nothing"
    missing = sorted(f"{where}: {text!r}" for text, where in explained.items()
                     if not german(text, german_of))
    assert not missing, "no German for:\n" + "\n".join(missing)
    # the failure by construction: a server text the catalogue lacks
    assert german("A step no catalogue knows.", german_of) is None


def test_a_template_takes_the_names_a_server_text_carries():
    german_of = {"{key}: no field asks for this property":
                 "{key}: kein Feld fragt nach dieser Eigenschaft"}
    templates = list(german_of)
    assert german("study: no field asks for this property", german_of,
                  templates) \
        == "{key}: kein Feld fragt nach dieser Eigenschaft"
    # the failures by construction: other words around the same name, and
    # a key of names only, which would fit any text
    assert german("study: a field asks for this property", german_of,
                  templates) is None
    assert german("the dimension", {"{subject} {prop}": "{subject} {prop}"},
                  ["{subject} {prop}"]) is None


def test_a_template_is_none_of_the_pages_own_texts():
    german_of = catalogue()
    page = {key for scan in scans() for key, _ in scan.keys}
    wrong = [key for key in server_templates()
             if key in page or not NAME.search(key) or not german_of.get(key)]
    assert not wrong, wrong
    # the failure by construction: the page's own "For each {name}" as a
    # template takes a sentence of the server that has no German
    sentence = "For each chunk a made-up step says what it does."
    assert "For each {name}" in page
    assert german(sentence, german_of, ["For each {name}"]) is not None
    assert german(sentence, german_of) is None


def test_every_sentence_of_the_request_logs_has_its_german():
    from docpipe.editor import measured

    german_of = catalogue()
    said = measured_texts()
    forms = [form for key in measured.SAID
             for form in (measured.SAID[key]
                          if isinstance(measured.SAID[key], tuple)
                          else (measured.SAID[key],))]
    unsaid = [form for form in forms
              if not any(german(text, german_of, [form]) is not None
                         for text in said)]
    assert not unsaid, "never said, so never checked:\n" + "\n".join(unsaid)
    missing = [text for text in said if german(text, german_of) is None]
    assert not missing, "no German for:\n" + "\n".join(missing)
    assert measured.NOT_NOTED in said
    # the failure by construction: the old sentence, glued from pieces and
    # in the old words, has no German
    assert german("108 answers did not hold and were asked again: find 69.",
                  german_of) is None


CHILD = re.compile(r"(?<![=$])\{tr\(")


def test_a_server_text_shows_its_code_as_code():
    bare = [f"{path.relative_to(UI).as_posix()}:"
            f"{text[:m.start()].count(chr(10)) + 1}"
            for path in sources() if path.suffix == ".tsx"
            for text in [path.read_text(encoding="utf-8")]
            for m in CHILD.finditer(text)]
    assert not bare, "a server text shown without rich():\n" \
        + "\n".join(bare)
    # the failure by construction: a text of the server as an element
    # without rich(); as a value of an attribute it is a string
    assert CHILD.search('<Text size="sm">{tr(note)}</Text>')
    assert not CHILD.search('<Text size="sm">{rich(tr(note))}</Text>')
    assert not CHILD.search("<Help text={tr(rule.help)} />")


# -- 4. the catalogue itself --------------------------------------------------

def test_a_german_entry_keeps_the_names_of_its_key():
    wrong = [key for key, said in catalogue().items()
             if sorted(NAME.findall(key)) != sorted(NAME.findall(said or ""))]
    assert not wrong, wrong
    # the failure by construction: a name lost in the German
    key, said = "Saved {file}.", "Gespeichert."
    assert sorted(NAME.findall(key)) != sorted(NAME.findall(said))
