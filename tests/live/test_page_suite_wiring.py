"""Every page test file must be run by `node --test tests/page/`.

The directory form runs tests/page/index.js only (see its header). On 2026-11-13 the new
labels.test.js was written but not required there, so its 5 tests never ran in the usual
command while two reports counted them. This test makes that silent gap impossible.
"""
import re
from pathlib import Path

PAGE_TESTS = Path(__file__).resolve().parents[1] / "page"


def test_every_page_test_file_is_required_by_index():
    index = (PAGE_TESTS / "index.js").read_text(encoding="utf-8")
    required = set(re.findall(r"require\('\./([\w.-]+\.test\.js)'\)", index))
    present = {p.name for p in PAGE_TESTS.glob("*.test.js")}
    assert present, "no page test file found"
    assert present == required, {"missing in index.js": sorted(present - required),
                                 "required but absent": sorted(required - present)}
