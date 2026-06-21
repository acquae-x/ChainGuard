def test_estimate_incoming_sums_sizes(tmp_path):
    from src.import_preflight import estimate_incoming

    a = tmp_path / "a.csv"
    a.write_text("id,name\n1,x\n2,y\n", encoding="utf-8")
    b = tmp_path / "b.csv"
    b.write_text("id,v\n1,9\n", encoding="utf-8")

    total, rows, largest = estimate_incoming([a, b])

    assert total == a.stat().st_size + b.stat().st_size
    assert largest == max(a.stat().st_size, b.stat().st_size)
    assert rows > 0


def test_insufficient_disk_blocks(tmp_path, monkeypatch):
    import src.import_preflight as pf

    f = tmp_path / "big.csv"
    f.write_text("c\n" + "row\n" * 1000, encoding="utf-8")
    monkeypatch.setattr(
        pf,
        "probe_resources",
        lambda _p: pf.ResourceProbe(
            free_disk_bytes=10,
            available_ram_bytes=None,
            ram_source="unavailable",
        ),
    )

    rep = pf.run_preflight([f], tmp_path / "t.db")

    assert rep.verdict == "INSUFFICIENT_DISK"
    assert rep.can_proceed is False
    assert rep.disk_shortfall_bytes > 0


def test_ok_when_disk_sufficient(tmp_path, monkeypatch):
    import src.import_preflight as pf

    f = tmp_path / "s.csv"
    f.write_text("c\n1\n", encoding="utf-8")
    monkeypatch.setattr(
        pf,
        "probe_resources",
        lambda _p: pf.ResourceProbe(
            free_disk_bytes=10**12,
            available_ram_bytes=10**9,
            ram_source="psutil",
        ),
    )

    rep = pf.run_preflight([f], tmp_path / "t.db")

    assert rep.verdict == "OK"
    assert rep.can_proceed is True


def test_recommend_postgres_above_soft_limit(tmp_path, monkeypatch):
    import src.import_preflight as pf

    f = tmp_path / "s.csv"
    f.write_text("c\n1\n", encoding="utf-8")
    monkeypatch.setattr(
        pf,
        "estimate_incoming",
        lambda _paths: (6 * 1024**3, 9_000_000, 6 * 1024**3),
    )
    monkeypatch.setattr(
        pf,
        "probe_resources",
        lambda _p: pf.ResourceProbe(
            free_disk_bytes=10**13,
            available_ram_bytes=None,
            ram_source="unavailable",
        ),
    )

    rep = pf.run_preflight([f], tmp_path / "t.db")

    assert rep.recommend_postgres is True
    assert rep.verdict == "REVIEW"
    assert rep.can_proceed is True


def test_probe_resources_degrades_without_psutil(tmp_path, monkeypatch):
    import builtins

    import src.import_preflight as pf

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    probe = pf.probe_resources(tmp_path)

    assert probe.available_ram_bytes is None
    assert probe.ram_source == "unavailable"
    assert probe.free_disk_bytes > 0


def test_existing_dir_climbs_to_existing_parent(tmp_path):
    import src.import_preflight as pf

    missing_db = tmp_path / "missing" / "nested" / "tenant.db"

    assert pf._existing_dir(missing_db) == tmp_path
