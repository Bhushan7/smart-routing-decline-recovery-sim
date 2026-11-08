"""Eval entry point. Phase 1 stub: real evals arrive in Phases 2-5.

Usage: python evals/run_evals.py [--smoke]
"""
import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="small run with the stub LLM")
    args = parser.parse_args()
    mode = "smoke" if args.smoke else "full"
    print(f"[evals] mode={mode}: no evals implemented yet (Phase 1 placeholder).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
