import argparse

parser = argparse.ArgumentParser()
sub = parser.add_subparsers()
inspect = sub.add_parser("inspect")
inspect.add_argument("--json", action="store_true")
repair = sub.add_parser("repair")
