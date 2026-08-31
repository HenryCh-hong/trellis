

def test_structured_dates_arrive_as_strings_and_must_be_coerced():
    """Structured payloads travel as JSON, so a date is a string. Passing it
    through raw reached the scorer and raised there — a long way from the
    mistake. Coercion belongs at the boundary."""
    from datetime import date

    from app.agents.extraction_agent import _as_date, _as_int

    assert _as_date("2026-09-30") == date(2026, 9, 30)
    assert _as_date("2026-09-30T12:00:00Z") == date(2026, 9, 30)
    assert _as_date(date(2026, 9, 30)) == date(2026, 9, 30)
    assert _as_date("not a date") is None
    assert _as_date(None) is None
    assert _as_date("") is None

    assert _as_int("8 hours") == 8
    assert _as_int(8) == 8
    assert _as_int(True) is None
    assert _as_int("none") is None
