# Copyright 2019 The Meson development team
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

"""Mixins for compilers that *are* linkers.

While many compilers (such as gcc and clang) are used by meson to dispatch
linker commands and other (like MSVC) are not, a few (such as DMD) actually
are both the linker and compiler in one binary. This module provides mixin
classes for those cases.
"""

import typing as T

from ...mesonlib import EnvironmentException, MesonException, is_windows

if T.TYPE_CHECKING:
    from ...coredata import KeyedOptionDictType
    from ...environment import Environment
    from ...compilers.compilers import Compiler
else:
    # This is a bit clever, for mypy we pretend that these mixins descend from
    # Compiler, so we get all of the methods and attributes defined for us, but
    # for runtime we make them descend from object (which all classes normally
    # do). This gives up DRYer type checking, with no runtime impact
    Compiler = object


class BasicLinkerIsCompilerMixin(Compiler):

    """Provides a baseline of methods that a linker would implement.

    In every case this provides a "no" or "empty" answer. If a compiler
    implements any of these it needs a different mixin or to override that
    functionality itself.
    """

    def sanitizer_link_args(self, value )  :
        return []

    def get_lto_link_args(self, *, threads  = 0, mode  = 'default')  :
        return []

    def can_linker_accept_rsp(self)  :
        return is_windows()

    def get_linker_exelist(self)  :
        return self.exelist.copy()

    def get_linker_output_args(self, output )  :
        return []

    def get_linker_always_args(self)  :
        return []

    def get_linker_lib_prefix(self)  :
        return ''

    def get_option_link_args(self, options )  :
        return []

    def has_multi_link_args(self, args , env )   :
        return False, False

    def get_link_debugfile_args(self, targetfile )  :
        return []

    def get_std_shared_lib_link_args(self)  :
        return []

    def get_std_shared_module_args(self, options )  :
        return self.get_std_shared_lib_link_args()

    def get_link_whole_for(self, args )  :
        raise EnvironmentException('Linker {} does not support link_whole'.format((self.id)))

    def get_allow_undefined_link_args(self)  :
        raise EnvironmentException('Linker {} does not support allow undefined'.format((self.id)))

    def get_pie_link_args(self)  :
        raise EnvironmentException('Linker {} does not support position-independent executable'.format((self.id)))

    def get_undefined_link_args(self)  :
        return []

    def get_coverage_link_args(self)  :
        return []

    def no_undefined_link_args(self)  :
        return []

    def bitcode_args(self)  :
        raise MesonException("This linker doesn't support bitcode bundles")

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion ,
                        darwin_versions  )  :
        raise MesonException("This linker doesn't support soname args")

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return ([], set())

    def get_asneeded_args(self)  :
        return []

    def get_buildtype_linker_args(self, buildtype )  :
        return []

    def get_link_debugfile_name(self, target )  :
        return ''

    def thread_flags(self, env )  :
        return []

    def thread_link_flags(self, env )  :
        return []
