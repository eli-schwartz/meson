# Copyright 2013-2018 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for external dependencies.
# Custom logic for several other packages are in separate files.

from __future__ import annotations
import copy
import os
import collections
import itertools
import typing as T
from enum import Enum

from .. import mlog
from ..compilers import clib_langs
from ..mesonlib import LibType, MachineChoice, MesonException, HoldableObject
from ..mesonlib import version_compare_many
#from ..interpreterbase import FeatureDeprecated, FeatureNew

if T.TYPE_CHECKING:
    from .._typing import ImmutableListProtocol
    from ..build import StructuredSources
    from ..compilers.compilers import Compiler
    from ..environment import Environment
    from ..interpreterbase import FeatureCheckBase
    from ..build import BuildTarget, CustomTarget, IncludeDirs
    from ..mesonlib import FileOrString


class DependencyException(MesonException):
    '''Exceptions raised while trying to find dependencies'''


class DependencyMethods(Enum):
    # Auto means to use whatever dependency checking mechanisms in whatever order meson thinks is best.
    AUTO = 'auto'
    PKGCONFIG = 'pkg-config'
    CMAKE = 'cmake'
    # The dependency is provided by the standard library and does not need to be linked
    BUILTIN = 'builtin'
    # Just specify the standard link arguments, assuming the operating system provides the library.
    SYSTEM = 'system'
    # This is only supported on OSX - search the frameworks directory by name.
    EXTRAFRAMEWORK = 'extraframework'
    # Detect using the sysconfig module.
    SYSCONFIG = 'sysconfig'
    # Specify using a "program"-config style tool
    CONFIG_TOOL = 'config-tool'
    # For backwards compatibility
    SDLCONFIG = 'sdlconfig'
    CUPSCONFIG = 'cups-config'
    PCAPCONFIG = 'pcap-config'
    LIBWMFCONFIG = 'libwmf-config'
    QMAKE = 'qmake'
    # Misc
    DUB = 'dub'


DependencyTypeName = T.NewType('DependencyTypeName', str)


