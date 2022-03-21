# Copyright 2012-2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Representations specific to the Microchip XC16 C compiler family."""

import os
import typing as T

from ...mesonlib import EnvironmentException

if T.TYPE_CHECKING:
    from ...environment import Environment
    from ...compilers.compilers import Compiler
else:
    # This is a bit clever, for mypy we pretend that these mixins descend from
    # Compiler, so we get all of the methods and attributes defined for us, but
    # for runtime we make them descend from object (which all classes normally
    # do). This gives up DRYer type checking, with no runtime impact
    Compiler = object

xc16_buildtype_args = {
    'plain': [],
    'debug': [],
    'debugoptimized': [],
    'release': [],
    'minsize': [],
    'custom': [],
}  # type: T.Dict[str, T.List[str]]

xc16_optimization_args = {
    '0': ['-O0'],
    'g': ['-O0'],
    '1': ['-O1'],
    '2': ['-O2'],
    '3': ['-O3'],
    's': ['-Os']
}  # type: T.Dict[str, T.List[str]]

xc16_debug_args = {
    False: [],
    True: []
}  # type: T.Dict[bool, T.List[str]]


class Xc16Compiler(Compiler):

    id = 'xc16'

    def __init__(self)  :
        if not self.is_cross:
            raise EnvironmentException('xc16 supports only cross-compilation.')
        # Assembly
        self.can_compile_suffixes.add('s')
        default_warn_args = []  # type: T.List[str]
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + [],
                          '3': default_warn_args + []}  # type: T.Dict[str, T.List[str]]

    def get_always_args(self)  :
        return []

    def get_pic_args(self)  :
        # PIC support is not enabled by default for xc16,
        # if users want to use it, they need to add the required arguments explicitly
        return []

    def get_buildtype_args(self, buildtype )  :
        return xc16_buildtype_args[buildtype]

    def get_pch_suffix(self)  :
        return 'pch'

    def get_pch_use_args(self, pch_dir , header )  :
        return []

    def thread_flags(self, env )  :
        return []

    def get_coverage_args(self)  :
        return []

    def get_no_stdinc_args(self)  :
        return ['-nostdinc']

    def get_no_stdlib_link_args(self)  :
        return ['--nostdlib']

    def get_optimization_args(self, optimization_level )  :
        return xc16_optimization_args[optimization_level]

    def get_debug_args(self, is_debug )  :
        return xc16_debug_args[is_debug]

    @classmethod
    def unix_args_to_native(cls, args )  :
        result = []
        for i in args:
            if i.startswith('-D'):
                i = '-D' + i[2:]
            if i.startswith('-I'):
                i = '-I' + i[2:]
            if i.startswith('-Wl,-rpath='):
                continue
            elif i == '--print-search-dirs':
                continue
            elif i.startswith('-L'):
                continue
            result.append(i)
        return result

    def compute_parameters_with_absolute_paths(self, parameter_list , build_dir )  :
        for idx, i in enumerate(parameter_list):
            if i[:9] == '-I':
                parameter_list[idx] = i[:9] + os.path.normpath(os.path.join(build_dir, i[9:]))

        return parameter_list
