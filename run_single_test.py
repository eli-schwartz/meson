#!/usr/bin/env python3
# SPDX-license-identifier: Apache-2.0
# Copyright © 2021 Intel Corporation

"""Script for running a single project test.

This script is meant for Meson developers who want to run a single project
test, with all of the rules from the test.json file loaded.
"""

import argparse
import pathlib
import typing as T

from mesonbuild import mlog
from run_project_tests import TestDef, load_test_json, run_tests, failing_logs
from run_project_tests import setup_commands, detect_system_compiler, print_tool_versions

if T.TYPE_CHECKING:
    from run_project_tests import CompilerArgumentType

    class ArgumentType(CompilerArgumentType):

        """Typing information for command line arguments."""

        case: pathlib.Path
        subtests: T.List[int]
        backend: str


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('case', type=pathlib.Path, help='The test case to run')
    parser.add_argument('--subtest', type=int, action='append', dest='subtests', help='which subtests to run')
    parser.add_argument('--backend', action='store', help="Which backend to use")
    parser.add_argument('--cross-file', action='store', help='File describing cross compilation environment.')
    parser.add_argument('--native-file', action='store', help='File describing native compilation environment.')
    parser.add_argument('--use-tmpdir', action='store_true', help='Use tmp directory for temporary files.')
    args = T.cast('ArgumentType', parser.parse_args())

    setup_commands(args.backend)
    detect_system_compiler(args)
    print_tool_versions()

    test = TestDef(args.case, args.case.stem, [])
    tests = load_test_json(test, False)
    if args.subtests:
        tests = [t for i, t in enumerate(tests) if i in args.subtests]

    results = run_tests([('single test', tests, False)], 'meson-single-test', False, [], args.use_tmpdir, 1)
    passing, failing, skipped = results
    if failing > 0:
        print('\nMesonlogs of failing tests\n')
        for l in failing_logs:
            try:
                print(l, '\n')
            except UnicodeError:
                print(l.encode('ascii', errors='replace').decode(), '\n')
    raise SystemExit(failing)

if __name__ == "__main__":
    main()