class Dependency(HoldableObject):

    @classmethod
    def _process_include_type_kw(cls, kwargs  )  :
        if 'include_type' not in kwargs:
            return 'preserve'
        if not isinstance(kwargs['include_type'], str):
            raise DependencyException('The include_type kwarg must be a string type')
        if kwargs['include_type'] not in ['preserve', 'system', 'non-system']:
            raise DependencyException("include_type may only be one of ['preserve', 'system', 'non-system']")
        return kwargs['include_type']

    def __init__(self, type_name , kwargs  )  :
        self.name = "null"
        self.version   = None
        self.language  = None # None means C-like
        self.is_found = False
        self.type_name = type_name
        self.compile_args  = []
        self.link_args     = []
        # Raw -L and -l arguments without manual library searching
        # If None, self.link_args will be used
        self.raw_link_args  = None
        self.sources    = []
        self.include_type = self._process_include_type_kw(kwargs)
        self.ext_deps  = []
        self.d_features   = collections.defaultdict(list)
        self.featurechecks  = []
        self.feature_since   = None

    def __repr__(self)  :
        return '<{} {}: {}>'.format((self.__class__.__name__), (self.name), (self.is_found))

    def is_built(self)  :
        return False

    def summary_value(self)    :
        if not self.found():
            return mlog.red('NO')
        if not self.version:
            return mlog.green('YES')
        return mlog.AnsiText(mlog.green('YES'), ' ', mlog.cyan(self.version))

    def get_compile_args(self)  :
        if self.include_type == 'system':
            converted = []
            for i in self.compile_args:
                if i.startswith('-I') or i.startswith('/I'):
                    converted += ['-isystem' + i[2:]]
                else:
                    converted += [i]
            return converted
        if self.include_type == 'non-system':
            converted = []
            for i in self.compile_args:
                if i.startswith('-isystem'):
                    converted += ['-I' + i[8:]]
                else:
                    converted += [i]
            return converted
        return self.compile_args

    def get_all_compile_args(self)  :
        """Get the compile arguments from this dependency and it's sub dependencies."""
        return list(itertools.chain(self.get_compile_args(),
                                    *(d.get_all_compile_args() for d in self.ext_deps)))

    def get_link_args(self, language  = None, raw  = False)  :
        if raw and self.raw_link_args is not None:
            return self.raw_link_args
        return self.link_args

    def get_all_link_args(self)  :
        """Get the link arguments from this dependency and it's sub dependencies."""
        return list(itertools.chain(self.get_link_args(),
                                    *(d.get_all_link_args() for d in self.ext_deps)))

    def found(self)  :
        return self.is_found

    def get_sources(self)    :
        """Source files that need to be added to the target.
        As an example, gtest-all.cc when using GTest."""
        return self.sources

    def get_name(self)  :
        return self.name

    def get_version(self)  :
        if self.version:
            return self.version
        else:
            return 'unknown'

    def get_include_type(self)  :
        return self.include_type

    def get_exe_args(self, compiler )  :
        return []

    def get_pkgconfig_variable(self, variable_name ,
                               define_variable ,
                               default )  :
        raise DependencyException('{!r} is not a pkgconfig dependency'.format((self.name)))

    def get_configtool_variable(self, variable_name )  :
        raise DependencyException('{!r} is not a config-tool dependency'.format((self.name)))

    def get_partial_dependency(self, *, compile_args  = False,
                               link_args  = False, links  = False,
                               includes  = False, sources  = False)  :
        """Create a new dependency that contains part of the parent dependency.

        The following options can be inherited:
            links -- all link_with arguments
            includes -- all include_directory and -I/-isystem calls
            sources -- any source, header, or generated sources
            compile_args -- any compile args
            link_args -- any link args

        Additionally the new dependency will have the version parameter of it's
        parent (if any) and the requested values of any dependencies will be
        added as well.
        """
        raise RuntimeError('Unreachable code in partial_dependency called')

    def _add_sub_dependency(self, deplist  )  :
        """Add an internal dependency from a list of possible dependencies.

        This method is intended to make it easier to add additional
        dependencies to another dependency internally.

        Returns true if the dependency was successfully added, false
        otherwise.
        """
        for d in deplist:
            dep = d()
            if dep.is_found:
                self.ext_deps.append(dep)
                return True
        return False

    def get_variable(self, *, cmake  = None, pkgconfig  = None,
                     configtool  = None, internal  = None,
                     default_value  = None,
                     pkgconfig_define  = None)   :
        if default_value is not None:
            return default_value
        raise DependencyException('No default provided for dependency {!r}, which is not pkg-config, cmake, or config-tool based.'.format((self)))

    def generate_system_dependency(self, include_type )  :
        new_dep = copy.deepcopy(self)
        new_dep.include_type = self._process_include_type_kw({'include_type': include_type})
        return new_dep

