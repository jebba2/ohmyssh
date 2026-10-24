"""Tests for the terminal emulation session and keyboard encoding."""

from pyommyssh.core.terminal import (
    CellPosition,
    Selection,
    TerminalSession,
    encodeKey,
    selectedText,
    wordSpanAt,
)


def test_feed_plain_text_appears_on_screen() -> None:
    session = TerminalSession(cols=20, rows=5)
    session.feed(b"hello")
    assert session.lines()[0].rstrip() == "hello"
    assert session.cursor() == (5, 0)


def test_feed_newline_moves_cursor() -> None:
    session = TerminalSession(cols=20, rows=5)
    session.feed(b"one\r\ntwo")
    lines = session.lines()
    assert lines[0].rstrip() == "one"
    assert lines[1].rstrip() == "two"
    assert session.cursor() == (3, 1)


def test_ansi_colors_are_tracked_per_cell() -> None:
    session = TerminalSession(cols=20, rows=5)
    session.feed(b"\x1b[31mR\x1b[0m\x1b[1mB")
    red = session.cellAt(0, 0)
    bold = session.cellAt(1, 0)
    assert red.data == "R"
    assert red.fg == "red"
    assert bold.data == "B"
    assert bold.bold is True
    assert bold.fg == "default"


def test_utf8_split_across_feeds() -> None:
    session = TerminalSession(cols=20, rows=5)
    encoded = "é".encode()
    session.feed(encoded[:1])
    session.feed(encoded[1:])
    assert session.lines()[0][0] == "é"


def test_resize_changes_dimensions_and_keeps_text() -> None:
    session = TerminalSession(cols=20, rows=5)
    session.feed(b"keep")
    session.resize(cols=40, rows=10)
    assert session.size() == (40, 10)
    assert len(session.lines()) == 10
    assert len(session.lines()[0]) == 40
    assert session.lines()[0].rstrip() == "keep"


def test_scrollback_keeps_lines_that_scroll_off() -> None:
    session = TerminalSession(cols=20, rows=3)
    session.feed(b"a\r\nb\r\nc\r\nd\r\ne")
    assert [line.rstrip() for line in session.lines()] == ["c", "d", "e"]
    assert [line.rstrip() for line in session.scrollbackLines()] == ["a", "b"]


def test_new_session_marks_every_row_dirty() -> None:
    session = TerminalSession(cols=20, rows=5)
    assert session.takeDirtyRows() == {0, 1, 2, 3, 4}


def test_dirty_rows_reported_then_cleared() -> None:
    session = TerminalSession(cols=20, rows=5)
    session.takeDirtyRows()
    session.feed(b"x\r\n\r\ny")
    assert session.takeDirtyRows() == {0, 2}
    assert session.takeDirtyRows() == set()


def test_encode_printable_text() -> None:
    assert encodeKey("a", text="a") == b"a"
    assert encodeKey("A", text="A", shift=True) == b"A"
    assert encodeKey("é", text="é") == "é".encode()


def test_encode_control_keys() -> None:
    assert encodeKey("Return") == b"\r"
    assert encodeKey("Enter") == b"\r"
    assert encodeKey("Backspace") == b"\x7f"
    assert encodeKey("Tab") == b"\t"
    assert encodeKey("Backtab", shift=True) == b"\x1b[Z"
    assert encodeKey("Escape") == b"\x1b"
    assert encodeKey("Delete") == b"\x1b[3~"
    assert encodeKey("Insert") == b"\x1b[2~"


def test_encode_cursor_and_navigation_keys() -> None:
    assert encodeKey("Up") == b"\x1b[A"
    assert encodeKey("Down") == b"\x1b[B"
    assert encodeKey("Right") == b"\x1b[C"
    assert encodeKey("Left") == b"\x1b[D"
    assert encodeKey("Home") == b"\x1b[H"
    assert encodeKey("End") == b"\x1b[F"
    assert encodeKey("PageUp") == b"\x1b[5~"
    assert encodeKey("PageDown") == b"\x1b[6~"


def test_encode_function_keys() -> None:
    assert encodeKey("F1") == b"\x1bOP"
    assert encodeKey("F4") == b"\x1bOS"
    assert encodeKey("F5") == b"\x1b[15~"
    assert encodeKey("F12") == b"\x1b[24~"


def test_encode_ctrl_combinations() -> None:
    assert encodeKey("c", text="c", ctrl=True) == b"\x03"
    assert encodeKey("C", text="C", ctrl=True, shift=True) == b"\x03"
    assert encodeKey("[", text="[", ctrl=True) == b"\x1b"
    assert encodeKey("Up", ctrl=True) == b"\x1b[1;5A"
    assert encodeKey("Left", ctrl=True) == b"\x1b[1;5D"


def test_encode_alt_prefixes_escape() -> None:
    assert encodeKey("x", text="x", alt=True) == b"\x1bx"
    assert encodeKey("Backspace", alt=True) == b"\x1b\x7f"


def test_encode_unknown_key_yields_nothing() -> None:
    assert encodeKey("Shift") == b""
    assert encodeKey("Control", ctrl=True) == b""
    assert encodeKey("CapsLock") == b""


def test_selection_orders_its_ends_and_spans_rows() -> None:
    forward = Selection(CellPosition(1, 2), CellPosition(3, 4))
    backward = Selection(CellPosition(3, 4), CellPosition(1, 2))
    for selection in (forward, backward):
        assert selection.start() == CellPosition(1, 2)
        assert selection.end() == CellPosition(3, 4)
        assert selection.columnSpan(0, 10) is None
        assert selection.columnSpan(1, 10) == (2, 10)
        assert selection.columnSpan(2, 10) == (0, 10)
        assert selection.columnSpan(3, 10) == (0, 5)
        assert selection.columnSpan(4, 10) is None
    single = Selection(CellPosition(2, 7), CellPosition(2, 3))
    assert single.columnSpan(2, 10) == (3, 8)


def test_selected_text_trims_padding_and_joins_rows() -> None:
    lines = ["first line   ", "   second", "third     ", "fourth"]
    assert selectedText(lines, Selection(CellPosition(0, 6), CellPosition(0, 9))) == "line"
    assert selectedText(lines, Selection(CellPosition(0, 6), CellPosition(2, 2))) == "line\n   second\nthi"
    assert selectedText(lines, Selection(CellPosition(1, 0), CellPosition(2, 20))) == "   second\nthird"
    assert selectedText(lines, Selection(CellPosition(9, 0), CellPosition(9, 3))) == ""


def test_word_span_at_covers_the_run_under_the_column() -> None:
    line = "ls -la /home/jeb  done"
    assert wordSpanAt(line, 0) == (0, 2)
    assert wordSpanAt(line, 4) == (3, 6)
    assert wordSpanAt(line, 9) == (7, 16)
    assert wordSpanAt(line, 17) == (16, 18)  # the gap between words
    assert wordSpanAt(line, 50) == (22, 22)
    assert wordSpanAt("", 0) == (0, 0)
