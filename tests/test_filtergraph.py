"""Unit tests for compile/filtergraph.py."""
from __future__ import annotations

from compilation_maker.compile.filtergraph import (
    build_segment_filtergraph,
    escape_drawtext,
    escape_fontfile,
    layout_string,
)


def test_layout_3x3():
    s = layout_string(3, 640, 360)
    expected = "0_0|640_0|1280_0|0_360|640_360|1280_360|0_720|640_720|1280_720"
    assert s == expected


def test_layout_2x2():
    s = layout_string(2, 960, 540)
    assert s == "0_0|960_0|0_540|960_540"


def test_layout_4x4_cell_count():
    s = layout_string(4, 480, 270)
    cells = s.split("|")
    assert len(cells) == 16
    assert cells[0] == "0_0"
    assert cells[-1] == "1440_810"


def test_layout_arbitrary_n():
    for n in range(2, 11):
        s = layout_string(n, 100, 100)
        cells = s.split("|")
        assert len(cells) == n * n
        # Row-major ordering: first row's y is 0
        first_row = cells[:n]
        for cell in first_row:
            assert cell.endswith("_0")


def test_escape_drawtext_basic():
    assert escape_drawtext("hello") == "hello"


def test_escape_drawtext_strips_single_quote():
    assert "'" not in escape_drawtext("don't")


def test_escape_drawtext_colon():
    assert escape_drawtext("12:34") == r"12\:34"


def test_escape_drawtext_backslash():
    # backslash should be doubled BEFORE other escapes
    out = escape_drawtext("a\\b")
    assert out == "a\\\\b"


def test_escape_drawtext_brackets_commas():
    out = escape_drawtext("a,b[c]d")
    assert "\\," in out
    assert "\\[" in out
    assert "\\]" in out


def test_escape_fontfile_windows():
    out = escape_fontfile(r"C:\Windows\Fonts\arial.ttf")
    assert out == r"C\:/Windows/Fonts/arial.ttf"


def test_build_filtergraph_3x3_shape():
    picks = [{"name": f"f{i}", "year": 2020 + i} for i in range(9)]
    fg = build_segment_filtergraph(
        n=3, cell_w=640, cell_h=360, fps=30,
        border=False, show_name=False, show_year=False,
        picks=picks, font_file=None,
    )
    # 9 video chains, 9 audio chains, 1 xstack, 1 amix → 20 ;-separated parts
    parts = fg.split(";")
    assert len(parts) == 20
    assert "xstack=inputs=9" in fg
    assert "amix=inputs=9" in fg
    for i in range(9):
        assert f"[{i}:v]" in fg
        assert f"[{i}:a]" in fg
        assert f"[v{i}]" in fg
        assert f"[a{i}]" in fg
    assert "[v]" in fg
    assert "[a]" in fg


def test_build_filtergraph_with_overlays():
    picks = [{"name": "clip", "year": 2024}] * 9
    fg = build_segment_filtergraph(
        n=3, cell_w=640, cell_h=360, fps=30,
        border=True, show_name=True, show_year=True,
        picks=picks, font_file=r"C:\Windows\Fonts\arial.ttf",
    )
    assert "drawbox=" in fg
    assert "drawtext=" in fg
    assert "fontfile='C\\:/Windows/Fonts/arial.ttf'" in fg


def test_build_filtergraph_pick_count_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        build_segment_filtergraph(
            n=3, cell_w=640, cell_h=360, fps=30,
            border=False, show_name=False, show_year=False,
            picks=[{"name": "x", "year": 2024}] * 5,  # wrong count
            font_file=None,
        )


def test_build_filtergraph_skips_drawtext_without_font():
    picks = [{"name": "clip", "year": 2024}] * 9
    fg = build_segment_filtergraph(
        n=3, cell_w=640, cell_h=360, fps=30,
        border=False, show_name=True, show_year=True,
        picks=picks, font_file=None,
    )
    assert "drawtext=" not in fg
