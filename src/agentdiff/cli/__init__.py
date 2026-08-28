import argparse

from agentdiff import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentdiff")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(f"agentdiff {__version__}")
        return 0
    parser.print_help()
    return 0
