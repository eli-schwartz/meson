# Copyright 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This class contains the basic functionality needed to run any interpreter
# or an interpreter-based tool.

from ..mesonlib import MesonException, OptionKey
from .. import mlog
from pathlib import Path
import typing as T

if T.TYPE_CHECKING:
    from ..environment import Environment

language_map = {
    'c': 'C',
    'cpp': 'CXX',
    'cuda': 'CUDA',
    'objc': 'OBJC',
    'objcpp': 'OBJCXX',
    'cs': 'CSharp',
    'java': 'Java',
    'fortran': 'Fortran',
    'swift': 'Swift',
}

backend_generator_map = {
    'ninja': 'Ninja',
    'xcode': 'Xcode',
    'vs2010': 'Visual Studio 10 2010',
    'vs2012': 'Visual Studio 11 2012',
    'vs2013': 'Visual Studio 12 2013',
    'vs2015': 'Visual Studio 14 2015',
    'vs2017': 'Visual Studio 15 2017',
    'vs2019': 'Visual Studio 16 2019',
    'vs2022': 'Visual Studio 17 2022',
}

blacklist_cmake_defs = [
    'CMAKE_TOOLCHAIN_FILE',
    'CMAKE_PROJECT_INCLUDE',
    'MESON_PRELOAD_FILE',
    'MESON_PS_CMAKE_CURRENT_BINARY_DIR',
    'MESON_PS_CMAKE_CURRENT_SOURCE_DIR',
    'MESON_PS_DELAYED_CALLS',
    'MESON_PS_LOADED',
    'MESON_FIND_ROOT_PATH',
    'MESON_CMAKE_SYSROOT',
    'MESON_PATHS_LIST',
    'MESON_CMAKE_ROOT',
]

def cmake_is_debug(env )  :
    if OptionKey('b_vscrt') in env.coredata.options:
        is_debug = env.coredata.get_option(OptionKey('buildtype')) == 'debug'
        if env.coredata.options[OptionKey('b_vscrt')].value in {'mdd', 'mtd'}:
            is_debug = True
        return is_debug
    else:
        # Don't directly assign to is_debug to make mypy happy
        debug_opt = env.coredata.get_option(OptionKey('debug'))
        assert isinstance(debug_opt, bool)
        return debug_opt

class CMakeException(MesonException):
    pass

class CMakeBuildFile:
    def __init__(self, file , is_cmake , is_temp )  :
        self.file = file
        self.is_cmake = is_cmake
        self.is_temp = is_temp

    def __repr__(self)  :
        return '<{}: {}; cmake={}; temp={}>'.format((self.__class__.__name__), (self.file), (self.is_cmake), (self.is_temp))

def _flags_to_list(raw )  :
    # Convert a raw commandline string into a list of strings
    res = []
    curr = ''
    escape = False
    in_string = False
    for i in raw:
        if escape:
            # If the current char is not a quote, the '\' is probably important
            if i not in ['"', "'"]:
                curr += '\\'
            curr += i
            escape = False
        elif i == '\\':
            escape = True
        elif i in ['"', "'"]:
            in_string = not in_string
        elif i in [' ', '\n']:
            if in_string:
                curr += i
            else:
                res += [curr]
                curr = ''
        else:
            curr += i
    res += [curr]
    res = list(filter(lambda x: len(x) > 0, res))
    return res

def cmake_get_generator_args(env )  :
    backend_name = env.coredata.get_option(OptionKey('backend'))
    assert isinstance(backend_name, str)
    assert backend_name in backend_generator_map
    return ['-G', backend_generator_map[backend_name]]

def cmake_defines_to_args(raw , permissive  = False)  :
    res = []  # type: T.List[str]
    if not isinstance(raw, list):
        raw = [raw]

    for i in raw:
        if not isinstance(i, dict):
            raise MesonException('Invalid CMake defines. Expected a dict, but got a {}'.format(type(i).__name__))
        for key, val in i.items():
            assert isinstance(key, str)
            if key in blacklist_cmake_defs:
                mlog.warning('Setting', mlog.bold(key), 'is not supported. See the meson docs for cross compilation support:')
                mlog.warning('  - URL: https://mesonbuild.com/CMake-module.html#cross-compilation')
                mlog.warning('  --> Ignoring this option')
                continue
            if isinstance(val, (str, int, float)):
                res += ['-D{}={}'.format((key), (val))]
            elif isinstance(val, bool):
                val_str = 'ON' if val else 'OFF'
                res += ['-D{}={}'.format((key), (val_str))]
            else:
                raise MesonException('Type "{}" of "{}" is not supported as for a CMake define value'.format(type(val).__name__, key))

    return res

