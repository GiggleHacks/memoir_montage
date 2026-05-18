from compilation_maker.analyzers.frames import pick_timestamps


def test_pick_timestamps_normal():
    ts = pick_timestamps(100.0, sample_count=8, trim_pct=0.05)
    assert len(ts) == 8
    assert ts[0] >= 5.0 - 1e-6
    assert ts[-1] <= 95.0 + 1e-6
    # monotonically increasing
    assert all(b > a for a, b in zip(ts[:-1], ts[1:]))


def test_pick_timestamps_short_video():
    ts = pick_timestamps(3.0, sample_count=8)
    assert 1 <= len(ts) <= 4
    assert ts[0] >= 0.0
    assert ts[-1] <= 3.0 + 1e-6


def test_pick_timestamps_near_zero():
    ts = pick_timestamps(0.0)
    assert ts == [0.0]


def test_pick_timestamps_single():
    ts = pick_timestamps(50.0, sample_count=1)
    assert len(ts) == 1