class InternalDependency(Dependency):
    def __init__(self, version , incdirs , compile_args ,
                 link_args ,
                 libraries  ,
                 whole_libraries  ,
                 sources   ,
                 ext_deps , variables  ,
                 d_module_versions , d_import_dirs ):
        super().__init__(DependencyTypeName('internal'), {})
        self.version = version
        self.is_found = True
        self.include_directories = incdirs
        self.compile_args = compile_args
        self.link_args = link_args
        self.libraries = libraries
        self.whole_libraries = whole_libraries
        self.sources = list(sources)
        self.ext_deps = ext_deps
        self.variables = variables
        if d_module_versions:
            self.d_features['versions'] = d_module_versions
        if d_import_dirs:
            self.d_features['import_dirs'] = d_import_dirs

    def __deepcopy__(self, memo  )  :
        result = self.__class__.__new__(self.__class__)
        assert isinstance(result, InternalDependency)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if k in ['libraries', 'whole_libraries']:
                setattr(result, k, copy.copy(v))
            else:
                setattr(result, k, copy.deepcopy(v, memo))
        return result

    def summary_value(self)  :
        # Omit the version.  Most of the time it will be just the project
        # version, which is uninteresting in the summary.
        return mlog.green('YES')

    def is_built(self)  :
        if self.sources or self.libraries or self.whole_libraries:
            return True
        return any(d.is_built() for d in self.ext_deps)

    def get_pkgconfig_variable(self, variable_name ,
                               define_variable ,
                               default )  :
        raise DependencyException('Method "get_pkgconfig_variable()" is '
                                  'invalid for an internal dependency')

    def get_configtool_variable(self, variable_name )  :
        raise DependencyException('Method "get_configtool_variable()" is '
                                  'invalid for an internal dependency')

    def get_partial_dependency(self, *, compile_args  = False,
                               link_args  = False, links  = False,
                               includes  = False, sources  = False)  :
        final_compile_args = self.compile_args.copy() if compile_args else []
        final_link_args = self.link_args.copy() if link_args else []
        final_libraries = self.libraries.copy() if links else []
        final_whole_libraries = self.whole_libraries.copy() if links else []
        final_sources = self.sources.copy() if sources else []
        final_includes = self.include_directories.copy() if includes else []
        final_deps = [d.get_partial_dependency(
            compile_args=compile_args, link_args=link_args, links=links,
            includes=includes, sources=sources) for d in self.ext_deps]
        return InternalDependency(
            self.version, final_includes, final_compile_args,
            final_link_args, final_libraries, final_whole_libraries,
            final_sources, final_deps, self.variables, [], [])

    def get_variable(self, *, cmake  = None, pkgconfig  = None,
                     configtool  = None, internal  = None,
                     default_value  = None,
                     pkgconfig_define  = None)   :
        val = self.variables.get(internal, default_value)
        if val is not None:
            # TODO: Try removing this assert by better typing self.variables
            if isinstance(val, str):
                return val
            if isinstance(val, list):
                for i in val:
                    assert isinstance(i, str)
                return val
        raise DependencyException('Could not get an internal variable and no default provided for {!r}'.format((self)))

    def generate_link_whole_dependency(self)  :
        new_dep = copy.deepcopy(self)
        new_dep.whole_libraries += new_dep.libraries
        new_dep.libraries = []
        return new_dep

class HasNativeKwarg:
    def __init__(self, kwargs  ):
        self.for_machine = self.get_for_machine_from_kwargs(kwargs)

    def get_for_machine_from_kwargs(self, kwargs  )  :
        return MachineChoice.BUILD if kwargs.get('native', False) else MachineChoice.HOST

