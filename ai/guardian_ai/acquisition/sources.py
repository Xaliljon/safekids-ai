"""Where each open dataset actually lives.

Every URL here was probed before being written down. A source spec that
404s is worse than no spec: it turns an unavailable dataset into what looks
like a broken tool, and the next person debugs the fetcher instead of
emailing the maintainer.

None of these contain minors, which is why they need nothing from ADR-0005's
collection governance — but their licences are research terms, so the
datasets they produce publish as ``evaluation-only`` and cannot train a
model that reaches the zoo (ADR-0005 §5). They exist to answer one
question the current corpus cannot: does the detector work anywhere it was
not trained?
"""

from __future__ import annotations

from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.fetch import RemoteFile, SourceSpec

_URFALL_BASE = "http://fenix.ur.edu.pl/~mkepski/ds/data"
_URFALL_FALLS = 30
_URFALL_ADLS = 40


def _urfall_files() -> tuple[RemoteFile, ...]:
    """Two label CSVs and one RGB archive per sequence, camera 0.

    Camera 1 exists for the fall sequences only and is omitted: a second
    view of the same fall in the same room adds no domain, and UR Fall's
    value here is being a domain Guardian has never seen.
    """
    files = [
        RemoteFile(f"{_URFALL_BASE}/urfall-cam0-falls.csv", "urfall-cam0-falls.csv"),
        RemoteFile(f"{_URFALL_BASE}/urfall-cam0-adls.csv", "urfall-cam0-adls.csv"),
    ]
    for index in range(1, _URFALL_FALLS + 1):
        name = f"fall-{index:02d}-cam0-rgb"
        files.append(RemoteFile(f"{_URFALL_BASE}/{name}.zip", f"videos/{name}.zip", extract=True))
    for index in range(1, _URFALL_ADLS + 1):
        name = f"adl-{index:02d}-cam0-rgb"
        files.append(RemoteFile(f"{_URFALL_BASE}/{name}.zip", f"videos/{name}.zip", extract=True))
    return tuple(files)


URFALL = SourceSpec(
    name="urfall",
    homepage="http://fenix.ur.edu.pl/~mkepski/ds/uf.html",
    license_note="UR Fall Detection Dataset — free for research use; cite Kwolek & Kepski 2014.",
    files=_urfall_files(),
)

GMDCSA24 = SourceSpec(
    name="gmdcsa24",
    homepage="https://github.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos",
    license_note="GMDCSA24 — CC-BY 4.0; cite Alanazi et al. 2024.",
    files=(
        RemoteFile(
            url=(
                "https://github.com/ekramalam/"
                "GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos/"
                "archive/refs/heads/master.tar.gz"
            ),
            target="gmdcsa24.tar.gz",
            extract=True,
            # The tarball wraps everything in `<repo>-master/`; the importer
            # expects `Subject 1/…` at the top.
            strip_root=True,
        ),
    ),
)

# Le2i has no stable public download — the Dijon page has moved more than
# once and mirrors disagree on contents. It is fetched by hand and its
# provenance recorded at import, which is exactly the situation the lockfile
# exists to avoid; listing a dead URL here would hide that rather than fix it.
_SOURCES = {spec.name: spec for spec in (URFALL, GMDCSA24)}


def available_sources() -> list[str]:
    return sorted(_SOURCES)


def get_source(name: str) -> SourceSpec:
    spec = _SOURCES.get(name)
    if spec is None:
        raise AcquisitionError(
            f"no fetch spec for '{name}' (available: {available_sources()}). "
            f"Sources without one are downloaded by hand and passed with --raw."
        )
    return spec
