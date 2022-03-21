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

import abc
import contextlib, os.path, re
import enum
import itertools
import typing as T
from functools import lru_cache

from .. import coredata
from .. import mlog
from .. import mesonlib
from ..mesonlib import (
    HoldableObject,
    EnvironmentException, MachineChoice, MesonException,
    Popen_safe, LibType, TemporaryDirectoryWinProof, OptionKey,
)

from ..arglist import CompilerArgs

if T.TYPE_CHECKING:
    from ..build import BuildTarget
    from ..coredata import KeyedOptionDictType
    from ..envconfig import MachineInfo
    from ..environment import Environment
    from ..linkers import DynamicLinker, RSPFileSyntax
    from ..dependencies import Dependency

    CompilerType = T.TypeVar('CompilerType', bound='Compiler')
    _T = T.TypeVar('_T')

"""This file contains the data files of all compilers Meson knows
about. To support a new compiler, add its information below.
Also add corresponding autodetection code in environment.py."""

header_suffixes = ('h', 'hh', 'hpp', 'hxx', 'H', 'ipp', 'moc', 'vapi', 'di')  # type: T.Tuple[str, ...]
obj_suffixes = ('o', 'obj', 'res')  # type: T.Tuple[str, ...]
# To the emscripten compiler, .js files are libraries
lib_suffixes = ('a', 'lib', 'dll', 'dll.a', 'dylib', 'so', 'js')  # type: T.Tuple[str, ...]
# Mapping of language to suffixes of files that should always be in that language
# This means we can't include .h headers here since they could be C, C++, ObjC, etc.
lang_suffixes = {
    'c': ('c',),
    'cpp': ('cpp', 'cc', 'cxx', 'c++', 'hh', 'hpp', 'ipp', 'hxx', 'ino', 'ixx', 'C'),
    'cuda': ('cu',),
    # f90, f95, f03, f08 are for free-form fortran ('f90' recommended)
    # f, for, ftn, fpp are for fixed-form fortran ('f' or 'for' recommended)
    'fortran': ('f90', 'f95', 'f03', 'f08', 'f', 'for', 'ftn', 'fpp'),
    'd': ('d', 'di'),
    'objc': ('m',),
    'objcpp': ('mm',),
    'rust': ('rs',),
    'vala': ('vala', 'vapi', 'gs'),
    'cs': ('cs',),
    'swift': ('swift',),
    'java': ('java',),
    'cython': ('pyx', ),
}  # type: T.Dict[str, T.Tuple[str, ...]]
all_languages = lang_suffixes.keys()
cpp_suffixes = lang_suffixes['cpp'] + ('h',)  # type: T.Tuple[str, ...]
c_suffixes = lang_suffixes['c'] + ('h',)  # type: T.Tuple[str, ...]
# List of languages that by default consume and output libraries following the
# C ABI; these can generally be used interchangeably
clib_langs = ('objcpp', 'cpp', 'objc', 'c', 'fortran',)  # type: T.Tuple[str, ...]
# List of assembler suffixes that can be linked with C code directly by the linker
assembler_suffixes   = ('s', 'S')
# List of languages that can be linked with C code directly by the linker
# used in build.py:process_compilers() and build.py:get_dynamic_linker()
clink_langs = ('d', 'cuda') + clib_langs  # type: T.Tuple[str, ...]
clink_suffixes = tuple()  # type: T.Tuple[str, ...]
for _l in clink_langs + ('vala',):
    clink_suffixes += lang_suffixes[_l]
clink_suffixes += ('h', 'll', 's')
all_suffixes = set(itertools.chain(*lang_suffixes.values(), clink_suffixes))  # type: T.Set[str]
SUFFIX_TO_LANG = dict(itertools.chain(*(
    [(suffix, lang) for suffix in v] for lang, v in lang_suffixes.items()))) # type: T.Dict[str, str]

# Languages that should use LDFLAGS arguments when linking.
LANGUAGES_USING_LDFLAGS = {'objcpp', 'cpp', 'objc', 'c', 'fortran', 'd', 'cuda'}  # type: T.Set[str]
# Languages that should use CPPFLAGS arguments when linking.
LANGUAGES_USING_CPPFLAGS = {'c', 'cpp', 'objc', 'objcpp'}  # type: T.Set[str]
soregex = re.compile(r'.*\.so(\.[0-9]+)?(\.[0-9]+)?(\.[0-9]+)?$')

# Environment variables that each lang uses.
CFLAGS_MAPPING   = {
    'c': 'CFLAGS',
    'cpp': 'CXXFLAGS',
    'cuda': 'CUFLAGS',
    'objc': 'OBJCFLAGS',
    'objcpp': 'OBJCXXFLAGS',
    'fortran': 'FFLAGS',
    'd': 'DFLAGS',
    'vala': 'VALAFLAGS',
    'rust': 'RUSTFLAGS',
    'cython': 'CYTHONFLAGS',
}

# All these are only for C-linkable languages; see `clink_langs` above.

def sort_clink(lang )  :
    '''
    Sorting function to sort the list of languages according to
    reversed(compilers.clink_langs) and append the unknown langs in the end.
    The purpose is to prefer C over C++ for files that can be compiled by
    both such as assembly, C, etc. Also applies to ObjC, ObjC++, etc.
    '''
    if lang not in clink_langs:
        return 1
    return -clink_langs.index(lang)