class ExternalDependency(Dependency, HasNativeKwarg):
    def __init__(self, type_name , environment , kwargs  , language  = None):
        Dependency.__init__(self, type_name, kwargs)
        self.env = environment
        self.name = type_name # default
        self.is_found = False
        self.language = language
        self.version_reqs = kwargs.get('version', None)
        if isinstance(self.version_reqs, str):
            self.version_reqs = [self.version_reqs]
        self.required = kwargs.get('required', True)
        self.silent = kwargs.get('silent', False)
        self.static = kwargs.get('static', False)
        self.libtype = LibType.STATIC if self.static else LibType.PREFER_SHARED
        if not isinstance(self.static, bool):
            raise DependencyException('Static keyword must be boolean')
        # Is this dependency to be run on the build platform?
        HasNativeKwarg.__init__(self, kwargs)
        self.clib_compiler = detect_compiler(self.name, environment, self.for_machine, self.language)

    def get_compiler(self)  :
        return self.clib_compiler

    def get_partial_dependency(self, *, compile_args  = False,
                               link_args  = False, links  = False,
                               includes  = False, sources  = False)  :
        new = copy.copy(self)
        if not compile_args:
            new.compile_args = []
        if not link_args:
            new.link_args = []
        if not sources:
            new.sources = []
        if not includes:
            pass # TODO maybe filter compile_args?
        if not sources:
            new.sources = []

        return new

    def log_details(self)  :
        return ''

    def log_info(self)  :
        return ''

    def log_tried(self)  :
        return ''

    # Check if dependency version meets the requirements
    def _check_version(self)  :
        if not self.is_found:
            return

        if self.version_reqs:
            # an unknown version can never satisfy any requirement
            if not self.version:
                self.is_found = False
                found_msg  = []
                found_msg += ['Dependency', mlog.bold(self.name), 'found:']
                found_msg += [mlog.red('NO'), 'unknown version, but need:', self.version_reqs]
                mlog.log(*found_msg)

                if self.required:
                    m = 'Unknown version of dependency {!r}, but need {!r}.'.format((self.name), (self.version_reqs))
                    raise DependencyException(m)

            else:
                (self.is_found, not_found, found) =\
                    version_compare_many(self.version, self.version_reqs)
                if not self.is_found:
                    found_msg = ['Dependency', mlog.bold(self.name), 'found:']
                    found_msg += [mlog.red('NO'),
                                  'found', mlog.normal_cyan(self.version), 'but need:',
                                  mlog.bold(', '.join(["'{}'".format((e)) for e in not_found]))]
                    if found:
                        found_msg += ['; matched:',
                                      ', '.join(["'{}'".format((e)) for e in found])]
                    mlog.log(*found_msg)

                    if self.required:
                        m = 'Invalid version of dependency, need {!r} {!r} found {!r}.'
                        raise DependencyException(m.format(self.name, not_found, self.version))
                    return


class NotFoundDependency(Dependency):
    def __init__(self, name , environment )  :
        super().__init__(DependencyTypeName('not-found'), {})
        self.env = environment
        self.name = name
        self.is_found = False

    def get_partial_dependency(self, *, compile_args  = False,
                               link_args  = False, links  = False,
                               includes  = False, sources  = False)  :
        return copy.copy(self)


class ExternalLibrary(ExternalDependency):
    def __init__(self, name , link_args , environment ,
                 language , silent  = False)  :
        super().__init__(DependencyTypeName('library'), environment, {}, language=language)
        self.name = name
        self.language = language
        self.is_found = False
        if link_args:
            self.is_found = True
            self.link_args = link_args
        if not silent:
            if self.is_found:
                mlog.log('Library', mlog.bold(name), 'found:', mlog.green('YES'))
            else:
                mlog.log('Library', mlog.bold(name), 'found:', mlog.red('NO'))

    def get_link_args(self, language  = None, raw  = False)  :
        '''
        External libraries detected using a compiler must only be used with
        compatible code. For instance, Vala libraries (.vapi files) cannot be
        used with C code, and not all Rust library types can be linked with
        C-like code. Note that C++ libraries *can* be linked with C code with
        a C++ linker (and vice-versa).
        '''
        # Using a vala library in a non-vala target, or a non-vala library in a vala target
        # XXX: This should be extended to other non-C linkers such as Rust
        if (self.language == 'vala' and language != 'vala') or\
           (language == 'vala' and self.language != 'vala'):
            return []
        return super().get_link_args(language=language, raw=raw)

    def get_partial_dependency(self, *, compile_args  = False,
                               link_args  = False, links  = False,
                               includes  = False, sources  = False)  :
        # External library only has link_args, so ignore the rest of the
        # interface.
        new = copy.copy(self)
        if not link_args:
            new.link_args = []
        return new


