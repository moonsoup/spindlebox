import pytest

from findexer.addresses import (
    assign_ordinals,
    make_address,
    parse_ranges,
    parse_selector,
)


def test_parse_ranges_single():
    assert parse_ranges("12") == [12]


def test_parse_ranges_span():
    assert parse_ranges("3-6") == [3, 4, 5, 6]


def test_parse_ranges_mixed():
    assert parse_ranges("12-14,55,2") == [12, 13, 14, 55, 2]


def test_parse_ranges_bad():
    with pytest.raises(ValueError):
        parse_ranges("9-3")


def test_parse_selector_ordinals_vs_address():
    assert parse_selector("12-14") == [12, 13, 14]
    assert parse_selector("src.utils.io") == "src.utils.io"
    assert parse_selector("7") == [7]


def test_make_address():
    assert make_address("src/utils/io.py", ["Reader"], "read_lines", 40) == (
        "src.utils.io.Reader.read_lines"
    )
    assert make_address("src/app.py", [], "<lambda>", 42) == "src.app#42"
    assert make_address("bin/tool.sh", [], "main", 3) == "bin.tool.main"


def test_assign_ordinals_fresh():
    items = [{"address": "b.f"}, {"address": "a.g"}]
    retired = assign_ordinals(items, {}, [])
    assert [i["ordinal"] for i in items] == [0, 1]
    assert retired == []


def test_assign_ordinals_sticky_and_retire():
    # previous build: a.g=0, b.f=1, c.h=2 ; retired: [5]
    old = {"a.g": 0, "b.f": 1, "c.h": 2}
    # new build: c.h gone, new d.k appears
    items = [{"address": "a.g"}, {"address": "b.f"}, {"address": "d.k"}]
    retired = assign_ordinals(items, old, [5])
    by_addr = {i["address"]: i["ordinal"] for i in items}
    assert by_addr["a.g"] == 0
    assert by_addr["b.f"] == 1
    assert by_addr["d.k"] == 6  # next free after max(existing + retired), never reuses 2 or 5
    assert sorted(retired) == [2, 5]
