from pathlib import Path

import pytest

from ielts import db
from ielts.ingest import cambridge as cb
from ielts.ingest import review
from ielts.ingest.schema import Group, KeyEntry, ListeningPart, Passage, TestData, load_test, save_test
from ielts.modules import dictation
from ielts.modules import receptive as rc

ROOT = Path(__file__).resolve().parent.parent
C17 = ROOT / "resources" / "Cambriedge IELTS 17 (2022)" / "cambridge_ielts_17_academic.pdf"


# ---------------------------------------------------------------- parser (texto sintético)
def test_page_lines_strips_headers_and_footers():
    page = "Test 1\n18\nQuestions 1–6\nComplete the notes.\nThe 1 \nof London\n\nListening test audio\n12\np. 119"
    assert cb.page_lines(page) == ["Questions 1–6", "Complete the notes.", "The 1", "of London"]


def test_page_lines_keeps_question_number_lines_in_the_middle():
    page = "Reading\n17\nQuestions 7–9\n7\nSome statement\n8\nOther statement"
    assert cb.page_lines(page) == ["Questions 7–9", "7", "Some statement", "8", "Other statement"]


def test_merge_markers():
    assert cb.merge_markers(["11", "What colour?", "A", "dark red", "ii", "A heading", "plain"]) == \
        ["11 What colour?", "A dark red", "ii A heading", "plain"]


def test_classify_group():
    assert cb.classify_group("Do the following statements agree. TRUE if ... FALSE if ... NOT GIVEN if") == "tfng"
    assert cb.classify_group("Choose TWO letters, A–E.") == "multi"
    assert cb.classify_group("Which section contains the following information?") == "matching_info"
    assert cb.classify_group("Choose the correct letter, A, B or C.") == "mcq"
    assert cb.classify_group("Complete the notes. Write ONE WORD ONLY") == "completion"
    assert cb.classify_group("Look at the following list of people") == "matching"


def test_split_groups_keeps_the_later_of_two_consecutive_headers():
    lines = ["intro", "Questions 11–20", "Questions 11–14", "Choose the correct letter, A, B or C.", "11", "q?",
             "A", "x", "Questions 15 and 16", "Choose TWO letters, A–E.", "A", "a", "B", "b"]
    pre, groups = cb.split_groups(lines)
    assert pre == ["intro"]
    assert [(g.start, g.end, g.type) for g in groups] == [(11, 14, "mcq"), (15, 16, "multi")]
    assert "11 q?" in groups[0].text


def test_parse_key_block_with_pairs_and_alternatives():
    lines = ["Part 1, Questions 1–10", "  1", "litter ", "  2", "dogs", "10", "35 / thirty five",
             "Part 2, Questions 11–20", "11", "A ", "15&16 IN EITHER ORDER", "A ", "D ", "17&18", "IN EITHER ORDER", "B", "C",
             "Answer key with extra explanations", "in Resource Bank", "19", "E", "If you score …", "1–15"]
    keys = {e.qnums[0]: e for e in cb.parse_key_block(lines)}
    assert keys[1].answers == [["litter"]] and keys[10].answers == [["35", "thirty five"]]
    assert keys[15].qnums == [15, 16] and keys[15].any_order and keys[15].answers == [["A"], ["D"]]
    assert keys[17].qnums == [17, 18] and keys[17].answers == [["B"], ["C"]]
    assert keys[19].answers == [["E"]]


def test_writing_type():
    assert cb.writing_type("The maps below show a town", 1) == "map"
    assert cb.writing_type("The table below gives", 1) == "table"
    assert cb.writing_type("Discuss both views and give your own opinion.", 2) == "discussion"
    assert cb.writing_type("Do the advantages outweigh the disadvantages?", 2) == "advantages_disadvantages"
    assert cb.writing_type("To what extent do you agree or disagree?", 2) == "opinion"


