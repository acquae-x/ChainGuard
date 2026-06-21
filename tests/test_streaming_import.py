def test_stream_import_constant_batches(tmp_path):
    import sqlite3

    from src.streaming_import import stream_import_csv

    csv_p = tmp_path / "materials.csv"
    csv_p.write_text(
        "material_id,material_name\n"
        + "".join(f"M{i},n{i}\n" for i in range(2500)),
        encoding="utf-8",
    )
    db = tmp_path / "t.db"

    n = stream_import_csv(csv_p, "materials", db, batch_size=1000)

    assert n == 2500
    got = sqlite3.connect(db).execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    assert got == 2500


def test_reconcile_detects_match(tmp_path):
    from src.streaming_import import reconcile, stream_import_csv

    csv_p = tmp_path / "materials.csv"
    csv_p.write_text("material_id,name\n1,a\n2,b\n3,c\n", encoding="utf-8")
    db = tmp_path / "t.db"

    stream_import_csv(csv_p, "materials", db)
    ok, csv_rows, db_rows = reconcile(csv_p, "materials", db)

    assert ok is True and csv_rows == 3 and db_rows == 3


def test_create_indexes_for_known_table(tmp_path):
    import sqlite3

    from src.streaming_import import create_indexes, stream_import_csv

    csv_p = tmp_path / "inventory.csv"
    csv_p.write_text("material_id,on_hand_qty\n1,100\n", encoding="utf-8")
    db = tmp_path / "t.db"

    stream_import_csv(csv_p, "inventory", db)
    created = create_indexes(db, "inventory")

    assert created
    idx = sqlite3.connect(db).execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='inventory'"
    ).fetchall()
    assert idx


def test_stream_import_reports_batch_progress(tmp_path):
    from src.streaming_import import stream_import_csv

    csv_p = tmp_path / "inventory.csv"
    csv_p.write_text(
        "material_id,on_hand_qty\n" + "".join(f"M{i},{i}\n" for i in range(5)),
        encoding="utf-8",
    )
    db = tmp_path / "t.db"
    calls = []

    stream_import_csv(csv_p, "inventory", db, batch_size=2, progress=calls.append)

    assert calls == [2, 4, 5]
