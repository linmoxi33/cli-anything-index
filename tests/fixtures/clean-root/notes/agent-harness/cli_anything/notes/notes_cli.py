import argparse

parser = argparse.ArgumentParser()
sub = parser.add_subparsers()
add = sub.add_parser("add")
add.add_argument("--json", action="store_true")