def is_header(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname
    suffix = fname.split('.')[-1]
    return suffix in header_suffixes

def is_source(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname
    suffix = fname.split('.')[-1].lower()
    return suffix in clink_suffixes

def is_assembly(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname
    return fname.split('.')[-1].lower() == 's'

def is_llvm_ir(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname
    return fname.split('.')[-1] == 'll'

@lru_cache(maxsize=None)
def cached_by_name(fname )  :
    suffix = fname.split('.')[-1]
    return suffix in obj_suffixes

def is_object(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname
    return cached_by_name(fname)

def is_library(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname

    if soregex.match(fname):
        return True

    suffix = fname.split('.')[-1]
    return suffix in lib_suffixes

def is_known_suffix(fname )  :
    if isinstance(fname, mesonlib.File):
        fname = fname.fname
    suffix = fname.split('.')[-1]

    return suffix in all_suffixes


class CompileCheckMode(enum.Enum):

    PREPROCESS = 'preprocess'
    COMPILE = 'compile'
    LINK = 'link'


cuda_buildtype_args = {'plain': [],
                       'debug': ['-g', '-G'],
                       'debugoptimized': ['-g', '-lineinfo'],
                       'release': [],
                       'minsize': [],
                       'custom': [],
                       }  # type: T.Dict[str, T.List[str]]
java_buildtype_args = {'plain': [],
                       'debug': ['-g'],
                       'debugoptimized': ['-g'],
                       'release': [],
                       'minsize': [],
                       'custom': [],
                       }  # type: T.Dict[str, T.List[str]]

rust_buildtype_args = {'plain': [],
                       'debug': [],
                       'debugoptimized': [],
                       'release': [],
                       'minsize': [],
                       'custom': [],
                       }  # type: T.Dict[str, T.List[str]]

d_gdc_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': ['-finline-functions'],
                        'release': ['-finline-functions'],
                        'minsize': [],
                        'custom': [],
                        }  # type: T.Dict[str, T.List[str]]

d_ldc_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': ['-enable-inlining', '-Hkeep-all-bodies'],
                        'release': ['-enable-inlining', '-Hkeep-all-bodies'],
                        'minsize': [],
                        'custom': [],
                        }  # type: T.Dict[str, T.List[str]]

d_dmd_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': ['-inline'],
                        'release': ['-inline'],
                        'minsize': [],
                        'custom': [],
                        }  # type: T.Dict[str, T.List[str]]

mono_buildtype_args = {'plain': [],
                       'debug': [],
                       'debugoptimized': ['-optimize+'],
                       'release': ['-optimize+'],
                       'minsize': [],
                       'custom': [],
                       }  # type: T.Dict[str, T.List[str]]

swift_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': [],
                        'release': [],
                        'minsize': [],
                        'custom': [],
                        }  # type: T.Dict[str, T.List[str]]

gnu_winlibs = ['-lkernel32', '-luser32', '-lgdi32', '-lwinspool', '-lshell32',
               '-lole32', '-loleaut32', '-luuid', '-lcomdlg32', '-ladvapi32']  # type: T.List[str]

msvc_winlibs = ['kernel32.lib', 'user32.lib', 'gdi32.lib',
                'winspool.lib', 'shell32.lib', 'ole32.lib', 'oleaut32.lib',
                'uuid.lib', 'comdlg32.lib', 'advapi32.lib']  # type: T.List[str]

clike_optimization_args = {'0': [],
                           'g': [],
                           '1': ['-O1'],
                           '2': ['-O2'],
                           '3': ['-O3'],
                           's': ['-Os'],
                           }  # type: T.Dict[str, T.List[str]]

cuda_optimization_args = {'0': [],
                          'g': ['-O0'],
                          '1': ['-O1'],
                          '2': ['-O2'],
                          '3': ['-O3'],
                          's': ['-O3']
                          }  # type: T.Dict[str, T.List[str]]

cuda_debug_args = {False: [],
                   True: ['-g']}  # type: T.Dict[bool, T.List[str]]

clike_debug_args = {False: [],
                    True: ['-g']}  # type: T.Dict[bool, T.List[str]]

base_options  = {
    OptionKey('b_pch'): coredata.UserBooleanOption('Use precompiled headers', True),
    OptionKey('b_lto'): coredata.UserBooleanOption('Use link time optimization', False),
    OptionKey('b_lto'): coredata.UserBooleanOption('Use link time optimization', False),
    OptionKey('b_lto_threads'): coredata.UserIntegerOption('Use multiple threads for Link Time Optimization', (None, None, 0)),
    OptionKey('b_lto_mode'): coredata.UserComboOption('Select between different LTO modes.',
                                                      ['default', 'thin'],
                                                      'default'),
    OptionKey('b_sanitize'): coredata.UserComboOption('Code sanitizer to use',
                                                      ['none', 'address', 'thread', 'undefined', 'memory', 'address,undefined'],
                                                      'none'),
    OptionKey('b_lundef'): coredata.UserBooleanOption('Use -Wl,--no-undefined when linking', True),
    OptionKey('b_asneeded'): coredata.UserBooleanOption('Use -Wl,--as-needed when linking', True),
    OptionKey('b_pgo'): coredata.UserComboOption('Use profile guided optimization',
                                                 ['off', 'generate', 'use'],
                                                 'off'),
    OptionKey('b_coverage'): coredata.UserBooleanOption('Enable coverage tracking.', False),
    OptionKey('b_colorout'): coredata.UserComboOption('Use colored output',
                                                      ['auto', 'always', 'never'],
                                                      'always'),
    OptionKey('b_ndebug'): coredata.UserComboOption('Disable asserts', ['true', 'false', 'if-release'], 'false'),
    OptionKey('b_staticpic'): coredata.UserBooleanOption('Build static libraries as position independent', True),
    OptionKey('b_pie'): coredata.UserBooleanOption('Build executables as position independent', False),
    OptionKey('b_bitcode'): coredata.UserBooleanOption('Generate and embed bitcode (only macOS/iOS/tvOS)', False),
    OptionKey('b_vscrt'): coredata.UserComboOption('VS run-time library type to use.',
                                                   ['none', 'md', 'mdd', 'mt', 'mtd', 'from_buildtype', 'static_from_buildtype'],
                                                   'from_buildtype'),
}

def option_enabled(boptions , options ,
                   option )  :
    try:
        if option not in boptions:
            return False
        ret = options[option].value
        assert isinstance(ret, bool), 'must return bool'  # could also be str
        return ret
    except KeyError:
        return False


def get_option_value(options , opt , fallback )  :
    """Get the value of an option, or the fallback value."""
    try:
        v  = options[opt].value
    except KeyError:
        return fallback

    assert isinstance(v, type(fallback)), 'Should have {!r} but was {!r}'.format((type(fallback)), (type(v)))
    # Mypy doesn't understand that the above assert ensures that v is type _T
    return v


def get_base_compile_args(options , compiler )  :
    args = []  # type T.List[str]
    try:
        if options[OptionKey('b_lto')].value:
            args.extend(compiler.get_lto_compile_args(
                threads=get_option_value(options, OptionKey('b_lto_threads'), 0),
                mode=get_option_value(options, OptionKey('b_lto_mode'), 'default')))
    except KeyError:
        pass
    try:
        args += compiler.get_colorout_args(options[OptionKey('b_colorout')].value)
    except KeyError:
        pass
    try:
        args += compiler.sanitizer_compile_args(options[OptionKey('b_sanitize')].value)
    except KeyError:
        pass
    try:
        pgo_val = options[OptionKey('b_pgo')].value
        if pgo_val == 'generate':
            args.extend(compiler.get_profile_generate_args())
        elif pgo_val == 'use':
            args.extend(compiler.get_profile_use_args())
    except KeyError:
        pass
    try:
        if options[OptionKey('b_coverage')].value:
            args += compiler.get_coverage_args()
    except KeyError:
        pass
    try:
        if (options[OptionKey('b_ndebug')].value == 'true' or
                (options[OptionKey('b_ndebug')].value == 'if-release' and
                 options[OptionKey('buildtype')].value in {'release', 'plain'})):
            args += compiler.get_disable_assert_args()
    except KeyError:
        pass
    # This does not need a try...except
    if option_enabled(compiler.base_options, options, OptionKey('b_bitcode')):
        args.append('-fembed-bitcode')
    try:
        crt_val = options[OptionKey('b_vscrt')].value
        buildtype = options[OptionKey('buildtype')].value
        try:
            args += compiler.get_crt_compile_args(crt_val, buildtype)
        except AttributeError:
            pass
    except KeyError:
        pass
    return args

def get_base_link_args(options , linker ,
                       is_shared_module )  :
    args = []  # type: T.List[str]
    try:
        if options[OptionKey('b_lto')].value:
            args.extend(linker.get_lto_link_args(
                threads=get_option_value(options, OptionKey('b_lto_threads'), 0),
                mode=get_option_value(options, OptionKey('b_lto_mode'), 'default')))
    except KeyError:
        pass
    try:
        args += linker.sanitizer_link_args(options[OptionKey('b_sanitize')].value)
    except KeyError:
        pass
    try:
        pgo_val = options[OptionKey('b_pgo')].value
        if pgo_val == 'generate':
            args.extend(linker.get_profile_generate_args())
        elif pgo_val == 'use':
            args.extend(linker.get_profile_use_args())
    except KeyError:
        pass
    try:
        if options[OptionKey('b_coverage')].value:
            args += linker.get_coverage_link_args()
    except KeyError:
        pass

    as_needed = option_enabled(linker.base_options, options, OptionKey('b_asneeded'))
    bitcode = option_enabled(linker.base_options, options, OptionKey('b_bitcode'))
    # Shared modules cannot be built with bitcode_bundle because
    # -bitcode_bundle is incompatible with -undefined and -bundle
    if bitcode and not is_shared_module:
        args.extend(linker.bitcode_args())
    elif as_needed:
        # -Wl,-dead_strip_dylibs is incompatible with bitcode
        args.extend(linker.get_asneeded_args())

    # Apple's ld (the only one that supports bitcode) does not like -undefined
    # arguments or -headerpad_max_install_names when bitcode is enabled
    if not bitcode:
        args.extend(linker.headerpad_args())
        if (not is_shared_module and
                option_enabled(linker.base_options, options, OptionKey('b_lundef'))):
            args.extend(linker.no_undefined_link_args())
        else:
            args.extend(linker.get_allow_undefined_link_args())

    try:
        crt_val = options[OptionKey('b_vscrt')].value
        buildtype = options[OptionKey('buildtype')].value
        try:
            args += linker.get_crt_link_args(crt_val, buildtype)
        except AttributeError:
            pass
    except KeyError:
        pass
    return args


class CrossNoRunException(MesonException):
    pass

class RunResult(HoldableObject):
    def __init__(self, compiled , returncode  = 999,
                 stdout  = 'UNDEFINED', stderr  = 'UNDEFINED'):
        self.compiled = compiled
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CompileResult(HoldableObject):

    """The result of Compiler.compiles (and friends)."""

    def __init__(self, stdo  = None, stde  = None,
                 args  = None,
                 returncode  = 999, pid  = -1,
                 text_mode  = True,
                 input_name  = None,
                 output_name  = None,
                 command  = None, cached  = False):
        self.stdout = stdo
        self.stderr = stde
        self.input_name = input_name
        self.output_name = output_name
        self.command = command or []
        self.args = args or []
        self.cached = cached
        self.returncode = returncode
        self.pid = pid
        self.text_mode = text_mode


class Compiler(HoldableObject, metaclass=abc.ABCMeta):
    # Libraries to ignore in find_library() since they are provided by the
    # compiler or the C library. Currently only used for MSVC.
    ignore_libs = []  # type: T.List[str]
    # Libraries that are internal compiler implementations, and must not be
    # manually searched.
    internal_libs = []  # type: T.List[str]

    LINKER_PREFIX = None  # type: T.Union[None, str, T.List[str]]
    INVOKES_LINKER = True

    #language: str
    #id: str
    #warn_args: T.Dict[str, T.List[str]]

    def __init__(self, exelist , version ,
                 for_machine , info ,
                 linker  = None,
                 full_version  = None, is_cross  = False):
        self.exelist = exelist
        # In case it's been overridden by a child class already
        if not hasattr(self, 'file_suffixes'):
            self.file_suffixes = lang_suffixes[self.language]
        if not hasattr(self, 'can_compile_suffixes'):
            self.can_compile_suffixes = set(self.file_suffixes)
        self.default_suffix = self.file_suffixes[0]
        self.version = version
        self.full_version = full_version
        self.for_machine = for_machine
        self.base_options  = set()
        self.linker = linker
        self.info = info
        self.is_cross = is_cross

    def __repr__(self)  :
        repr_str = "<{0}: v{1} `{2}`>"
        return repr_str.format(self.__class__.__name__, self.version,
                               ' '.join(self.exelist))

    @lru_cache(maxsize=None)
    def can_compile(self, src )  :
        if isinstance(src, mesonlib.File):
            src = src.fname
        suffix = os.path.splitext(src)[1]
        if suffix != '.C':
            suffix = suffix.lower()
        return bool(suffix) and suffix[1:] in self.can_compile_suffixes

    def get_id(self)  :
        return self.id

    def get_linker_id(self)  :
        # There is not guarantee that we have a dynamic linker instance, as
        # some languages don't have separate linkers and compilers. In those
        # cases return the compiler id
        try:
            return self.linker.id
        except AttributeError:
            return self.id

    def get_version_string(self)  :
        details = [self.id, self.version]
        if self.full_version:
            details += ['"%s"' % (self.full_version)]
        return '(%s)' % (' '.join(details))

    def get_language(self)  :
        return self.language

    @classmethod
    def get_display_language(cls)  :
        return cls.language.capitalize()

    def get_default_suffix(self)  :
        return self.default_suffix

    def get_define(self, dname , prefix , env ,
                   extra_args   ,
                   dependencies ,
                   disable_cache  = False)   :
        raise EnvironmentException('%s does not support get_define ' % self.get_id())

    def compute_int(self, expression , low , high ,
                    guess , prefix , env , *,
                    extra_args    ,
                    dependencies )  :
        raise EnvironmentException('%s does not support compute_int ' % self.get_id())

    def compute_parameters_with_absolute_paths(self, parameter_list ,
                                               build_dir )  :
        raise EnvironmentException('%s does not support compute_parameters_with_absolute_paths ' % self.get_id())

    def has_members(self, typename , membernames ,
                    prefix , env , *,
                    extra_args     = None,
                    dependencies  = None)   :
        raise EnvironmentException('%s does not support has_member(s) ' % self.get_id())

    def has_type(self, typename , prefix , env ,
                 extra_args   , *,
                 dependencies  = None)   :
        raise EnvironmentException('%s does not support has_type ' % self.get_id())

    def symbols_have_underscore_prefix(self, env )  :
        raise EnvironmentException('%s does not support symbols_have_underscore_prefix ' % self.get_id())

    def get_exelist(self)  :
        return self.exelist.copy()

    def get_linker_exelist(self)  :
        return self.linker.get_exelist()

    @abc.abstractmethod
    def get_output_args(self, outputname )  :
        pass

    def get_linker_output_args(self, outputname )  :
        return self.linker.get_output_args(outputname)

    def get_linker_search_args(self, dirname )  :
        return self.linker.get_search_args(dirname)

    def get_builtin_define(self, define )  :
        raise EnvironmentException('%s does not support get_builtin_define.' % self.id)

    def has_builtin_define(self, define )  :
        raise EnvironmentException('%s does not support has_builtin_define.' % self.id)

    def get_always_args(self)  :
        return []

    def can_linker_accept_rsp(self)  :
        """
        Determines whether the linker can accept arguments using the @rsp syntax.
        """
        return self.linker.get_accepts_rsp()

    def get_linker_always_args(self)  :
        return self.linker.get_always_args()

    def get_linker_lib_prefix(self)  :
        return self.linker.get_lib_prefix()

    def gen_import_library_args(self, implibname )  :
        """
        Used only on Windows for libraries that need an import library.
        This currently means C, C++, Fortran.
        """
        return []

    def get_options(self)  :
        return {}

    def get_option_compile_args(self, options )  :
        return []

    def get_option_link_args(self, options )  :
        return self.linker.get_option_args(options)

    def check_header(self, hname , prefix , env , *,
                     extra_args     = None,
                     dependencies  = None)   :
        """Check that header is usable.

        Returns a two item tuple of bools. The first bool is whether the
        check succeeded, the second is whether the result was cached (True)
        or run fresh (False).
        """
        raise EnvironmentException('Language %s does not support header checks.' % self.get_display_language())

    def has_header(self, hname , prefix , env , *,
                   extra_args     = None,
                   dependencies  = None,
                   disable_cache  = False)   :
        """Check that header is exists.

        This check will return true if the file exists, even if it contains:

        ```c
        # error "You thought you could use this, LOLZ!"
        ```

        Use check_header if your header only works in some cases.

        Returns a two item tuple of bools. The first bool is whether the
        check succeeded, the second is whether the result was cached (True)
        or run fresh (False).
        """
        raise EnvironmentException('Language %s does not support header checks.' % self.get_display_language())

    def has_header_symbol(self, hname , symbol , prefix ,
                          env , *,
                          extra_args     = None,
                          dependencies  = None)   :
        raise EnvironmentException('Language %s does not support header symbol checks.' % self.get_display_language())

    def run(self, code , env , *,
            extra_args     = None,
            dependencies  = None)  :
        raise EnvironmentException('Language %s does not support run checks.' % self.get_display_language())

    def sizeof(self, typename , prefix , env , *,
               extra_args     = None,
               dependencies  = None)  :
        raise EnvironmentException('Language %s does not support sizeof checks.' % self.get_display_language())

    def alignment(self, typename , prefix , env , *,
                  extra_args  = None,
                  dependencies  = None)  :
        raise EnvironmentException('Language %s does not support alignment checks.' % self.get_display_language())

    def has_function(self, funcname , prefix , env , *,
                     extra_args  = None,
                     dependencies  = None)   :
        """See if a function exists.

        Returns a two item tuple of bools. The first bool is whether the
        check succeeded, the second is whether the result was cached (True)
        or run fresh (False).
        """
        raise EnvironmentException('Language %s does not support function checks.' % self.get_display_language())

    def unix_args_to_native(self, args )  :
        "Always returns a copy that can be independently mutated"
        return args.copy()

    @classmethod
    def native_args_to_unix(cls, args )  :
        "Always returns a copy that can be independently mutated"
        return args.copy()

    def find_library(self, libname , env , extra_dirs ,
                     libtype  = LibType.PREFER_SHARED)  :
        raise EnvironmentException('Language {} does not support library finding.'.format((self.get_display_language())))

    def get_library_naming(self, env , libtype ,
                           strict  = False)   :
        raise EnvironmentException(
            'Language {} does not support get_library_naming.'.format(
                self.get_display_language()))

    def get_program_dirs(self, env )  :
        return []

    def has_multi_arguments(self, args , env )   :
        raise EnvironmentException(
            'Language {} does not support has_multi_arguments.'.format(
                self.get_display_language()))

    def has_multi_link_arguments(self, args , env )   :
        return self.linker.has_multi_arguments(args, env)

    def _get_compile_output(self, dirname , mode )  :
        # TODO: mode should really be an enum
        # In pre-processor mode, the output is sent to stdout and discarded
        if mode == 'preprocess':
            return None
        # Extension only matters if running results; '.exe' is
        # guaranteed to be executable on every platform.
        if mode == 'link':
            suffix = 'exe'
        else:
            suffix = 'obj'
        return os.path.join(dirname, 'output.' + suffix)

    def get_compiler_args_for_mode(self, mode )  :
        # TODO: mode should really be an enum
        args = []  # type: T.List[str]
        args += self.get_always_args()
        if mode is CompileCheckMode.COMPILE:
            args += self.get_compile_only_args()
        elif mode is CompileCheckMode.PREPROCESS:
            args += self.get_preprocess_only_args()
        else:
            assert mode is CompileCheckMode.LINK
        return args

    def compiler_args(self, args  = None)  :
        """Return an appropriate CompilerArgs instance for this class."""
        return CompilerArgs(self, args)

    @contextlib.contextmanager
    def compile(self, code ,
                extra_args    = None,
                *, mode  = 'link', want_output  = False,
                temp_dir  = None)  :
        # TODO: there isn't really any reason for this to be a contextmanager
        if extra_args is None:
            extra_args = []

        with TemporaryDirectoryWinProof(dir=temp_dir) as tmpdirname:
            no_ccache = False
            if isinstance(code, str):
                srcname = os.path.join(tmpdirname,
                                       'testfile.' + self.default_suffix)
                with open(srcname, 'w', encoding='utf-8') as ofile:
                    ofile.write(code)
                # ccache would result in a cache miss
                no_ccache = True
                contents = code
            else:
                srcname = code.fname
                if not is_object(code.fname):
                    with open(code.fname, encoding='utf-8') as f:
                        contents = f.read()
                else:
                    contents = '<binary>'

            # Construct the compiler command-line
            commands = self.compiler_args()
            commands.append(srcname)

            # Preprocess mode outputs to stdout, so no output args
            output = self._get_compile_output(tmpdirname, mode)
            if mode != 'preprocess':
                commands += self.get_output_args(output)
            commands.extend(self.get_compiler_args_for_mode(CompileCheckMode(mode)))

            # extra_args must be last because it could contain '/link' to
            # pass args to VisualStudio's linker. In that case everything
            # in the command line after '/link' is given to the linker.
            if extra_args:
                commands += extra_args
            # Generate full command-line with the exelist
            command_list = self.get_exelist() + commands.to_native()
            mlog.debug('Running compile:')
            mlog.debug('Working directory: ', tmpdirname)
            mlog.debug('Command line: ', ' '.join(command_list), '\n')
            mlog.debug('Code:\n', contents)
            os_env = os.environ.copy()
            os_env['LC_ALL'] = 'C'
            if no_ccache:
                os_env['CCACHE_DISABLE'] = '1'
            p, stdo, stde = Popen_safe(command_list, cwd=tmpdirname, env=os_env)
            mlog.debug('Compiler stdout:\n', stdo)
            mlog.debug('Compiler stderr:\n', stde)

            result = CompileResult(stdo, stde, list(commands), p.returncode, p.pid, input_name=srcname)
            if want_output:
                result.output_name = output
            yield result

    @contextlib.contextmanager
    def cached_compile(self, code , cdata , *,
                       extra_args    = None,
                       mode  = 'link',
                       temp_dir  = None)  :
        # TODO: There's isn't really any reason for this to be a context manager

        # Calculate the key
        textra_args = tuple(extra_args) if extra_args is not None else tuple()  # type: T.Tuple[str, ...]
        key = (tuple(self.exelist), self.version, code, textra_args, mode)  # type: coredata.CompilerCheckCacheKey

        # Check if not cached, and generate, otherwise get from the cache
        if key in cdata.compiler_check_cache:
            p = cdata.compiler_check_cache[key]  # type: CompileResult
            p.cached = True
            mlog.debug('Using cached compile:')
            mlog.debug('Cached command line: ', ' '.join(p.command), '\n')
            mlog.debug('Code:\n', code)
            mlog.debug('Cached compiler stdout:\n', p.stdout)
            mlog.debug('Cached compiler stderr:\n', p.stderr)
            yield p
        else:
            with self.compile(code, extra_args=extra_args, mode=mode, want_output=False, temp_dir=temp_dir) as p:
                cdata.compiler_check_cache[key] = p
                yield p

    def get_colorout_args(self, colortype )  :
        # TODO: colortype can probably be an emum
        return []

    # Some compilers (msvc) write debug info to a separate file.
    # These args specify where it should be written.
    def get_compile_debugfile_args(self, rel_obj , pch  = False)  :
        return []

    def get_link_debugfile_name(self, targetfile )  :
        return self.linker.get_debugfile_name(targetfile)

    def get_link_debugfile_args(self, targetfile )  :
        return self.linker.get_debugfile_args(targetfile)

    def get_std_shared_lib_link_args(self)  :
        return self.linker.get_std_shared_lib_args()

    def get_std_shared_module_link_args(self, options )  :
        return self.linker.get_std_shared_module_args(options)

    def get_link_whole_for(self, args )  :
        return self.linker.get_link_whole_for(args)

    def get_allow_undefined_link_args(self)  :
        return self.linker.get_allow_undefined_args()

    def no_undefined_link_args(self)  :
        return self.linker.no_undefined_args()

    def get_instruction_set_args(self, instruction_set )  :
        """Compiler arguments needed to enable the given instruction set.

        Return type ay be an empty list meaning nothing needed or None
        meaning the given set is not supported.
        """
        return None

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return self.linker.build_rpath_args(
            env, build_dir, from_dir, rpath_paths, build_rpath, install_rpath)

    def thread_flags(self, env )  :
        return []

    def thread_link_flags(self, env )  :
        return self.linker.thread_flags(env)

    def openmp_flags(self)  :
        raise EnvironmentException('Language %s does not support OpenMP flags.' % self.get_display_language())

    def openmp_link_flags(self)  :
        return self.openmp_flags()

    def language_stdlib_only_link_flags(self, env )  :
        return []

    def gnu_symbol_visibility_args(self, vistype )  :
        return []

    def get_gui_app_args(self, value )  :
        # Only used on Windows
        return self.linker.get_gui_app_args(value)

    def get_win_subsystem_args(self, value )  :
        # By default the dynamic linker is going to return an empty
        # array in case it either doesn't support Windows subsystems
        # or does not target Windows
        return self.linker.get_win_subsystem_args(value)

    def has_func_attribute(self, name , env )   :
        raise EnvironmentException(
            'Language {} does not support function attributes.'.format((self.get_display_language())))

    def get_pic_args(self)  :
        m = 'Language {} does not support position-independent code'
        raise EnvironmentException(m.format(self.get_display_language()))

    def get_pie_args(self)  :
        m = 'Language {} does not support position-independent executable'
        raise EnvironmentException(m.format(self.get_display_language()))

    def get_pie_link_args(self)  :
        return self.linker.get_pie_args()

    def get_argument_syntax(self)  :
        """Returns the argument family type.

        Compilers fall into families if they try to emulate the command line
        interface of another compiler. For example, clang is in the GCC family
        since it accepts most of the same arguments as GCC. ICL (ICC on
        windows) is in the MSVC family since it accepts most of the same
        arguments as MSVC.
        """
        return 'other'

    def get_profile_generate_args(self)  :
        raise EnvironmentException(
            '%s does not support get_profile_generate_args ' % self.get_id())

    def get_profile_use_args(self)  :
        raise EnvironmentException(
            '%s does not support get_profile_use_args ' % self.get_id())

    def remove_linkerlike_args(self, args )  :
        rm_exact = ('-headerpad_max_install_names',)
        rm_prefixes = ('-Wl,', '-L',)
        rm_next = ('-L', '-framework',)
        ret = []  # T.List[str]
        iargs = iter(args)
        for arg in iargs:
            # Remove this argument
            if arg in rm_exact:
                continue
            # If the argument starts with this, but is not *exactly* this
            # f.ex., '-L' should match ['-Lfoo'] but not ['-L', 'foo']
            if arg.startswith(rm_prefixes) and arg not in rm_prefixes:
                continue
            # Ignore this argument and the one after it
            if arg in rm_next:
                next(iargs)
                continue
            ret.append(arg)
        return ret

    def get_lto_compile_args(self, *, threads  = 0, mode  = 'default')  :
        return []

    def get_lto_link_args(self, *, threads  = 0, mode  = 'default')  :
        return self.linker.get_lto_args()

    def sanitizer_compile_args(self, value )  :
        return []

    def sanitizer_link_args(self, value )  :
        return self.linker.sanitizer_args(value)

    def get_asneeded_args(self)  :
        return self.linker.get_asneeded_args()

    def headerpad_args(self)  :
        return self.linker.headerpad_args()

    def bitcode_args(self)  :
        return self.linker.bitcode_args()

    def get_buildtype_args(self, buildtype )  :
        raise EnvironmentException('{} does not implement get_buildtype_args'.format((self.id)))

    def get_buildtype_linker_args(self, buildtype )  :
        return self.linker.get_buildtype_args(buildtype)

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion ,
                        darwin_versions  )  :
        return self.linker.get_soname_args(
            env, prefix, shlib_name, suffix, soversion,
            darwin_versions)

    def get_target_link_args(self, target )  :
        return target.link_args

    def get_dependency_compile_args(self, dep )  :
        return dep.get_compile_args()

    def get_dependency_link_args(self, dep )  :
        return dep.get_link_args()

    @classmethod
    def use_linker_args(cls, linker )  :
        """Get a list of arguments to pass to the compiler to set the linker.
        """
        return []

    def get_coverage_args(self)  :
        return []

    def get_coverage_link_args(self)  :
        return self.linker.get_coverage_args()

    def get_disable_assert_args(self)  :
        return []

    def get_crt_compile_args(self, crt_val , buildtype )  :
        raise EnvironmentException('This compiler does not support Windows CRT selection')

    def get_crt_link_args(self, crt_val , buildtype )  :
        raise EnvironmentException('This compiler does not support Windows CRT selection')

    def get_compile_only_args(self)  :
        return []

    def get_preprocess_only_args(self)  :
        raise EnvironmentException('This compiler does not have a preprocessor')

    def get_default_include_dirs(self)  :
        # TODO: This is a candidate for returning an immutable list
        return []

    def get_largefile_args(self)  :
        '''Enable transparent large-file-support for 32-bit UNIX systems'''
        if not (self.get_argument_syntax() == 'msvc' or self.info.is_darwin()):
            # Enable large-file support unconditionally on all platforms other
            # than macOS and MSVC. macOS is now 64-bit-only so it doesn't
            # need anything special, and MSVC doesn't have automatic LFS.
            # You must use the 64-bit counterparts explicitly.
            # glibc, musl, and uclibc, and all BSD libcs support this. On Android,
            # support for transparent LFS is available depending on the version of
            # Bionic: https://github.com/android/platform_bionic#32-bit-abi-bugs
            # https://code.google.com/p/android/issues/detail?id=64613
            #
            # If this breaks your code, fix it! It's been 20+ years!
            return ['-D_FILE_OFFSET_BITS=64']
            # We don't enable -D_LARGEFILE64_SOURCE since that enables
            # transitionary features and must be enabled by programs that use
            # those features explicitly.
        return []

    def get_library_dirs(self, env ,
                         elf_class  = None)  :
        return []

    def get_return_value(self,
                         fname ,
                         rtype ,
                         prefix ,
                         env ,
                         extra_args ,
                         dependencies )   :
        raise EnvironmentException('{} does not support get_return_value'.format((self.id)))

    def find_framework(self,
                       name ,
                       env ,
                       extra_dirs ,
                       allow_system  = True)  :
        raise EnvironmentException('{} does not support find_framework'.format((self.id)))

    def find_framework_paths(self, env )  :
        raise EnvironmentException('{} does not support find_framework_paths'.format((self.id)))

    def attribute_check_func(self, name )  :
        raise EnvironmentException('{} does not support attribute checks'.format((self.id)))

    def get_pch_suffix(self)  :
        raise EnvironmentException('{} does not support pre compiled headers'.format((self.id)))

    def get_pch_name(self, name )  :
        raise EnvironmentException('{} does not support pre compiled headers'.format((self.id)))

    def get_pch_use_args(self, pch_dir , header )  :
        raise EnvironmentException('{} does not support pre compiled headers'.format((self.id)))

    def get_has_func_attribute_extra_args(self, name )  :
        raise EnvironmentException('{} does not support function attributes'.format((self.id)))

    def name_string(self)  :
        return ' '.join(self.exelist)

    @abc.abstractmethod
    def sanity_check(self, work_dir , environment )  :
        """Check that this compiler actually works.

        This should provide a simple compile/link test. Something as simple as:
        ```python
        main(): return 0
        ```
        is good enough here.
        """

    def split_shlib_to_parts(self, fname )   :
        return None, fname

    def get_dependency_gen_args(self, outtarget , outfile )  :
        return []

    def get_std_exe_link_args(self)  :
        # TODO: is this a linker property?
        return []

    def get_include_args(self, path , is_system )  :
        return []

    def depfile_for_object(self, objfile )  :
        return objfile + '.' + self.get_depfile_suffix()

    def get_depfile_suffix(self)  :
        raise EnvironmentException('{} does not implement get_depfile_suffix'.format((self.id)))

    def get_no_stdinc_args(self)  :
        """Arguments to turn off default inclusion of standard libraries."""
        return []

    def get_warn_args(self, level )  :
        return []

    def get_werror_args(self)  :
        return []

    @abc.abstractmethod
    def get_optimization_args(self, optimization_level )  :
        pass

    def get_module_incdir_args(self)   :
        raise EnvironmentException('{} does not implement get_module_incdir_args'.format((self.id)))

    def get_module_outdir_args(self, path )  :
        raise EnvironmentException('{} does not implement get_module_outdir_args'.format((self.id)))

    def module_name_to_filename(self, module_name )  :
        raise EnvironmentException('{} does not implement module_name_to_filename'.format((self.id)))

    def get_compiler_check_args(self, mode )  :
        """Arguments to pass the compiler and/or linker for checks.

        The default implementation turns off optimizations.

        Examples of things that go here:
          - extra arguments for error checking
          - Arguments required to make the compiler exit with a non-zero status
            when something is wrong.
        """
        return self.get_no_optimization_args()

    def get_no_optimization_args(self)  :
        """Arguments to the compiler to turn off all optimizations."""
        return []

    def build_wrapper_args(self, env ,
                           extra_args     ,
                           dependencies ,
                           mode  = CompileCheckMode.COMPILE)  :
        """Arguments to pass the build_wrapper helper.

        This generally needs to be set on a per-language baises. It provides
        a hook for languages to handle dependencies and extra args. The base
        implementation handles the most common cases, namely adding the
        check_arguments, unwrapping dependencies, and appending extra args.
        """
        if callable(extra_args):
            extra_args = extra_args(mode)
        if extra_args is None:
            extra_args = []
        if dependencies is None:
            dependencies = []

        # Collect compiler arguments
        args = self.compiler_args(self.get_compiler_check_args(mode))
        for d in dependencies:
            # Add compile flags needed by dependencies
            args += d.get_compile_args()
            if mode is CompileCheckMode.LINK:
                # Add link flags needed to find dependencies
                args += d.get_link_args()

        if mode is CompileCheckMode.COMPILE:
            # Add DFLAGS from the env
            args += env.coredata.get_external_args(self.for_machine, self.language)
        elif mode is CompileCheckMode.LINK:
            # Add LDFLAGS from the env
            args += env.coredata.get_external_link_args(self.for_machine, self.language)
        # extra_args must override all other arguments, so we add them last
        args += extra_args
        return args

    @contextlib.contextmanager
    def _build_wrapper(self, code , env ,
                       extra_args      = None,
                       dependencies  = None,
                       mode  = 'compile', want_output  = False,
                       disable_cache  = False,
                       temp_dir  = None)  :
        """Helper for getting a cacched value when possible.

        This method isn't meant to be called externally, it's mean to be
        wrapped by other methods like compiles() and links().
        """
        args = self.build_wrapper_args(env, extra_args, dependencies, CompileCheckMode(mode))
        if disable_cache or want_output:
            with self.compile(code, extra_args=args, mode=mode, want_output=want_output, temp_dir=env.scratch_dir) as r:
                yield r
        else:
            with self.cached_compile(code, env.coredata, extra_args=args, mode=mode, temp_dir=env.scratch_dir) as r:
                yield r

    def compiles(self, code , env , *,
                 extra_args      = None,
                 dependencies  = None,
                 mode  = 'compile',
                 disable_cache  = False)   :
        with self._build_wrapper(code, env, extra_args, dependencies, mode, disable_cache=disable_cache) as p:
            return p.returncode == 0, p.cached

    def links(self, code , env , *,
              compiler  = None,
              extra_args      = None,
              dependencies  = None,
              mode  = 'compile',
              disable_cache  = False)   :
        if compiler:
            with compiler._build_wrapper(code, env, dependencies=dependencies, want_output=True) as r:
                objfile = mesonlib.File.from_absolute_file(r.output_name)
                return self.compiles(objfile, env, extra_args=extra_args,
                                     dependencies=dependencies, mode='link', disable_cache=True)

        return self.compiles(code, env, extra_args=extra_args,
                             dependencies=dependencies, mode='link', disable_cache=disable_cache)

    def get_feature_args(self, kwargs  , build_to_src )  :
        """Used by D for extra language features."""
        # TODO: using a TypeDict here would improve this
        raise EnvironmentException('{} does not implement get_feature_args'.format((self.id)))

    def get_prelink_args(self, prelink_name , obj_list )  :
        raise EnvironmentException('{} does not know how to do prelinking.'.format((self.id)))

    def rsp_file_syntax(self)  :
        """The format of the RSP file that this compiler supports.

        If `self.can_linker_accept_rsp()` returns True, then this needs to
        be implemented
        """
        return self.linker.rsp_file_syntax()

    def get_debug_args(self, is_debug )  :
        """Arguments required for a debug build."""
        return []

    def get_no_warn_args(self)  :
        """Arguments to completely disable warnings."""
        return []


def get_global_options(lang ,
                       comp ,
                       for_machine ,
                       env )  :
    """Retrieve options that apply to all compilers for a given language."""
    description = 'Extra arguments passed to the {}'.format((lang))
    argkey = OptionKey('args', lang=lang, machine=for_machine)
    largkey = argkey.evolve('link_args')
    envkey = argkey.evolve('env_args')

    comp_key = argkey if argkey in env.options else envkey

    comp_options = env.options.get(comp_key, [])
    link_options = env.options.get(largkey, [])

    cargs = coredata.UserArrayOption(
        description + ' compiler',
        comp_options, split_args=True, user_input=True, allow_dups=True)

    largs = coredata.UserArrayOption(
        description + ' linker',
        link_options, split_args=True, user_input=True, allow_dups=True)

    if comp.INVOKES_LINKER and comp_key == envkey:
        # If the compiler acts as a linker driver, and we're using the
        # environment variable flags for both the compiler and linker
        # arguments, then put the compiler flags in the linker flags as well.
        # This is how autotools works, and the env vars freature is for
        # autotools compatibility.
        largs.extend_value(comp_options)

    opts  = {argkey: cargs, largkey: largs}

    return opts
