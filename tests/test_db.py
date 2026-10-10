from ielts import db


def test_block_progress_and_levels():
    conn = db.connect(":memory:")
    assert db.get_level(conn, "writing") == db.DEFAULT_LEVEL
    db.set_level(conn, "writing", 12)
    assert db.get_level(conn, "writing") == 10

    assert not db.day_is_done(conn, 1, "monday", ["a", "b"])
    db.mark_block_done(conn, 1, "monday", "a", 60)
    assert not db.day_is_done(conn, 1, "monday", ["a", "b"])
    db.mark_block_done(conn, 1, "monday", "b", 30)
    assert db.day_is_done(conn, 1, "monday", ["a", "b"])
    assert not db.day_is_done(conn, 2, "monday", ["a", "b"])
    assert not db.day_is_done(conn, 1, "monday", [])
