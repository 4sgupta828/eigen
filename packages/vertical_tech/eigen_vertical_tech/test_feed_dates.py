"""One sortable date out of every shape a feed ships."""
from __future__ import annotations

from eigen_vertical_tech.feed_dates import iso_date


def test_every_real_feed_shape_parses():
    assert iso_date("Mon, 07 Sep 2026 07:19:44 +0000") == "2026-09-07"     # RSS, offset
    assert iso_date("Sat, 05 Sep 2026 07:07:00 -0000") == "2026-09-05"     # RSS, NO timezone stated
    assert iso_date("Fri, 04 Sep 2026 12:36:19 GMT") == "2026-09-04"       # RSS, named zone
    assert iso_date("2026-09-07T14:00:03+00:00") == "2026-09-07"           # Atom
    assert iso_date("2026-09-07") == "2026-09-07"


def test_a_date_we_cannot_trust_is_empty_rather_than_wrong():
    # A wrong date is worse than none: it would put an old piece at the top of "this week".
    assert iso_date("") == "" and iso_date("garbage") == "" and iso_date(None) == ""
    assert iso_date("Mon, 07 Sep 2099 07:19:44 +0000") == ""               # a feed bug, not news


def test_dates_sort_as_plain_text():
    days = ["2026-09-04", "2026-09-07", "2025-12-31"]
    assert sorted(days, reverse=True) == ["2026-09-07", "2026-09-04", "2025-12-31"]
