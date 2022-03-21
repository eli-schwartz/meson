# Copyright 2019 The meson development team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Abstractions for the PGI family of compilers."""

import typing as T
import os
from pathlib import Path

from ..compilers import clike_debug_args, clike_optimization_args
from ...mesonlib import OptionKey

if T.TYPE_CHECKING:
    from ...environment import Environment
    from ...compilers.compilers import Compiler
else:
    # This is a bit clever, for mypy we pretend that these mixins descend from
    # Compiler, so we get all of the methods and attributes defined for us, but
    # for runtime we make them descend from object (which all classes normally
    # do). This gives up DRYer type checking, with no runtime impact
    Compiler = object

pgi_buildtype_args = {
    'plain': [],
    'debug': [],
    'debugoptimized': [],
    'release': [],
    'minsize': [],
    'custom': [],
}  # type: T.Dict[str, T.List[str]]


class PGICompiler(Compiler):

    id = 'pgi'

    def __init__(self)  :
        self.base_options = {OptionKey('b_pch')}

        default_warn_args = ['-Minform=inform']
        self.warn_args   = {
            '0': [],
            '1': default_warn_args,
            '2': default_warn_args,
            '3': default_warn_args
        }

    def get_module_incdir_args(self)  :
        return ('-module', )

    def get_no_warn_args(self)  :
        return ['-silent']

    def gen_import_library_args(self, implibname )  :
        return []

    def get_pic_args(self)  :
        # PGI -fPIC is Linux only.
        if self.info.is_linux():
            return ['-fPIC']
        return []

    def openmp_flags(self)  :
        return ['-mp']

    def get_buildtype_args(self, buildtype )  :
        return pgi_buildtype_args[buildtype]

    def get_optimization_args(self, optimization_level )  :
        return clike_optimization_args[optimization_level]

    def get_debug_args(self, is_debug )  :
        return clike_debug_args[is_debug]

    def compute_parameters_with_absolute_paths(self, parameter_list , build_dir )  :
        for idx, i in enumerate(parameter_list):
            if i[:2] == '-I' or i[:2] == '-L':
                parameter_list[idx] = i[:2] + os.path.normpath(os.path.join(build_dir, i[2:]))
        return parameter_list

    def get_always_args(self)  :
        return []

    def get_pch_suffix(self)  :
        # PGI defaults to .pch suffix for PCH on Linux and Windows with --pch option
        return 'pch'

    def get_pch_use_args(self, pch_dir , header )  :
        # PGI supports PCH for C++ only.
        hdr = Path(pch_dir).resolve().parent / header
        if self.language == 'cpp':
            return ['--pch',
                    '--pch_dir', str(hdr.parent),
                    '-I{}'.format((hdr.parent))]
        else:
            return []

    def thread_flags(self, env )  :
        # PGI cannot accept -pthread, it's already threaded
        return []
