"""Run browser scenarios with a fresh database for each script."""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = ("finance_workflow", "statement_wizard", "grocery_optimizer")
SCENARIOS = tuple(sorted(path.stem for path in HERE.glob("*.py")
                         if path.stem not in {"browser_harness", "run_suite"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Run every browser scenario.")
    parser.add_argument("scenarios", nargs="*", metavar="SCENARIO", help=", ".join(SCENARIOS))
    options = parser.parse_args()
    invalid = set(options.scenarios) - set(SCENARIOS)
    if invalid or (options.all and options.scenarios):
        parser.error("Use --all or list valid scenario names.")
    selected = SCENARIOS if options.all else options.scenarios or CORE
    failed = []
    for scenario in selected:
        print(f"Running {scenario}", flush=True)
        result = subprocess.run([sys.executable, str(HERE / f"{scenario}.py")], check=False)
        if result.returncode:
            failed.append(scenario)
    print(f"Browser workflows: {len(selected) - len(failed)} passed, {len(failed)} failed.")
    if failed:
        print("Failed: " + ", ".join(failed))
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
