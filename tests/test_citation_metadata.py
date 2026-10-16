"""Every Zenodo DOI the release names is one of the two the citation file names.

A version DOI is minted when its deposit is published, so it reaches the repository after
the archive it identifies, and it has to be written into the files by hand. That is how it
goes wrong: the version DOI was corrected in README.md and CITATION.cff for one release
while the About dialog of the GUI kept naming the release before it, in two languages, and
nothing noticed until the files were scanned for the old number.

So the scan is a test. CITATION.cff is the one place a DOI is written down - project_version
and project_archive_dois read it rather than repeat it - and a DOI anywhere else in the
release either agrees with it or is left over from an earlier version. The test also keeps
README.md and CITATION.cff together, because the two are updated in the same breath and
forgetting one of them is the easier mistake.
"""

from __future__ import annotations

import re
from pathlib import Path

from leximin.gui.data import project_archive_dois, project_version

ROOT = Path(__file__).resolve().parents[1]
DOI = re.compile(r"10\.5281/zenodo\.\d+")
READABLE = {".py", ".md", ".cff", ".txt", ".toml", ".json", ".yml", ".yaml", ".cfg"}
ROOT_FILES = ("README.md", "CITATION.cff", "LICENSE", "main.py", "pyproject.toml",
              "requirements.txt", "requirements-lock.txt")
FOLDERS = ("src", "tests", "DATA", "results")


def published_files() -> list[Path]:
    """The files of the release, found the way the allowlist finds them.

    scripts/ is the one directory that is published in part: .gitignore ignores it and
    re-includes the computation scripts one line at a time, so those lines are the list of
    what goes out. Everywhere else what is in the directory is what is published.
    """

    found = [ROOT / name for name in ROOT_FILES]
    for folder in FOLDERS:
        found += [path for path in (ROOT / folder).rglob("*")
                  if path.is_file() and path.suffix.lower() in READABLE]
    allowlist = (ROOT / ".gitignore").read_text(encoding="utf-8")
    found += [ROOT / "scripts" / name
              for name in re.findall(r"^!/scripts/([\w.\-]+\.py)$", allowlist, re.M)]
    return [path for path in sorted(set(found)) if path.is_file()]


def test_the_citation_file_names_two_distinct_archive_dois() -> None:
    concept, archived = project_archive_dois(ROOT)
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

    assert DOI.fullmatch(concept), f"the concept DOI reads {concept!r}"
    assert DOI.fullmatch(archived), f"the version DOI reads {archived!r}"
    assert concept != archived, "the concept DOI and the version DOI are the same number"
    assert f"doi: {concept}" in citation
    assert f"value: {archived}" in citation
    assert f"version: {project_version(ROOT)}" in citation


def test_the_readme_names_the_archive_the_citation_file_names() -> None:
    concept, archived = project_archive_dois(ROOT)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.count(concept) == 1, "README.md states the concept DOI once"
    assert readme.count(archived) == 1, (
        "README.md and CITATION.cff name different archives, or README.md was not "
        f"updated with {archived}")


def test_no_published_file_names_another_zenodo_record() -> None:
    allowed = set(project_archive_dois(ROOT))
    stale: dict[str, set[str]] = {}
    for path in published_files():
        for found in DOI.findall(path.read_text(encoding="utf-8", errors="ignore")):
            if found not in allowed:
                stale.setdefault(found, set()).add(str(path.relative_to(ROOT)))

    assert not stale, "a published file names a Zenodo DOI the citation file does not: " + \
        "; ".join(f"{doi} in {', '.join(sorted(where))}" for doi, where in sorted(stale.items()))