def mk_test(verified=True) -> TestData:
    tf = Group(start=1, end=3, type="tfng", input="tfng", options=["TRUE", "FALSE", "NOT GIVEN"], text="1 a\n2 b\n3 c")
    tx = Group(start=4, end=5, type="completion", input="text", text="4 The ____\n5 The ____")
    mc = Group(start=6, end=7, type="multi", input="choice", options=list("ABCDE"), text="Choose TWO letters")
    key = [KeyEntry(qnums=[1], answers=[["TRUE"]]), KeyEntry(qnums=[2], answers=[["FALSE"]]),
           KeyEntry(qnums=[3], answers=[["NOT GIVEN"]]),
           KeyEntry(qnums=[4], answers=[["(Sumatran) orangutan", "orang-utan"]]),
           KeyEntry(qnums=[5], answers=[["floor(s)"]]), KeyEntry(qnums=[6, 7], answers=[["A"], ["D"]], any_order=True)]
    return TestData(book="tb", book_title="Test Book Academic", test=1, verified=verified, key_reading=key,
                    reading=[Passage(n=1, title="T", text="Long text. " * 50, qstart=1, qend=7, groups=[tf, tx, mc])],
                    listening=[ListeningPart(part=1, qstart=1, qend=1, groups=[], audio=None)])


# ---------------------------------------------------------------- corrección
def test_expand_answer_variants():
    assert rc.expand_answer("(Sumatran) orangutan") == {"sumatran orangutan", "orangutan"}
    assert rc.expand_answer("floor(s)") == {"floor", "floors"}
    assert rc.expand_answer("Thirty  Five") == {"thirty five"}


def test_grade_reading_with_optional_text_and_either_order():
    td = mk_test()
    ans = {1: "true", 2: "FALSE ", 3: "False", 4: "Orangutan", 5: "FLOORS", 6: "D", 7: "A"}
    res = {r.q: r for r in rc.grade(td, "reading", ans, [1, 2, 3, 4, 5, 6, 7])}
    assert [res[q].correct for q in range(1, 8)] == [True, True, False, True, True, True, True]
    assert res[3].expected == "NOT GIVEN"
    bad = {r.q: r.correct for r in rc.grade(td, "reading", {6: "A", 7: "A"}, [6, 7])}
    assert bad == {6: True, 7: False}        # no se puede repetir la misma letra en la pareja


def test_near_miss_flags_spelling_but_not_far_answers():
    td = mk_test()
    r = {x.q: x for x in rc.grade(td, "reading", {4: "orangutang", 5: "ceiling"}, [4, 5])}
    assert r[4].near_miss and not r[4].correct
    assert not r[5].near_miss


def test_band_only_for_full_tests():
    assert rc.band_for("reading", 30, 40) == 7.0 and rc.band_for("listening", 30, 40) == 7.0
    assert rc.band_for("reading", 10, 13) is None


def test_record_attempt_errors_causes_and_error_log():
    conn = db.connect(":memory:")
    td = mk_test()
    res = rc.grade(td, "reading", {1: "FALSE", 2: "FALSE", 3: "", 4: "orangutang"}, [1, 2, 3, 4])
    aid = rc.record_attempt(conn, week=1, skill="reading", td=td, unit="p1", results=res, qtype="tfng")
    errs = rc.attempt_errors(conn, aid)
    assert [e["q"] for e in errs] == [1, 3, 4] and all(e["cause"] == "" for e in errs)   # reading: sin causa automática
    rc.save_cause(conn, "reading", errs[0]["id"], "Not Given vs False")
    assert conn.execute("SELECT module FROM error_log").fetchone()["module"] == "reading"
    a = conn.execute("SELECT * FROM receptive_attempt").fetchone()
    assert (a["raw"], a["total"], a["band"]) == (1, 4, None)
    assert conn.execute("SELECT COUNT(*) c FROM attempt WHERE skill='reading'").fetchone()["c"] == 1


def test_listening_near_miss_is_auto_spelling_and_creates_srs_card():
    conn = db.connect(":memory:")
    td = mk_test()
    td.key_listening = [KeyEntry(qnums=[1], answers=[["butterflies"]])]
    res = rc.grade(td, "listening", {1: "buterflies"}, [1])
    aid = rc.record_attempt(conn, week=1, skill="listening", td=td, unit="l1", results=res)
    assert rc.attempt_errors(conn, aid)[0]["cause"] == "Ortografía"
    assert conn.execute("SELECT category FROM error_log").fetchone()["category"] == "spelling"
    assert conn.execute("SELECT word FROM card").fetchone()["word"] == "butterflies"


def test_aggregate_attempt_has_band_and_no_errors():
    conn = db.connect(":memory:")
    td = mk_test()
    res = [rc.QResult(q, "x", q <= 30, "y") for q in range(1, 41)]
    aid = rc.record_attempt(conn, week=5, skill="reading", td=td, unit="all", results=res, aggregate=True)
    assert conn.execute("SELECT band FROM receptive_attempt WHERE id=?", (aid,)).fetchone()["band"] == 7.0
    assert rc.attempt_errors(conn, aid) == []
    assert conn.execute("SELECT COUNT(*) c FROM attempt").fetchone()["c"] == 0      # no mueve el nivel


