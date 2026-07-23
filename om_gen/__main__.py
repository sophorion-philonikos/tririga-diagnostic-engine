"""CLI: python3 -m om_gen build|nl|minimal|types|nl-help"""

from __future__ import annotations

import argparse
import json
import sys

from om_gen.build import (
    build_from_nl,
    build_from_recipe_file,
    build_from_ir,
    minimal_start_end_ir,
)
from om_gen.dictionary import supported_type_codes, TASK_TYPES
from om_gen.intent import INTENT_NL_HELP
from om_gen import TYPE_NAMES


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='om_gen',
        description='Compile JSON recipe, constrained NL, or plain-English intent into a flat TRIRIGA OM zip.',
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_build = sub.add_parser('build', help='Build from JSON recipe file')
    p_build.add_argument('--recipe', required=True, help='Path to recipe JSON')
    p_build.add_argument('--out', required=True, help='Output zip path')

    p_nl = sub.add_parser('nl', help='Build from constrained NL or intent prompt')
    p_nl.add_argument('--prompt', required=True)
    p_nl.add_argument('--out', required=True)
    p_nl.add_argument('--name', default='')
    p_nl.add_argument('--module', default='')
    p_nl.add_argument('--bo', default='')
    p_nl.add_argument('--event', default='')

    p_min = sub.add_parser('minimal', help='Emit Start→End smoke zip')
    p_min.add_argument('--out', required=True)
    p_min.add_argument('--name', default='cst om_gen Minimal Start End')
    p_min.add_argument('--module', default='Location')
    p_min.add_argument('--bo', default='triBuilding')
    p_min.add_argument('--event', default='Pre-Create')

    sub.add_parser('types', help='List supported task types')
    sub.add_parser('nl-help', help='Show constrained NL + intent help')

    args = parser.parse_args(argv)

    if args.cmd == 'types':
        for code in supported_type_codes():
            info = TASK_TYPES[code]
            print(f"{code}\t{TYPE_NAMES.get(code, info['name'])}\tdefault_event={info['default_event_name']!r}")
        return 0

    if args.cmd == 'nl-help':
        print(INTENT_NL_HELP)
        return 0

    if args.cmd == 'minimal':
        ir = minimal_start_end_ir(
            name=args.name, module=args.module, bo=args.bo, event_name=args.event,
        )
        path = build_from_ir(ir, out_path=args.out)
        print(path)
        return 0

    if args.cmd == 'build':
        path = build_from_recipe_file(args.recipe, out_path=args.out)
        print(path)
        return 0

    if args.cmd == 'nl':
        path = build_from_nl(
            args.prompt, out_path=args.out,
            name=args.name, module=args.module, bo=args.bo, event_name=args.event,
        )
        print(path)
        return 0

    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
