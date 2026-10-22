"""Run the same fail-closed security checks for selected group members."""
import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_checks():
    spec = importlib.util.spec_from_file_location(
        "group_security_checks", ROOT / "student-2" / "security_checks.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", nargs="+", choices=("student-2", "student-3", "student-4"),
                        default=["student-2", "student-3", "student-4"])
    parser.add_argument("--scan", choices=("ruff", "secrets", "dependencies", "all"), default="all")
    parser.add_argument("--include-shared", action="store_true",
                        help="Also scan ai-services source with Ruff and detect-secrets. AI requirements are always audited.")
    parser.add_argument("--report-root", type=Path,
                        help="Write each scope to ROOT/student-N/security/*.json (default: repository logs/).")
    args = parser.parse_args(argv)
    checks = load_checks()
    kinds = ("ruff", "secrets", "dependencies") if args.scan == "all" else (args.scan,)
    failures = 0
    for student in dict.fromkeys(args.students):
        report_dir = args.report_root / student / "security" if args.report_root else None
        for kind in kinds:
            try:
                checks.scan(kind, student, args.include_shared, report_dir)
            except (AssertionError, OSError, RuntimeError, ValueError):
                # Preserve the scanner's redacted JSON and continue to report other scopes.
                # No exception text, source lines, or detected secret values are printed.
                print(f"FAIL {student}: {kind}; inspect its redacted security report.")
                failures += 1
            else:
                print(f"PASS {student}: {kind}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
