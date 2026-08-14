from scripts.check_mypy_ceiling import parse_error_count


def test_parse_mypy_error_count() -> None:
    assert parse_error_count("Found 778 errors in 125 files (checked 236 source files)") == 778


def test_parse_clean_mypy_result() -> None:
    assert parse_error_count("Success: no issues found in 236 source files") == 0


def test_rejects_unrecognized_mypy_output() -> None:
    assert parse_error_count("mypy crashed before reporting") is None
