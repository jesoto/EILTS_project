"""Parser de libros Cambridge IELTS (Academic) con texto seleccionable (probado con Cambridge 17).

Solo heurísticas sobre el texto de PyMuPDF: el formato es muy regular. El resultado NO se usa hasta que el
usuario lo verifica en la página «Verificar claves» (una clave mal leída arruina la evaluación).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .schema import (DERIVED_DIR, Group, KeyEntry, ListeningPart, Passage, TestData, WritingTask)

SECTIONS = {"listening", "reading", "writing", "speaking"}
Q_HEADER = re.compile(r"^Questions?\s+(\d+)\s*(?:[–-]|and|&)\s*(\d+)$")
ROMAN = re.compile(r"^(?:i{1,3}|iv|v|vi{0,3}|ix|x|xi|xii)$")
NOISE_HEAD = re.compile(r"^(?:\d{1,3}|Test \d|Listening|Reading|Writing|Speaking|Listening test audio)$", re.I)
NOISE_FOOT = re.compile(r"^(?:\d{1,3}|p\. ?\d+(?:\s+\d+)?|\d+\s+p\. ?\d+|\d+\s+p\. ?\d+\s*p\. ?\d+|Listening test audio)$")


# ------------------------------------------------------------------ limpieza
def page_lines(text: str) -> list[str]:
    """Líneas de una página sin cabeceras/pies (números de página, «Test 1», «Reading», «p. 119»…)."""
    lines = [ln.replace("\t", " ").replace(" ", " ").rstrip() for ln in text.split("\n")]
    lines = [ln for ln in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    head = 0
    while head < min(3, len(lines)) and NOISE_HEAD.match(lines[head].strip()):
        head += 1
    lines = lines[head:]
    while lines and (NOISE_FOOT.match(lines[-1].strip()) or not lines[-1].strip()):
        lines.pop()
    return lines


def merge_markers(lines: list[str]) -> list[str]:
    """Reconstruye líneas legibles de un grupo de preguntas.

    - «11» / «A» / «ii» / «•» sueltos se unen con la línea siguiente.
    - Un número al final de línea es un hueco de respuesta: «The 1» + «of London…» → «The 1 ____ of London…».
    """
    lines = [ln.strip() for ln in lines if ln.strip()]
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur, used = lines[i], 1
        if (re.fullmatch(r"\d{1,2}", cur) or re.fullmatch(r"[A-L]", cur) or ROMAN.match(cur) or cur == "•")                 and i + 1 < len(lines):
            cur, used = f"{cur} {lines[i + 1]}", 2
        if i + used < len(lines) and re.search(r"[A-Za-z,;:)]\s\d{1,2}$", cur)                 and re.match(r"[a-z]", lines[i + used]) and not re.match(r"\d{1,2} |[A-L] ", cur):
            cur, used = f"{cur} ____ {lines[i + used]}", used + 1
        out.append(cur)
        i += used
    return out


# ------------------------------------------------------------------ clasificación
def classify_group(text: str) -> str:
    t = text.lower()
    if "true" in t and "false" in t and "not given" in t:
        return "tfng"
    if "yes" in t and "no" in t and "not given" in t and ("agree with the claims" in t or "views of the writer" in t
                                                          or "yes" in t.split("write")[-1]):
        return "ynng"
    if re.search(r"choose (two|three|four|five) letters", t):
        return "multi"
    if "list of headings" in t or "correct heading" in t:
        return "matching_headings"
    if re.search(r"which (paragraph|section) contains|(paragraph|section) contains the following", t):
        return "matching_info"
    if "correct ending" in t or "complete each sentence with the correct ending" in t:
        return "sentence_endings"
    if "label the map" in t or "label the plan" in t or "label the diagram" in t:
        return "labelling"
    if t.startswith(("match", "look at the following")) or "match each" in t or "classify the following" in t:
        return "matching"
    if "choose the correct letter" in t:
        return "mcq"
    if re.search(r"complete the|write (one|no more)|no more than|one word|summary|choose .* from the (box|list)", t):
        return "completion"
    return "other"


# ------------------------------------------------------------------ grupos de preguntas
def split_groups(lines: list[str]) -> tuple[list[str], list[Group]]:
    """Devuelve (líneas previas a la primera cabecera «Questions», grupos)."""
    headers: list[tuple[int, int, int]] = []     # (idx_línea, start, end)
    first_idx = None
    for i, ln in enumerate(lines):
        m = Q_HEADER.match(ln.strip())
        if m:
            if headers and headers[-1][0] == i - 1:      # «Questions 11–20» seguido de «Questions 11–14»
                headers[-1] = (i, int(m.group(1)), int(m.group(2)))
            else:
                headers.append((i, int(m.group(1)), int(m.group(2))))
                if first_idx is None:
                    first_idx = i
    if not headers:
        return lines, []
    pre = lines[:first_idx]
    groups = []
    for k, (idx, a, b) in enumerate(headers):
        end_idx = headers[k + 1][0] if k + 1 < len(headers) else len(lines)
        body = lines[idx + 1:end_idx]
        merged = merge_markers(body)
        instr = " ".join(merged[:6])
        groups.append(Group(start=a, end=b, type=classify_group(instr), instruction=" ".join(merged[:3]),
                            text="\n".join(merged)))
    return pre, groups


# ------------------------------------------------------------------ claves
def parse_key_block(lines: list[str]) -> list[KeyEntry]:
    """Parsea líneas de una sección de claves: «1» / respuesta, «15&16 IN EITHER ORDER» / A / D."""
    out: list[KeyEntry] = []
    i = 0
    clean = [ln.strip() for ln in lines if ln.strip()]
    skip = re.compile(r"^(Answer key with extra explanations|in Resource Bank|Part \d, Questions.*|Reading Passage \d,.*|"
                      r"Questions \d+.*|If you score.*)$", re.I)
    while i < len(clean):
        ln = clean[i]
        m_pair = re.match(r"^(\d+)\s*&\s*(\d+)(?:\s+IN EITHER ORDER)?$", ln)
        if m_pair:
            a, b = int(m_pair.group(1)), int(m_pair.group(2))
            j = i + 1
            if j < len(clean) and clean[j].upper() == "IN EITHER ORDER":
                j += 1
            ans = clean[j:j + 2]
            out.append(KeyEntry(qnums=[a, b], answers=[_alts(ans[0])] + ([_alts(ans[1])] if len(ans) > 1 else []),
                                any_order=True))
            i = j + 2
            continue
        m = re.match(r"^(\d{1,2})$", ln)
        if m and i + 1 < len(clean):
            out.append(KeyEntry(qnums=[int(m.group(1))], answers=[_alts(clean[i + 1])]))
            i += 2
            continue
        if ln.startswith("If you score"):
            break
        if skip.match(ln):
            i += 1
            continue
        i += 1
    return out


def _alts(raw: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\s+/\s+|\s*/\s*(?=[A-Za-z0-9])", raw) if p.strip()]
    return parts or [raw.strip()]


# ------------------------------------------------------------------ escritura
def writing_type(prompt: str, task: int) -> str:
    t = prompt.lower()
    if task == 1:
        for kw, name in [("map", "map"), ("diagram", "process"), ("process", "process"), ("pie chart", "pie"),
                         ("table", "table"), ("bar chart", "bar"), ("line graph", "line"), ("graph", "line"),
                         ("chart", "bar")]:
            if kw in t:
                return "mixed" if ("bar chart" in t and "line graph" in t) else name
        return "other"
    if "discuss both views" in t or "discuss both these views" in t:
        return "discussion"
    if "outweigh" in t:
        return "advantages_disadvantages"
    if "solution" in t or "measures" in t:
        return "problem_solution"
    if "to what extent" in t or "do you agree" in t or "agree or disagree" in t:
        return "opinion"
    if re.search(r"\bwhy\b.*\?", t):
        return "double_question"
    return "other"


def parse_writing(lines: list[str], task: int) -> str:
    text = " ".join(ln.strip() for ln in lines)
    m = re.search(r"minutes on this task\.\s*(.*?)(Write at least \d+ words\.)", text, re.S)
    return (m.group(1) + m.group(2)).strip() if m else text[:600]


# ------------------------------------------------------------------ libro completo
def _classify_pages(pages: list[str], first: int, last: int) -> dict[tuple[int, str], list[int]]:
    """Asigna cada página de contenido a (test, sección) con una máquina de estados."""
    cur_test, cur_sec = 0, ""
    assign: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i in range(first, last):
        raw = [ln.strip() for ln in pages[i].split("\n") if ln.strip()]
        head, foot = raw[:3], raw[-3:]
        for ln in head + foot:
            m = re.fullmatch(r"Test (\d)", ln)
            if m:
                cur_test = int(m.group(1))
        for ln in head:
            if ln.lower() in SECTIONS:
                cur_sec = ln.lower()
        if cur_test and cur_sec:
            assign[(cur_test, cur_sec)].append(i + 1)
    return assign


def _paragraphs(lines: list[str]) -> str:
    lens = sorted(len(ln) for ln in lines if ln.strip())
    median = lens[len(lens) // 2] if lens else 80
    paras, cur = [], []
    for ln in lines:
        s = ln.strip()
        if re.fullmatch(r"[A-H]", s):
            if cur:
                paras.append(" ".join(cur))
            cur = [f"[{s}]"]
            continue
        cur.append(s)
        if s.endswith((".", "?", "!", ".”", "’")) and len(s) < 0.6 * median:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


def parse_audioscripts(pages: list[str], start: int, end: int) -> dict[tuple[int, int], str]:
    """{(test, part): transcripción}."""
    lines: list[str] = []
    for i in range(start, end):
        pl = [ln.strip() for ln in pages[i].split("\n")]
        pl = [ln for ln in pl if ln and not re.fullmatch(r"\d{1,3}", ln) and ln != "Audioscripts"
              and not re.fullmatch(r"Test \d", ln)]
        lines += pl
    out: dict[tuple[int, int], list[str]] = {}
    test = part = 0
    for ln in lines:
        m_t = re.fullmatch(r"TEST (\d)", ln)
        m_p = re.fullmatch(r"PART (\d)", ln)
        if m_t:
            test = int(m_t.group(1))
            continue
        if m_p:
            part = int(m_p.group(1))
            out.setdefault((test, part), [])
            continue
        if test and part:
            out[(test, part)].append(ln.replace("\t", " "))
    return {k: "\n".join(v) for k, v in out.items()}


def find_marker_page(pages: list[str], pattern: str, after: int = 0) -> int | None:
    rx = re.compile(pattern, re.S)
    for i in range(after, len(pages)):
        if rx.search(pages[i]):
            return i
    return None


def map_audio_c17(resources: Path, book_dir: str) -> dict[tuple[int, int], str]:
    out = {}
    for p in (resources / book_dir).rglob("*.mp3"):
        m = re.fullmatch(r"T(\d) AUDIO (\d)", p.stem)
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = str(p.relative_to(resources)).replace("\\", "/")
    return out


def map_audio_c16(resources: Path, book_dir: str) -> dict[tuple[int, int], str]:
    out = {}
    for p in (resources / book_dir).rglob("*.mp3"):
        m = re.fullmatch(r"TEST (\d) PARTE (\d)", p.stem, re.I)
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = str(p.relative_to(resources)).replace("\\", "/")
    return out


def parse_book(pdf_path: Path, book: str, book_title: str, audio_map: dict[tuple[int, int], str],
               out_root: Path | None = None, render_images: bool = True) -> list[TestData]:
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    pages = [p.get_text() for p in doc]

    first = find_marker_page(pages, r"Test 1\s+LISTENING\s+PART 1")
    audio_start = find_marker_page(pages, r"^\s*Audioscripts?\s+TEST 1\s+PART 1", after=(first or 0) + 1) \
        or find_marker_page(pages, r"Audioscripts?\s*\n\s*TEST 1", after=(first or 0) + 1)
    keys_start = find_marker_page(pages, r"Listening and Reading answer keys\s+TEST 1", after=(audio_start or 0))
    if None in (first, audio_start, keys_start):
        raise ValueError(f"No se reconoció la estructura de {pdf_path.name}: first={first} audio={audio_start} keys={keys_start}")
    sample_start = find_marker_page(pages, r"Sample Writing answers", after=keys_start + 1) or len(pages)
    # las claves terminan donde empiezan los «Sample Writing answers»
    assign = _classify_pages(pages, first, audio_start)
    scripts = parse_audioscripts(pages, audio_start, keys_start)

    # ---- claves por test
    key_pages_text: dict[tuple[int, str], list[str]] = defaultdict(list)
    key_page_nums: dict[int, list[int]] = defaultdict(list)
    cur_t, cur_s = 0, ""
    for i in range(keys_start, sample_start):
        for ln in [x.strip() for x in pages[i].split("\n") if x.strip()]:
            m = re.fullmatch(r"TEST (\d)", ln)
            if m:
                cur_t, cur_s = int(m.group(1)), ""
            elif ln in ("LISTENING", "READING"):
                cur_s = ln.lower()
            elif cur_t and cur_s:
                key_pages_text[(cur_t, cur_s)].append(ln)
        if cur_t:
            key_page_nums[cur_t].append(i + 1)

    tests: list[TestData] = []
    test_numbers = sorted({t for t, _ in assign})
    for n in test_numbers:
        td = TestData(book=book, book_title=book_title, test=n, source_pdf=pdf_path.name,
                      key_pages=sorted(set(key_page_nums.get(n, []))))
        # ---- Listening
        lines: list[str] = []
        for pg in assign.get((n, "listening"), []):
            lines += page_lines(pages[pg - 1]) + ["\f"]
        td.listening = _listening_parts(lines, n, scripts, audio_map, assign.get((n, "listening"), []))
        # ---- Reading
        rl: list[str] = []
        for pg in assign.get((n, "reading"), []):
            rl += page_lines(pages[pg - 1]) + ["\f"]
        td.reading = _reading_passages(rl, assign.get((n, "reading"), []))
        # ---- Writing
        for pg in assign.get((n, "writing"), []):
            wl = page_lines(pages[pg - 1])
            body = [ln for ln in wl if ln.strip()]
            joined = "\n".join(body)
            m = re.search(r"WRITING TASK (\d)", joined)
            if not m:
                continue
            task = int(m.group(1))
            prompt = parse_writing(body, task)
            wt = WritingTask(task=task, prompt=prompt, task_type=writing_type(prompt, task), page=pg)
            if render_images and task == 1:
                img = (out_root or DERIVED_DIR) / book / "images" / f"test{n}_task1.png"
                img.parent.mkdir(parents=True, exist_ok=True)
                doc[pg - 1].get_pixmap(dpi=130).save(str(img))
                wt.image = f"{book}/images/{img.name}"
            td.writing.append(wt)
        # ---- Imágenes de las páginas de clave (la página «Verificar claves» las muestra sin necesitar el PDF)
        if render_images:
            for pg in td.key_pages:
                img = (out_root or DERIVED_DIR) / book / "images" / f"test{n}_key_p{pg}.png"
                img.parent.mkdir(parents=True, exist_ok=True)
                doc[pg - 1].get_pixmap(dpi=85).save(str(img))
                td.key_images.append(f"{book}/images/{img.name}")
        # ---- Claves
        td.key_listening = parse_key_block(key_pages_text.get((n, "listening"), []))
        td.key_reading = parse_key_block(key_pages_text.get((n, "reading"), []))
        refine_types(td)
        td.notes += validate(td)
        tests.append(td)
    return tests


def _listening_parts(lines, test, scripts, audio_map, pages) -> list[ListeningPart]:
    chunks: dict[int, list[str]] = {}
    part = 0
    for ln in lines:
        m = re.fullmatch(r"PART (\d)", ln.strip())
        if m:
            part = int(m.group(1))
            chunks.setdefault(part, [])
        elif ln.strip() == "\f":
            continue
        elif part:
            chunks[part].append(ln)
    out = []
    for p, body in sorted(chunks.items()):
        pre, groups = split_groups(body)
        qs = [q for g in groups for q in (g.start, g.end)]
        out.append(ListeningPart(part=p, qstart=min(qs, default=0), qend=max(qs, default=0), groups=groups,
                                 transcript=scripts.get((test, p), ""), audio=audio_map.get((test, p)), pages=pages))
    return out


def _reading_passages(lines, pages) -> list[Passage]:
    chunks: dict[int, list[str]] = {}
    n = 0
    for ln in lines:
        m = re.fullmatch(r"READING PASSAGE (\d)", ln.strip())
        if m:
            n = int(m.group(1))
            chunks.setdefault(n, [])
        elif ln.strip() == "\f":
            continue
        elif n:
            chunks[n].append(ln)
    out = []
    for k, body in sorted(chunks.items()):
        pre, groups = split_groups(body)
        # quitar instrucción «You should spend about 20 minutes… below.» y sacar el título
        idx = next((i for i, ln in enumerate(pre) if ln.strip().endswith("below.")), -1)
        rest = pre[idx + 1:] if idx >= 0 else pre
        title = rest[0].strip() if rest else ""
        text_lines = rest[1:]
        letters = sorted({ln.strip() for ln in text_lines if re.fullmatch(r"[A-H]", ln.strip())})
        qs = [q for g in groups for q in (g.start, g.end)]
        out.append(Passage(n=k, title=title, text=_paragraphs(text_lines), qstart=min(qs, default=0),
                           qend=max(qs, default=0), groups=groups, paragraph_letters=letters, pages=pages))
    return out


# ------------------------------------------------------------------ tipos de entrada y validación
TFNG = {"TRUE", "FALSE", "NOT GIVEN"}
YNNG = {"YES", "NO", "NOT GIVEN"}


def refine_types(td: TestData) -> None:
    """Decide cómo se contesta cada grupo mirando su clave (más fiable que el enunciado)."""
    for skill, units in (("listening", td.listening), ("reading", td.reading)):
        km = td.key_map(skill)
        for u in units:
            letters_in_passage = getattr(u, "paragraph_letters", [])
            for g in u.groups:
                answers = []
                for q in g.qnums:
                    e = km.get(q)
                    if e:
                        answers.append(e.answers[e.qnums.index(q)] if not e.any_order else
                                       [a for al in e.answers for a in al])
                flat = {a.strip().upper() for al in answers for a in al}
                if flat and flat <= TFNG and "NOT GIVEN" in flat | {"NOT GIVEN"} and g.type in ("tfng", "other", "completion"):
                    if flat <= TFNG and (g.type == "tfng" or "TRUE" in flat or "FALSE" in flat):
                        g.type, g.input, g.options = "tfng", "tfng", ["TRUE", "FALSE", "NOT GIVEN"]
                        continue
                if flat and flat <= YNNG and ("YES" in flat or "NO" in flat):
                    g.type, g.input, g.options = "ynng", "ynng", ["YES", "NO", "NOT GIVEN"]
                    continue
                if flat and all(ROMAN.match(a.lower()) for al in answers for a in al):
                    g.input = "headings"
                    found = [m for m in re.findall(r"^([ivx]+) ", g.text, re.M) if ROMAN.match(m)]
                    g.options = sorted(set(found) | {a.lower() for al in answers for a in al}, key=_roman_value)
                    g.type = "matching_headings"
                    continue
                if flat and all(re.fullmatch(r"[A-L]", a) for a in flat):
                    g.input = "choice"
                    opts = {m for m in re.findall(r"^([A-L]) ", g.text, re.M)}
                    rng = re.search(r"letter[s]?,? ([A-L])\s*[–-]\s*([A-L])", g.instruction + " " + g.text[:300])
                    if rng:      # «Write the correct letter, A–G»
                        opts |= {chr(c) for c in range(ord(rng.group(1)), ord(rng.group(2)) + 1)}
                    if g.type == "matching_info" and letters_in_passage:
                        opts |= set(letters_in_passage)
                    g.options = sorted(opts | flat)
                    if g.type == "other":
                        g.type = "mcq"
                    continue
                g.input = "text"


def _roman_value(r: str) -> int:
    vals = {"i": 1, "v": 5, "x": 10}
    total = 0
    for a, b in zip(r, r[1:] + " "):
        total += -vals[a] if b in vals and vals[b] > vals[a] else vals[a]
    return total


def validate(td: TestData) -> list[str]:
    """Avisos automáticos para la revisión humana."""
    notes = []
    for skill, units in (("listening", td.listening), ("reading", td.reading)):
        km = td.key_map(skill)
        got = set(km)
        if got != set(range(1, 41)):
            missing = sorted(set(range(1, 41)) - got)
            extra = sorted(got - set(range(1, 41)))
            notes.append(f"{skill}: la clave no cubre 1-40 (faltan {missing}, sobran {extra})")
        covered = {q for u in units for g in u.groups for q in g.qnums}
        if covered != set(range(1, 41)):
            notes.append(f"{skill}: los grupos de preguntas no cubren 1-40 (faltan {sorted(set(range(1, 41)) - covered)})")
        if skill == "listening":
            for p in td.listening:
                if not p.audio:
                    notes.append(f"listening: falta el audio de la Parte {p.part}")
                if len(p.transcript) < 200:
                    notes.append(f"listening: transcripción de la Parte {p.part} vacía o muy corta")
        else:
            for p in td.reading:
                if len(p.text) < 1500:
                    notes.append(f"reading: el pasaje {p.n} parece demasiado corto ({len(p.text)} caracteres)")
    if len(td.writing) != 2:
        notes.append(f"writing: se esperaban 2 tareas y hay {len(td.writing)}")
    return notes