def sort_libpaths(libpaths , refpaths )  :
    """Sort <libpaths> according to <refpaths>

    It is intended to be used to sort -L flags returned by pkg-config.
    Pkg-config returns flags in random order which cannot be relied on.
    """
    if len(refpaths) == 0:
        return list(libpaths)

    def key_func(libpath )   :
        common_lengths  = []
        for refpath in refpaths:
            try:
                common_path  = os.path.commonpath([libpath, refpath])
            except ValueError:
                common_path = ''
            common_lengths.append(len(common_path))
        max_length = max(common_lengths)
        max_index = common_lengths.index(max_length)
        reversed_max_length = len(refpaths[max_index]) - max_length
        return (max_index, reversed_max_length)
    return sorted(libpaths, key=key_func)

def strip_system_libdirs(environment , for_machine , link_args )  :
    """Remove -L<system path> arguments.

    leaving these in will break builds where a user has a version of a library
    in the system path, and a different version not in the system path if they
    want to link against the non-system path version.
    """
    exclude = {'-L{}'.format((p)) for p in environment.get_compiler_system_dirs(for_machine)}
    return [l for l in link_args if l not in exclude]

def process_method_kw(possible , kwargs  )  :
    method = kwargs.get('method', 'auto')  # type: T.Union[DependencyMethods, str]
    if isinstance(method, DependencyMethods):
        return [method]
    # TODO: try/except?
    if method not in [e.value for e in DependencyMethods]:
        raise DependencyException('method {!r} is invalid'.format((method)))
    method = DependencyMethods(method)

    # Raise FeatureNew where appropriate
    if method is DependencyMethods.CONFIG_TOOL:
        # FIXME: needs to get a handle on the subproject
        # FeatureNew.single_use('Configuration method "config-tool"', '0.44.0')
        pass
    # This sets per-tool config methods which are deprecated to to the new
    # generic CONFIG_TOOL value.
    if method in [DependencyMethods.SDLCONFIG, DependencyMethods.CUPSCONFIG,
                  DependencyMethods.PCAPCONFIG, DependencyMethods.LIBWMFCONFIG]:
        # FIXME: needs to get a handle on the subproject
        #FeatureDeprecated.single_use(f'Configuration method {method.value}', '0.44', 'Use "config-tool" instead.')
        method = DependencyMethods.CONFIG_TOOL
    if method is DependencyMethods.QMAKE:
        # FIXME: needs to get a handle on the subproject
        # FeatureDeprecated.single_use('Configuration method "qmake"', '0.58', 'Use "config-tool" instead.')
        method = DependencyMethods.CONFIG_TOOL

    # Set the detection method. If the method is set to auto, use any available method.
    # If method is set to a specific string, allow only that detection method.
    if method == DependencyMethods.AUTO:
        methods = list(possible)
    elif method in possible:
        methods = [method]
    else:
        raise DependencyException(
            'Unsupported detection method: {}, allowed methods are {}'.format(
                method.value,
                mlog.format_list([x.value for x in [DependencyMethods.AUTO] + list(possible)])))

    return methods

def detect_compiler(name , env , for_machine ,
                    language )  :
    """Given a language and environment find the compiler used."""
    compilers = env.coredata.compilers[for_machine]

    # Set the compiler for this dependency if a language is specified,
    # else try to pick something that looks usable.
    if language:
        if language not in compilers:
            m = name.capitalize() + ' requires a {0} compiler, but '\
                '{0} is not in the list of project languages'
            raise DependencyException(m.format(language.capitalize()))
        return compilers[language]
    else:
        for lang in clib_langs:
            try:
                return compilers[lang]
            except KeyError:
                continue
    return None


class SystemDependency(ExternalDependency):

    """Dependency base for System type dependencies."""

    def __init__(self, name , env , kwargs  ,
                 language  = None)  :
        super().__init__(DependencyTypeName('system'), env, kwargs, language=language)
        self.name = name

    def log_tried(self)  :
        return 'system'


class BuiltinDependency(ExternalDependency):

    """Dependency base for Builtin type dependencies."""

    def __init__(self, name , env , kwargs  ,
                 language  = None)  :
        super().__init__(DependencyTypeName('builtin'), env, kwargs, language=language)
        self.name = name

    def log_tried(self)  :
        return 'builtin'
