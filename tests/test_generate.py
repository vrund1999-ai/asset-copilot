from datetime import date

from asset_copilot.synth.generate import month_start


def test_month_start_current_and_back():
    assert month_start(date(2026, 6, 30), 0) == date(2026, 6, 1)
    assert month_start(date(2026, 6, 30), 5) == date(2026, 1, 1)


def test_month_start_crosses_year_boundary():
    assert month_start(date(2026, 2, 15), 2) == date(2025, 12, 1)
    assert month_start(date(2026, 1, 1), 13) == date(2024, 12, 1)


def test_month_start_24_months_are_distinct_and_contiguous():
    months = [month_start(date(2026, 6, 30), m) for m in range(24)]
    assert len(set(months)) == 24
    assert months[0] == date(2026, 6, 1) and months[-1] == date(2024, 7, 1)