# TODO: this functuin will become obsolete once the `cmake_args` kwarg is dropped
def check_cmake_args(args )  :
    res = []  # type: T.List[str]
    dis = ['-D' + x for x in blacklist_cmake_defs]
    assert dis  # Ensure that dis is not empty.
    for i in args:
        if any([i.startswith(x) for x in dis]):
            mlog.warning('Setting', mlog.bold(i), 'is not supported. See the meson docs for cross compilation support:')
            mlog.warning('  - URL: https://mesonbuild.com/CMake-module.html#cross-compilation')
            mlog.warning('  --> Ignoring this option')
            continue
        res += [i]
    return res

class CMakeInclude:
    def __init__(self, path , isSystem  = False):
        self.path     = path
        self.isSystem = isSystem

    def __repr__(self)  :
        return '<CMakeInclude: {} -- isSystem = {}>'.format((self.path), (self.isSystem))

class CMakeFileGroup:
    def __init__(self, data  )  :
        self.defines      = data.get('defines', '')                       # type: str
        self.flags        = _flags_to_list(data.get('compileFlags', ''))  # type: T.List[str]
        self.is_generated = data.get('isGenerated', False)                # type: bool
        self.language     = data.get('language', 'C')                     # type: str
        self.sources      = [Path(x) for x in data.get('sources', [])]    # type: T.List[Path]

        # Fix the include directories
        self.includes = []  # type: T.List[CMakeInclude]
        for i in data.get('includePath', []):
            if isinstance(i, dict) and 'path' in i:
                isSystem = i.get('isSystem', False)
                assert isinstance(isSystem, bool)
                assert isinstance(i['path'], str)
                self.includes += [CMakeInclude(Path(i['path']), isSystem)]
            elif isinstance(i, str):
                self.includes += [CMakeInclude(Path(i))]

    def log(self)  :
        mlog.log('flags        =', mlog.bold(', '.join(self.flags)))
        mlog.log('defines      =', mlog.bold(', '.join(self.defines)))
        mlog.log('includes     =', mlog.bold(', '.join([str(x) for x in self.includes])))
        mlog.log('is_generated =', mlog.bold('true' if self.is_generated else 'false'))
        mlog.log('language     =', mlog.bold(self.language))
        mlog.log('sources:')
        for i in self.sources:
            with mlog.nested():
                mlog.log(i.as_posix())

class CMakeTarget:
    def __init__(self, data  )  :
        self.artifacts               = [Path(x) for x in data.get('artifacts', [])]         # type: T.List[Path]
        self.src_dir                 = Path(data.get('sourceDirectory', ''))                # type: Path
        self.build_dir               = Path(data.get('buildDirectory', ''))                 # type: Path
        self.name                    = data.get('name', '')                                 # type: str
        self.full_name               = data.get('fullName', '')                             # type: str
        self.install                 = data.get('hasInstallRule', False)                    # type: bool
        self.install_paths           = [Path(x) for x in set(data.get('installPaths', []))] # type: T.List[Path]
        self.link_lang               = data.get('linkerLanguage', '')                       # type: str
        self.link_libraries          = _flags_to_list(data.get('linkLibraries', ''))        # type: T.List[str]
        self.link_flags              = _flags_to_list(data.get('linkFlags', ''))            # type: T.List[str]
        self.link_lang_flags         = _flags_to_list(data.get('linkLanguageFlags', ''))    # type: T.List[str]
        # self.link_path             = Path(data.get('linkPath', ''))                       # type: Path
        self.type                    = data.get('type', 'EXECUTABLE')                       # type: str
        # self.is_generator_provided = data.get('isGeneratorProvided', False)               # type: bool
        self.files                   = []                                                   # type: T.List[CMakeFileGroup]

        for i in data.get('fileGroups', []):
            self.files += [CMakeFileGroup(i)]

    def log(self)  :
        mlog.log('artifacts             =', mlog.bold(', '.join([x.as_posix() for x in self.artifacts])))
        mlog.log('src_dir               =', mlog.bold(self.src_dir.as_posix()))
        mlog.log('build_dir             =', mlog.bold(self.build_dir.as_posix()))
        mlog.log('name                  =', mlog.bold(self.name))
        mlog.log('full_name             =', mlog.bold(self.full_name))
        mlog.log('install               =', mlog.bold('true' if self.install else 'false'))
        mlog.log('install_paths         =', mlog.bold(', '.join([x.as_posix() for x in self.install_paths])))
        mlog.log('link_lang             =', mlog.bold(self.link_lang))
        mlog.log('link_libraries        =', mlog.bold(', '.join(self.link_libraries)))
        mlog.log('link_flags            =', mlog.bold(', '.join(self.link_flags)))
        mlog.log('link_lang_flags       =', mlog.bold(', '.join(self.link_lang_flags)))
        # mlog.log('link_path             =', mlog.bold(self.link_path))
        mlog.log('type                  =', mlog.bold(self.type))
        # mlog.log('is_generator_provided =', mlog.bold('true' if self.is_generator_provided else 'false'))
        for idx, i in enumerate(self.files):
            mlog.log('Files {}:'.format((idx)))
            with mlog.nested():
                i.log()

