# SPDX-License-Identifier: Apache-2.0
# Copyright © 2021 Intel Corporation

"""Abstraction for Cython language compilers."""

import typing as T

from .. import coredata
from ..mesonlib import EnvironmentException, OptionKey
from .compilers import Compiler

if T.TYPE_CHECKING:
    from ..coredata import KeyedOptionDictType
    from ..environment import Environment


class CythonCompiler(Compiler):

    """Cython Compiler."""

    language = 'cython'
    id = 'cython'

    def needs_static_linker(self)  :
        # We transpile into C, so we don't need any linker
        return False

    def get_always_args(self)  :
        return ['--fast-fail']

    def get_werror_args(self)  :
        return ['-Werror']

    def get_output_args(self, outputname )  :
        return ['-o', outputname]

    def get_optimization_args(self, optimization_level )  :
        # Cython doesn't have optimization levels itself, the underlying
        # compiler might though
        return []

    def sanity_check(self, work_dir , environment )  :
        code = 'print("hello world")'
        with self.cached_compile(code, environment.coredata) as p:
            if p.returncode != 0:
                raise EnvironmentException('Cython compiler {!r} cannot compile programs'.format((self.id)))

    def get_buildtype_args(self, buildtype )  :
        # Cython doesn't implement this, but Meson requires an implementation
        return []

    def get_pic_args(self)  :
        # We can lie here, it's fine
        return []

    def compute_parameters_with_absolute_paths(self, parameter_list ,
                                               build_dir )  :
        new  = []
        for i in parameter_list:
            new.append(i)

        return new

    def get_options(self)  :
        opts = super().get_options()
        opts.update({
            OptionKey('version', machine=self.for_machine, lang=self.language): coredata.UserComboOption(
                'Python version to target',
                ['2', '3'],
                '3',
            ),
            OptionKey('language', machine=self.for_machine, lang=self.language): coredata.UserComboOption(
                'Output C or C++ files',
                ['c', 'cpp'],
                'c',
            )
        })
        return opts

    def get_option_compile_args(self, options )  :
        args  = []
        key = options[OptionKey('version', machine=self.for_machine, lang=self.language)]
        args.append('-{}'.format((key.value)))
        lang = options[OptionKey('language', machine=self.for_machine, lang=self.language)]
        if lang.value == 'cpp':
            args.append('--cplus')
        return args
