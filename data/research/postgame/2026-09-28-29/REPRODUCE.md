# Reproduce this postgame audit
Unzip the evidence archive into an empty directory. With Python and NumPy installed:

    python postgame-20260928-29/analyze.py
    python postgame-20260928-29/build_report.py

The audit reads only retained forecasts and captured final sources. It asserts all 75 existing joint registry file hashes, paired event/score agreement, retained draw hashes, and winner-versus-home probability orientation. It does not refit or simulate any forecast. Outputs have a new actual execution timestamp; compare numerical fields rather than the entire analysis file hash across reruns. The source capture scripts are retained as provenance, but a reproduction should use the frozen raw sources. Future result revisions require a new audit version.

No canonical grading ledger is changed. The Monday research grade already existed and is referenced without appending it again. Montreal is excluded from the strict timing cohort. This archive includes future joint forecast bytes solely for registry integrity checks; only September 29 finals are scored.
