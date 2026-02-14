from poster_engine import batch_adjust_content


def test_batch_adjust_range_only_once():
    content = "[Grade A]: 1500-1550 元/吨"
    out = batch_adjust_content(content, 10)
    assert "1510-1560" in out
    assert "1520-1570" not in out


def test_batch_adjust_range_with_tilde_separator():
    content = "[Grade A]: 1500~1550 元/吨"
    out = batch_adjust_content(content, -10)
    assert "1490-1540" in out