def test_pick_unit_prefers_least_practised_and_filters_types():
    conn = db.connect(":memory:")
    t1, t2 = mk_test(), mk_test()
    t2.test = 2
    units = rc.all_units("reading", [t1, t2])
    first = rc.pick_unit(conn, "reading", units, types=["tfng"])
    assert first.td.test == 1
    rc.record_attempt(conn, week=1, skill="reading", td=t1, unit="p1", results=[rc.QResult(1, "a", True, "a")])
    assert rc.pick_unit(conn, "reading", units, types=["tfng"]).td.test == 2
    assert rc.pick_unit(conn, "reading", units, types=["matching_headings"]) is None


# ---------------------------------------------------------------- persistencia y revisión
def test_save_load_and_key_roundtrip(tmp_path):
    td = mk_test(verified=False)
    save_test(td, tmp_path)
    back = load_test("tb", 1, tmp_path)
    assert back.test_id == "tb/test1" and not back.verified
    rows = review.key_rows(back, "reading")
    assert rows[3] == {"q": 4, "answer": "(Sumatran) orangutan | orang-utan", "any_order": False}
    rows[0]["answer"] = "FALSE"
    new_key = review.rows_to_key(rows)
    assert [e.qnums for e in new_key] == [[1], [2], [3], [4], [5], [6, 7]]
    assert new_key[0].answers == [["FALSE"]] and new_key[5].any_order
    assert new_key[3].answers == [["(Sumatran) orangutan", "orang-utan"]]
    back.mark_verified()
    assert back.verified and back.verified_at


def test_check_flags_key_outside_options():
    td = mk_test()
    td.key_reading[0].answers = [["MAYBE"]]
    assert any("MAYBE" in n for n in review.check(td))


# ---------------------------------------------------------------- dictado
def test_dictation_locates_snippet_and_compares():
    book = ("peter: The island is a great place to explore. It is quite small, and it has a range of habitats.\n"
            "jan: OK. And is there anything we should bring, like a picnic, for instance?\n"
            "peter: Yes, do bring one, as it is a full-day walk.")
    asr = "and is there anything we should bring like a picnic for instance yes do bring one"
    ref = dictation.locate(asr, book)
    assert ref.startswith("And is there anything") and "peter" not in ref.lower() and ref.endswith("bring one")
    r = dictation.compare_dictation(ref, "is there anything we should bring picnic for instance yes do bring one")
    assert "and" in r["missing"] and "and" in r["weak_forms_missing"] and r["similarity"] < 1


# ---------------------------------------------------------------- integración con el libro real
@pytest.mark.skipif(not C17.exists(), reason="resources/ no disponible (se ignora en git)")
def test_c17_parses_completely(tmp_path):
    audio = cb.map_audio_c17(ROOT / "resources", "Cambriedge IELTS 17 (2022)")
    tests = cb.parse_book(C17, "c17", "Cambridge IELTS 17 Academic", audio, out_root=tmp_path, render_images=False)
    assert [t.test for t in tests] == [1, 2, 3, 4]
    for t in tests:
        assert set(t.key_map("listening")) == set(range(1, 41)), t.test_id
        assert set(t.key_map("reading")) == set(range(1, 41)), t.test_id
        assert [p.part for p in t.listening] == [1, 2, 3, 4]
        assert [p.n for p in t.reading] == [1, 2, 3]
        assert all(len(p.transcript) > 2000 for p in t.listening)
        assert all(len(p.text) > 3000 for p in t.reading)
        assert [w.task for w in t.writing] == [1, 2]
        for units in (t.listening, t.reading):
            assert {q for u in units for g in u.groups for q in g.qnums} == set(range(1, 41))
    assert tests[1].listening[3].audio is None                       # falta el audio de T2 parte 4
    assert all(p.audio for t in (tests[0], tests[2], tests[3]) for p in t.listening)
    assert any("Parte 4" in n for n in tests[1].notes)
    assert tests[0].key_map("listening")[10].answers == [["35", "thirty five"]]
    assert tests[0].key_map("reading")[7].answers == [["FALSE"]]