class CMakeProject:
    def __init__(self, data  )  :
        self.src_dir   = Path(data.get('sourceDirectory', ''))   # type: Path
        self.build_dir = Path(data.get('buildDirectory', ''))    # type: Path
        self.name      = data.get('name', '')                    # type: str
        self.targets   = []                                      # type: T.List[CMakeTarget]

        for i in data.get('targets', []):
            self.targets += [CMakeTarget(i)]

    def log(self)  :
        mlog.log('src_dir   =', mlog.bold(self.src_dir.as_posix()))
        mlog.log('build_dir =', mlog.bold(self.build_dir.as_posix()))
        mlog.log('name      =', mlog.bold(self.name))
        for idx, i in enumerate(self.targets):
            mlog.log('Target {}:'.format((idx)))
            with mlog.nested():
                i.log()

class CMakeConfiguration:
    def __init__(self, data  )  :
        self.name     = data.get('name', '')   # type: str
        self.projects = []                     # type: T.List[CMakeProject]
        for i in data.get('projects', []):
            self.projects += [CMakeProject(i)]

    def log(self)  :
        mlog.log('name =', mlog.bold(self.name))
        for idx, i in enumerate(self.projects):
            mlog.log('Project {}:'.format((idx)))
            with mlog.nested():
                i.log()

class SingleTargetOptions:
    def __init__(self)  :
        self.opts = {}       # type: T.Dict[str, str]
        self.lang_args = {}  # type: T.Dict[str, T.List[str]]
        self.link_args = []  # type: T.List[str]
        self.install = 'preserve'

    def set_opt(self, opt , val )  :
        self.opts[opt] = val

    def append_args(self, lang , args )  :
        if lang not in self.lang_args:
            self.lang_args[lang] = []
        self.lang_args[lang] += args

    def append_link_args(self, args )  :
        self.link_args += args

    def set_install(self, install )  :
        self.install = 'true' if install else 'false'

    def get_override_options(self, initial )  :
        res = []  # type: T.List[str]
        for i in initial:
            opt = i[:i.find('=')]
            if opt not in self.opts:
                res += [i]
        res += ['{}={}'.format((k), (v)) for k, v in self.opts.items()]
        return res

    def get_compile_args(self, lang , initial )  :
        if lang in self.lang_args:
            return initial + self.lang_args[lang]
        return initial

    def get_link_args(self, initial )  :
        return initial + self.link_args

    def get_install(self, initial )  :
        return {'preserve': initial, 'true': True, 'false': False}[self.install]

class TargetOptions:
    def __init__(self)  :
        self.global_options = SingleTargetOptions()
        self.target_options = {}  # type: T.Dict[str, SingleTargetOptions]

    def __getitem__(self, tgt )  :
        if tgt not in self.target_options:
            self.target_options[tgt] = SingleTargetOptions()
        return self.target_options[tgt]

    def get_override_options(self, tgt , initial )  :
        initial = self.global_options.get_override_options(initial)
        if tgt in self.target_options:
            initial = self.target_options[tgt].get_override_options(initial)
        return initial

    def get_compile_args(self, tgt , lang , initial )  :
        initial = self.global_options.get_compile_args(lang, initial)
        if tgt in self.target_options:
            initial = self.target_options[tgt].get_compile_args(lang, initial)
        return initial

    def get_link_args(self, tgt , initial )  :
        initial = self.global_options.get_link_args(initial)
        if tgt in self.target_options:
            initial = self.target_options[tgt].get_link_args(initial)
        return initial

    def get_install(self, tgt , initial )  :
        initial = self.global_options.get_install(initial)
        if tgt in self.target_options:
            initial = self.target_options[tgt].get_install(initial)
        return initial
