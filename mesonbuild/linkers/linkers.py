# Copyright 2012-2017 The Meson development team

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
import enum
import os
import typing as T

from .. import mesonlib
from ..mesonlib import EnvironmentException, MesonException
from ..arglist import CompilerArgs

if T.TYPE_CHECKING:
    from ..coredata import KeyedOptionDictType
    from ..environment import Environment
    from ..mesonlib import MachineChoice


@enum.unique
class RSPFileSyntax(enum.Enum):

    """Which RSP file syntax the compiler supports."""

    MSVC = enum.auto()
    GCC = enum.auto()


class StaticLinker:

    #id: str

    def __init__(self, exelist ):
        self.exelist = exelist

    def compiler_args(self, args  = None)  :
        return CompilerArgs(self, args)

    def can_linker_accept_rsp(self)  :
        """
        Determines whether the linker can accept arguments using the @rsp syntax.
        """
        return mesonlib.is_windows()

    def get_base_link_args(self, options )  :
        """Like compilers.get_base_link_args, but for the static linker."""
        return []

    def get_exelist(self)  :
        return self.exelist.copy()

    def get_std_link_args(self, is_thin )  :
        return []

    def get_buildtype_linker_args(self, buildtype )  :
        return []

    def get_output_args(self, target )  :
        return[]

    def get_coverage_link_args(self)  :
        return []

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return ([], set())

    def thread_link_flags(self, env )  :
        return []

    def openmp_flags(self)  :
        return []

    def get_option_link_args(self, options )  :
        return []

    @classmethod
    def unix_args_to_native(cls, args )  :
        return args[:]

    @classmethod
    def native_args_to_unix(cls, args )  :
        return args[:]

    def get_link_debugfile_name(self, targetfile )  :
        return None

    def get_link_debugfile_args(self, targetfile )  :
        # Static libraries do not have PDB files
        return []

    def get_always_args(self)  :
        return []

    def get_linker_always_args(self)  :
        return []

    def rsp_file_syntax(self)  :
        """The format of the RSP file that this compiler supports.

        If `self.can_linker_accept_rsp()` returns True, then this needs to
        be implemented
        """
        assert not self.can_linker_accept_rsp(), '{} linker accepts RSP, but doesn\' provide a supported format, this is a bug'.format((self.id))
        raise EnvironmentException('{} does not implement rsp format, this shouldn\'t be called'.format((self.id)))


class VisualStudioLikeLinker:
    always_args = ['/NOLOGO']

    def __init__(self, machine ):
        self.machine = machine

    def get_always_args(self)  :
        return self.always_args.copy()

    def get_linker_always_args(self)  :
        return self.always_args.copy()

    def get_output_args(self, target )  :
        args = []  # type: T.List[str]
        if self.machine:
            args += ['/MACHINE:' + self.machine]
        args += ['/OUT:' + target]
        return args

    @classmethod
    def unix_args_to_native(cls, args )  :
        from ..compilers import VisualStudioCCompiler
        return VisualStudioCCompiler.unix_args_to_native(args)

    @classmethod
    def native_args_to_unix(cls, args )  :
        from ..compilers import VisualStudioCCompiler
        return VisualStudioCCompiler.native_args_to_unix(args)

    def rsp_file_syntax(self)  :
        return RSPFileSyntax.MSVC


class VisualStudioLinker(VisualStudioLikeLinker, StaticLinker):

    """Microsoft's lib static linker."""

    def __init__(self, exelist , machine ):
        StaticLinker.__init__(self, exelist)
        VisualStudioLikeLinker.__init__(self, machine)


class IntelVisualStudioLinker(VisualStudioLikeLinker, StaticLinker):

    """Intel's xilib static linker."""

    def __init__(self, exelist , machine ):
        StaticLinker.__init__(self, exelist)
        VisualStudioLikeLinker.__init__(self, machine)


class ArLikeLinker(StaticLinker):
    # POSIX requires supporting the dash, GNU permits omitting it
    std_args = ['-csr']

    def can_linker_accept_rsp(self)  :
        # armar / AIX can't accept arguments using the @rsp syntax
        # in fact, only the 'ar' id can
        return False

    def get_std_link_args(self, is_thin )  :
        return self.std_args

    def get_output_args(self, target )  :
        return [target]

    def rsp_file_syntax(self)  :
        return RSPFileSyntax.GCC


class ArLinker(ArLikeLinker):
    id = 'ar'

    def __init__(self, exelist ):
        super().__init__(exelist)
        stdo = mesonlib.Popen_safe(self.exelist + ['-h'])[1]
        # Enable deterministic builds if they are available.
        stdargs = 'csr'
        thinargs = ''
        if '[D]' in stdo:
            stdargs += 'D'
        if '[T]' in stdo:
            thinargs = 'T'
        self.std_args = [stdargs]
        self.std_thin_args = [stdargs + thinargs]
        self.can_rsp = '@<' in stdo

    def can_linker_accept_rsp(self)  :
        return self.can_rsp

    def get_std_link_args(self, is_thin )  :
        # FIXME: osx ld rejects this: "file built for unknown-unsupported file format"
        if is_thin and not mesonlib.is_osx():
            return self.std_thin_args
        else:
            return self.std_args


class ArmarLinker(ArLikeLinker):
    id = 'armar'


class DLinker(StaticLinker):
    def __init__(self, exelist , arch , *, rsp_syntax  = RSPFileSyntax.GCC):
        super().__init__(exelist)
        self.id = exelist[0]
        self.arch = arch
        self.__rsp_syntax = rsp_syntax

    def get_std_link_args(self, is_thin )  :
        return ['-lib']

    def get_output_args(self, target )  :
        return ['-of=' + target]

    def get_linker_always_args(self)  :
        if mesonlib.is_windows():
            if self.arch == 'x86_64':
                return ['-m64']
            elif self.arch == 'x86_mscoff' and self.id == 'dmd':
                return ['-m32mscoff']
            return ['-m32']
        return []

    def rsp_file_syntax(self)  :
        return self.__rsp_syntax


class CcrxLinker(StaticLinker):

    def __init__(self, exelist ):
        super().__init__(exelist)
        self.id = 'rlink'

    def can_linker_accept_rsp(self)  :
        return False

    def get_output_args(self, target )  :
        return ['-output={}'.format((target))]

    def get_linker_always_args(self)  :
        return ['-nologo', '-form=library']


class Xc16Linker(StaticLinker):

    def __init__(self, exelist ):
        super().__init__(exelist)
        self.id = 'xc16-ar'

    def can_linker_accept_rsp(self)  :
        return False

    def get_output_args(self, target )  :
        return ['{}'.format((target))]

    def get_linker_always_args(self)  :
        return ['rcs']

class CompCertLinker(StaticLinker):

    def __init__(self, exelist ):
        super().__init__(exelist)
        self.id = 'ccomp'

    def can_linker_accept_rsp(self)  :
        return False

    def get_output_args(self, target )  :
        return ['-o{}'.format((target))]


class TILinker(StaticLinker):

    def __init__(self, exelist ):
        super().__init__(exelist)
        self.id = 'ti-ar'

    def can_linker_accept_rsp(self)  :
        return False

    def get_output_args(self, target )  :
        return ['{}'.format((target))]

    def get_linker_always_args(self)  :
        return ['-r']


class C2000Linker(TILinker):
    # Required for backwards compat with projects created before ti-cgt support existed
    id = 'ar2000'


class AIXArLinker(ArLikeLinker):
    id = 'aixar'
    std_args = ['-csr', '-Xany']


def prepare_rpaths(raw_rpaths  , build_dir , from_dir )  :
    # The rpaths we write must be relative if they point to the build dir,
    # because otherwise they have different length depending on the build
    # directory. This breaks reproducible builds.
    internal_format_rpaths = [evaluate_rpath(p, build_dir, from_dir) for p in raw_rpaths]
    ordered_rpaths = order_rpaths(internal_format_rpaths)
    return ordered_rpaths


def order_rpaths(rpath_list )  :
    # We want rpaths that point inside our build dir to always override
    # those pointing to other places in the file system. This is so built
    # binaries prefer our libraries to the ones that may lie somewhere
    # in the file system, such as /lib/x86_64-linux-gnu.
    #
    # The correct thing to do here would be C++'s std::stable_partition.
    # Python standard library does not have it, so replicate it with
    # sort, which is guaranteed to be stable.
    return sorted(rpath_list, key=os.path.isabs)


def evaluate_rpath(p , build_dir , from_dir )  :
    if p == from_dir:
        return '' # relpath errors out in this case
    elif os.path.isabs(p):
        return p # These can be outside of build dir.
    else:
        return os.path.relpath(os.path.join(build_dir, p), os.path.join(build_dir, from_dir))

class DynamicLinker(metaclass=abc.ABCMeta):

    """Base class for dynamic linkers."""

    _BUILDTYPE_ARGS = {
        'plain': [],
        'debug': [],
        'debugoptimized': [],
        'release': [],
        'minsize': [],
        'custom': [],
    }  # type: T.Dict[str, T.List[str]]

    @abc.abstractproperty
    def id(self)  :
        pass

    def _apply_prefix(self, arg  )  :
        args = [arg] if isinstance(arg, str) else arg
        if self.prefix_arg is None:
            return args
        elif isinstance(self.prefix_arg, str):
            return [self.prefix_arg + arg for arg in args]
        ret = []
        for arg in args:
            ret += self.prefix_arg + [arg]
        return ret

    def __init__(self, exelist ,
                 for_machine , prefix_arg  ,
                 always_args , *, version  = 'unknown version'):
        self.exelist = exelist
        self.for_machine = for_machine
        self.version = version
        self.prefix_arg = prefix_arg
        self.always_args = always_args
        self.machine = None  # type: T.Optional[str]

    def __repr__(self)  :
        return '<{}: v{} `{}`>'.format(type(self).__name__, self.version, ' '.join(self.exelist))

    def get_id(self)  :
        return self.id

    def get_version_string(self)  :
        return '({} {})'.format((self.id), (self.version))

    def get_exelist(self)  :
        return self.exelist.copy()

    def get_accepts_rsp(self)  :
        # rsp files are only used when building on Windows because we want to
        # avoid issues with quoting and max argument length
        return mesonlib.is_windows()

    def rsp_file_syntax(self)  :
        """The format of the RSP file that this compiler supports.

        If `self.can_linker_accept_rsp()` returns True, then this needs to
        be implemented
        """
        return RSPFileSyntax.GCC

    def get_always_args(self)  :
        return self.always_args.copy()

    def get_lib_prefix(self)  :
        return ''

    # XXX: is use_ldflags a compiler or a linker attribute?

    def get_option_args(self, options )  :
        return []

    def has_multi_arguments(self, args , env )   :
        raise EnvironmentException('Language {} does not support has_multi_link_arguments.'.format((self.id)))

    def get_debugfile_name(self, targetfile )  :
        '''Name of debug file written out (see below)'''
        return None

    def get_debugfile_args(self, targetfile )  :
        """Some compilers (MSVC) write debug into a separate file.

        This method takes the target object path and returns a list of
        commands to append to the linker invocation to control where that
        file is written.
        """
        return []

    def get_std_shared_lib_args(self)  :
        return []

    def get_std_shared_module_args(self, options )  :
        return self.get_std_shared_lib_args()

    def get_pie_args(self)  :
        # TODO: this really needs to take a boolean and return the args to
        # disable pie, otherwise it only acts to enable pie if pie *isn't* the
        # default.
        raise EnvironmentException('Linker {} does not support position-independent executable'.format((self.id)))

    def get_lto_args(self)  :
        return []

    def sanitizer_args(self, value )  :
        return []

    def get_buildtype_args(self, buildtype )  :
        # We can override these in children by just overriding the
        # _BUILDTYPE_ARGS value.
        return self._BUILDTYPE_ARGS[buildtype]

    def get_asneeded_args(self)  :
        return []

    def get_link_whole_for(self, args )  :
        raise EnvironmentException(
            'Linker {} does not support link_whole'.format((self.id)))

    def get_allow_undefined_args(self)  :
        raise EnvironmentException(
            'Linker {} does not support allow undefined'.format((self.id)))

    @abc.abstractmethod
    def get_output_args(self, outname )  :
        pass

    def get_coverage_args(self)  :
        raise EnvironmentException("Linker {} doesn't implement coverage data generation.".format((self.id)))

    @abc.abstractmethod
    def get_search_args(self, dirname )  :
        pass

    def export_dynamic_args(self, env )  :
        return []

    def import_library_args(self, implibname )  :
        """The name of the outputted import library.

        This implementation is used only on Windows by compilers that use GNU ld
        """
        return []

    def thread_flags(self, env )  :
        return []

    def no_undefined_args(self)  :
        """Arguments to error if there are any undefined symbols at link time.

        This is the inverse of get_allow_undefined_args().

        TODO: A future cleanup might merge this and
              get_allow_undefined_args() into a single method taking a
              boolean
        """
        return []

    def fatal_warnings(self)  :
        """Arguments to make all warnings errors."""
        return []

    def headerpad_args(self)  :
        # Only used by the Apple linker
        return []

    def get_gui_app_args(self, value )  :
        # Only used by VisualStudioLikeLinkers
        return []

    def get_win_subsystem_args(self, value )  :
        # Only used if supported by the dynamic linker and
        # only when targeting Windows
        return []

    def bitcode_args(self)  :
        raise MesonException('This linker does not support bitcode bundles')

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return ([], set())

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        return []


class PosixDynamicLinkerMixin:

    """Mixin class for POSIX-ish linkers.

    This is obviously a pretty small subset of the linker interface, but
    enough dynamic linkers that meson supports are POSIX-like but not
    GNU-like that it makes sense to split this out.
    """

    def get_output_args(self, outname )  :
        return ['-o', outname]

    def get_std_shared_lib_args(self)  :
        return ['-shared']

    def get_search_args(self, dirname )  :
        return ['-L' + dirname]


class GnuLikeDynamicLinkerMixin:

    """Mixin class for dynamic linkers that provides gnu-like interface.

    This acts as a base for the GNU linkers (bfd and gold), LLVM's lld, and
    other linkers like GNU-ld.
    """

    if T.TYPE_CHECKING:
        for_machine = MachineChoice.HOST
        def _apply_prefix(self, arg  )  : ...

    _BUILDTYPE_ARGS = {
        'plain': [],
        'debug': [],
        'debugoptimized': [],
        'release': ['-O1'],
        'minsize': [],
        'custom': [],
    }  # type: T.Dict[str, T.List[str]]

    def get_buildtype_args(self, buildtype )  :
        # We can override these in children by just overriding the
        # _BUILDTYPE_ARGS value.
        return mesonlib.listify([self._apply_prefix(a) for a in self._BUILDTYPE_ARGS[buildtype]])

    def get_pie_args(self)  :
        return ['-pie']

    def get_asneeded_args(self)  :
        return self._apply_prefix('--as-needed')

    def get_link_whole_for(self, args )  :
        if not args:
            return args
        return self._apply_prefix('--whole-archive') + args + self._apply_prefix('--no-whole-archive')

    def get_allow_undefined_args(self)  :
        return self._apply_prefix('--allow-shlib-undefined')

    def get_lto_args(self)  :
        return ['-flto']

    def sanitizer_args(self, value )  :
        if value == 'none':
            return []
        return ['-fsanitize=' + value]

    def get_coverage_args(self)  :
        return ['--coverage']

    def export_dynamic_args(self, env )  :
        m = env.machines[self.for_machine]
        if m.is_windows() or m.is_cygwin():
            return self._apply_prefix('--export-all-symbols')
        return self._apply_prefix('-export-dynamic')

    def import_library_args(self, implibname )  :
        return self._apply_prefix('--out-implib=' + implibname)

    def thread_flags(self, env )  :
        if env.machines[self.for_machine].is_haiku():
            return []
        return ['-pthread']

    def no_undefined_args(self)  :
        return self._apply_prefix('--no-undefined')

    def fatal_warnings(self)  :
        return self._apply_prefix('--fatal-warnings')

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        m = env.machines[self.for_machine]
        if m.is_windows() or m.is_cygwin():
            # For PE/COFF the soname argument has no effect
            return []
        sostr = '' if soversion is None else '.' + soversion
        return self._apply_prefix('-soname,{}{}.{}{}'.format((prefix), (shlib_name), (suffix), (sostr)))

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        m = env.machines[self.for_machine]
        if m.is_windows() or m.is_cygwin():
            return ([], set())
        if not rpath_paths and not install_rpath and not build_rpath:
            return ([], set())
        args = []
        origin_placeholder = '$ORIGIN'
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        # Need to deduplicate rpaths, as macOS's install_name_tool
        # is *very* allergic to duplicate -delete_rpath arguments
        # when calling depfixer on installation.
        all_paths = mesonlib.OrderedSet([os.path.join(origin_placeholder, p) for p in processed_rpaths])
        rpath_dirs_to_remove = set()
        for p in all_paths:
            rpath_dirs_to_remove.add(p.encode('utf8'))
        # Build_rpath is used as-is (it is usually absolute).
        if build_rpath != '':
            all_paths.add(build_rpath)
            for p in build_rpath.split(':'):
                rpath_dirs_to_remove.add(p.encode('utf8'))

        # TODO: should this actually be "for (dragonfly|open)bsd"?
        if mesonlib.is_dragonflybsd() or mesonlib.is_openbsd():
            # This argument instructs the compiler to record the value of
            # ORIGIN in the .dynamic section of the elf. On Linux this is done
            # by default, but is not on dragonfly/openbsd for some reason. Without this
            # $ORIGIN in the runtime path will be undefined and any binaries
            # linked against local libraries will fail to resolve them.
            args.extend(self._apply_prefix('-z,origin'))

        # In order to avoid relinking for RPATH removal, the binary needs to contain just
        # enough space in the ELF header to hold the final installation RPATH.
        paths = ':'.join(all_paths)
        if len(paths) < len(install_rpath):
            padding = 'X' * (len(install_rpath) - len(paths))
            if not paths:
                paths = padding
            else:
                paths = paths + ':' + padding
        args.extend(self._apply_prefix('-rpath,' + paths))

        # TODO: should this actually be "for solaris/sunos"?
        if mesonlib.is_sunos():
            return (args, rpath_dirs_to_remove)

        # Rpaths to use while linking must be absolute. These are not
        # written to the binary. Needed only with GNU ld:
        # https://sourceware.org/bugzilla/show_bug.cgi?id=16936
        # Not needed on Windows or other platforms that don't use RPATH
        # https://github.com/mesonbuild/meson/issues/1897
        #
        # In addition, this linker option tends to be quite long and some
        # compilers have trouble dealing with it. That's why we will include
        # one option per folder, like this:
        #
        #   -Wl,-rpath-link,/path/to/folder1 -Wl,-rpath,/path/to/folder2 ...
        #
        # ...instead of just one single looooong option, like this:
        #
        #   -Wl,-rpath-link,/path/to/folder1:/path/to/folder2:...
        for p in rpath_paths:
            args.extend(self._apply_prefix('-rpath-link,' + os.path.join(build_dir, p)))

        return (args, rpath_dirs_to_remove)

    def get_win_subsystem_args(self, value )  :
        if 'windows' in value:
            args = ['--subsystem,windows']
        elif 'console' in value:
            args = ['--subsystem,console']
        else:
            raise MesonException('Only "windows" and "console" are supported for win_subsystem with MinGW, not "{}".'.format((value)))
        if ',' in value:
            args[-1] = args[-1] + ':' + value.split(',')[1]

        return self._apply_prefix(args)


class AppleDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """Apple's ld implementation."""

    id = 'ld64'

    def get_asneeded_args(self)  :
        return self._apply_prefix('-dead_strip_dylibs')

    def get_allow_undefined_args(self)  :
        return self._apply_prefix('-undefined,dynamic_lookup')

    def get_std_shared_module_args(self, options )  :
        return ['-bundle'] + self._apply_prefix('-undefined,dynamic_lookup')

    def get_pie_args(self)  :
        return []

    def get_link_whole_for(self, args )  :
        result = []  # type: T.List[str]
        for a in args:
            result.extend(self._apply_prefix('-force_load'))
            result.append(a)
        return result

    def get_coverage_args(self)  :
        return ['--coverage']

    def sanitizer_args(self, value )  :
        if value == 'none':
            return []
        return ['-fsanitize=' + value]

    def no_undefined_args(self)  :
        return self._apply_prefix('-undefined,error')

    def headerpad_args(self)  :
        return self._apply_prefix('-headerpad_max_install_names')

    def bitcode_args(self)  :
        return self._apply_prefix('-bitcode_bundle')

    def fatal_warnings(self)  :
        return self._apply_prefix('-fatal_warnings')

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        install_name = ['@rpath/', prefix, shlib_name]
        if soversion is not None:
            install_name.append('.' + soversion)
        install_name.append('.dylib')
        args = ['-install_name', ''.join(install_name)]
        if darwin_versions:
            args.extend(['-compatibility_version', darwin_versions[0],
                         '-current_version', darwin_versions[1]])
        return args

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        if not rpath_paths and not install_rpath and not build_rpath:
            return ([], set())
        args = []
        # @loader_path is the equivalent of $ORIGIN on macOS
        # https://stackoverflow.com/q/26280738
        origin_placeholder = '@loader_path'
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        all_paths = mesonlib.OrderedSet([os.path.join(origin_placeholder, p) for p in processed_rpaths])
        if build_rpath != '':
            all_paths.add(build_rpath)
        for rp in all_paths:
            args.extend(self._apply_prefix('-rpath,' + rp))

        return (args, set())


class GnuDynamicLinker(GnuLikeDynamicLinkerMixin, PosixDynamicLinkerMixin, DynamicLinker):

    """Representation of GNU ld.bfd and ld.gold."""

    def get_accepts_rsp(self)  :
        return True


class GnuGoldDynamicLinker(GnuDynamicLinker):

    id = 'ld.gold'


class GnuBFDDynamicLinker(GnuDynamicLinker):

    id = 'ld.bfd'


class LLVMDynamicLinker(GnuLikeDynamicLinkerMixin, PosixDynamicLinkerMixin, DynamicLinker):

    """Representation of LLVM's ld.lld linker.

    This is only the gnu-like linker, not the apple like or link.exe like
    linkers.
    """

    id = 'ld.lld'

    def __init__(self, exelist ,
                 for_machine , prefix_arg  ,
                 always_args , *, version  = 'unknown version'):
        super().__init__(exelist, for_machine, prefix_arg, always_args, version=version)

        # Some targets don't seem to support this argument (windows, wasm, ...)
        _, _, e = mesonlib.Popen_safe(self.exelist + self._apply_prefix('--allow-shlib-undefined'))
        self.has_allow_shlib_undefined = 'unknown argument: --allow-shlib-undefined' not in e

    def get_allow_undefined_args(self)  :
        if self.has_allow_shlib_undefined:
            return self._apply_prefix('--allow-shlib-undefined')
        return []


class WASMDynamicLinker(GnuLikeDynamicLinkerMixin, PosixDynamicLinkerMixin, DynamicLinker):

    """Emscripten's wasm-ld."""

    id = 'ld.wasm'

    def get_allow_undefined_args(self)  :
        return ['-s', 'ERROR_ON_UNDEFINED_SYMBOLS=0']

    def no_undefined_args(self)  :
        return ['-s', 'ERROR_ON_UNDEFINED_SYMBOLS=1']

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        raise MesonException('{} does not support shared libraries.'.format((self.id)))

    def get_asneeded_args(self)  :
        return []

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return ([], set())


class CcrxDynamicLinker(DynamicLinker):

    """Linker for Renesis CCrx compiler."""

    id = 'rlink'

    def __init__(self, for_machine ,
                 *, version  = 'unknown version'):
        super().__init__(['rlink.exe'], for_machine, '', [],
                         version=version)

    def get_accepts_rsp(self)  :
        return False

    def get_lib_prefix(self)  :
        return '-lib='

    def get_std_shared_lib_args(self)  :
        return []

    def get_output_args(self, outputname )  :
        return ['-output={}'.format((outputname))]

    def get_search_args(self, dirname )  :
        raise OSError('rlink.exe does not have a search dir argument')

    def get_allow_undefined_args(self)  :
        return []

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        return []


class Xc16DynamicLinker(DynamicLinker):

    """Linker for Microchip XC16 compiler."""

    id = 'xc16-gcc'

    def __init__(self, for_machine ,
                 *, version  = 'unknown version'):
        super().__init__(['xc16-gcc'], for_machine, '', [],
                         version=version)

    def get_link_whole_for(self, args )  :
        if not args:
            return args
        return self._apply_prefix('--start-group') + args + self._apply_prefix('--end-group')

    def get_accepts_rsp(self)  :
        return False

    def get_lib_prefix(self)  :
        return ''

    def get_std_shared_lib_args(self)  :
        return []

    def get_output_args(self, outputname )  :
        return ['-o{}'.format((outputname))]

    def get_search_args(self, dirname )  :
        raise OSError('xc16-gcc does not have a search dir argument')

    def get_allow_undefined_args(self)  :
        return []

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        return []

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return ([], set())

class CompCertDynamicLinker(DynamicLinker):

    """Linker for CompCert C compiler."""

    id = 'ccomp'

    def __init__(self, for_machine ,
                 *, version  = 'unknown version'):
        super().__init__(['ccomp'], for_machine, '', [],
                         version=version)

    def get_link_whole_for(self, args )  :
        if not args:
            return args
        return self._apply_prefix('-Wl,--whole-archive') + args + self._apply_prefix('-Wl,--no-whole-archive')

    def get_accepts_rsp(self)  :
        return False

    def get_lib_prefix(self)  :
        return ''

    def get_std_shared_lib_args(self)  :
        return []

    def get_output_args(self, outputname )  :
        return ['-o{}'.format((outputname))]

    def get_search_args(self, dirname )  :
        return ['-L{}'.format((dirname))]

    def get_allow_undefined_args(self)  :
        return []

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        raise MesonException('{} does not support shared libraries.'.format((self.id)))

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        return ([], set())

class TIDynamicLinker(DynamicLinker):

    """Linker for Texas Instruments compiler family."""

    id = 'ti'

    def __init__(self, exelist , for_machine ,
                 *, version  = 'unknown version'):
        super().__init__(exelist, for_machine, '', [],
                         version=version)

    def get_link_whole_for(self, args )  :
        if not args:
            return args
        return self._apply_prefix('--start-group') + args + self._apply_prefix('--end-group')

    def get_accepts_rsp(self)  :
        return False

    def get_lib_prefix(self)  :
        return '-l='

    def get_std_shared_lib_args(self)  :
        return []

    def get_output_args(self, outputname )  :
        return ['-z', '--output_file={}'.format((outputname))]

    def get_search_args(self, dirname )  :
        raise OSError('TI compilers do not have a search dir argument')

    def get_allow_undefined_args(self)  :
        return []

    def get_always_args(self)  :
        return []


class C2000DynamicLinker(TIDynamicLinker):
    # Required for backwards compat with projects created before ti-cgt support existed
    id = 'cl2000'


class ArmDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """Linker for the ARM compiler."""

    id = 'armlink'

    def __init__(self, for_machine ,
                 *, version  = 'unknown version'):
        super().__init__(['armlink'], for_machine, '', [],
                         version=version)

    def get_accepts_rsp(self)  :
        return False

    def get_std_shared_lib_args(self)  :
        raise MesonException('The Arm Linkers do not support shared libraries')

    def get_allow_undefined_args(self)  :
        return []


class ArmClangDynamicLinker(ArmDynamicLinker):

    """Linker used with ARM's clang fork.

    The interface is similar enough to the old ARM ld that it inherits and
    extends a few things as needed.
    """

    def export_dynamic_args(self, env )  :
        return ['--export_dynamic']

    def import_library_args(self, implibname )  :
        return ['--symdefs=' + implibname]

class QualcommLLVMDynamicLinker(LLVMDynamicLinker):

    """ARM Linker from Snapdragon LLVM ARM Compiler."""

    id = 'ld.qcld'


class NAGDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """NAG Fortran linker, ld via gcc indirection.

    Using nagfor -Wl,foo passes option foo to a backend gcc invocation.
    (This linking gathers the correct objects needed from the nagfor runtime
    system.)
    To pass gcc -Wl,foo options (i.e., to ld) one must apply indirection
    again: nagfor -Wl,-Wl,,foo
    """

    id = 'nag'

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        if not rpath_paths and not install_rpath and not build_rpath:
            return ([], set())
        args = []
        origin_placeholder = '$ORIGIN'
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        all_paths = mesonlib.OrderedSet([os.path.join(origin_placeholder, p) for p in processed_rpaths])
        if build_rpath != '':
            all_paths.add(build_rpath)
        for rp in all_paths:
            args.extend(self._apply_prefix('-Wl,-Wl,,-rpath,,' + rp))

        return (args, set())

    def get_allow_undefined_args(self)  :
        return []

    def get_std_shared_lib_args(self)  :
        from ..compilers import NAGFortranCompiler
        return NAGFortranCompiler.get_nagfor_quiet(self.version) + ['-Wl,-shared']


class PGIDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """PGI linker."""

    id = 'pgi'

    def get_allow_undefined_args(self)  :
        return []

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        return []

    def get_std_shared_lib_args(self)  :
        # PGI -shared is Linux only.
        if mesonlib.is_windows():
            return ['-Bdynamic', '-Mmakedll']
        elif mesonlib.is_linux():
            return ['-shared']
        return []

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        if not env.machines[self.for_machine].is_windows():
            return (['-R' + os.path.join(build_dir, p) for p in rpath_paths], set())
        return ([], set())

NvidiaHPC_DynamicLinker = PGIDynamicLinker


class PGIStaticLinker(StaticLinker):
    def __init__(self, exelist ):
        super().__init__(exelist)
        self.id = 'ar'
        self.std_args = ['-r']

    def get_std_link_args(self, is_thin )  :
        return self.std_args

    def get_output_args(self, target )  :
        return [target]

NvidiaHPC_StaticLinker = PGIStaticLinker


class VisualStudioLikeLinkerMixin:

    """Mixin class for for dynamic linkers that act like Microsoft's link.exe."""

    if T.TYPE_CHECKING:
        for_machine = MachineChoice.HOST
        def _apply_prefix(self, arg  )  : ...

    _BUILDTYPE_ARGS = {
        'plain': [],
        'debug': [],
        'debugoptimized': [],
        # The otherwise implicit REF and ICF linker optimisations are disabled by
        # /DEBUG. REF implies ICF.
        'release': ['/OPT:REF'],
        'minsize': ['/INCREMENTAL:NO', '/OPT:REF'],
        'custom': [],
    }  # type: T.Dict[str, T.List[str]]

    def __init__(self, exelist , for_machine ,
                 prefix_arg  , always_args , *,
                 version  = 'unknown version', direct  = True, machine  = 'x86'):
        # There's no way I can find to make mypy understand what's going on here
        super().__init__(exelist, for_machine, prefix_arg, always_args, version=version)  # type: ignore
        self.machine = machine
        self.direct = direct

    def get_buildtype_args(self, buildtype )  :
        return mesonlib.listify([self._apply_prefix(a) for a in self._BUILDTYPE_ARGS[buildtype]])

    def invoked_by_compiler(self)  :
        return not self.direct

    def get_output_args(self, outputname )  :
        return self._apply_prefix(['/MACHINE:' + self.machine, '/OUT:' + outputname])

    def get_always_args(self)  :
        parent = super().get_always_args() # type: ignore
        return self._apply_prefix('/nologo') + T.cast('T.List[str]', parent)

    def get_search_args(self, dirname )  :
        return self._apply_prefix('/LIBPATH:' + dirname)

    def get_std_shared_lib_args(self)  :
        return self._apply_prefix('/DLL')

    def get_debugfile_name(self, targetfile )  :
        basename = targetfile.rsplit('.', maxsplit=1)[0]
        return basename + '.pdb'

    def get_debugfile_args(self, targetfile )  :
        return self._apply_prefix(['/DEBUG', '/PDB:' + self.get_debugfile_name(targetfile)])

    def get_link_whole_for(self, args )  :
        # Only since VS2015
        args = mesonlib.listify(args)
        l = []  # T.List[str]
        for a in args:
            l.extend(self._apply_prefix('/WHOLEARCHIVE:' + a))
        return l

    def get_allow_undefined_args(self)  :
        return []

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        return []

    def import_library_args(self, implibname )  :
        """The command to generate the import library."""
        return self._apply_prefix(['/IMPLIB:' + implibname])

    def rsp_file_syntax(self)  :
        return RSPFileSyntax.MSVC


class MSVCDynamicLinker(VisualStudioLikeLinkerMixin, DynamicLinker):

    """Microsoft's Link.exe."""

    id = 'link'

    def __init__(self, for_machine , always_args , *,
                 exelist  = None,
                 prefix   = '',
                 machine  = 'x86', version  = 'unknown version',
                 direct  = True):
        super().__init__(exelist or ['link.exe'], for_machine,
                         prefix, always_args, machine=machine, version=version, direct=direct)

    def get_always_args(self)  :
        return self._apply_prefix(['/nologo', '/release']) + super().get_always_args()

    def get_gui_app_args(self, value )  :
        return self.get_win_subsystem_args("windows" if value else "console")

    def get_win_subsystem_args(self, value )  :
        return self._apply_prefix(['/SUBSYSTEM:{}'.format((value.upper()))])


class ClangClDynamicLinker(VisualStudioLikeLinkerMixin, DynamicLinker):

    """Clang's lld-link.exe."""

    id = 'lld-link'

    def __init__(self, for_machine , always_args , *,
                 exelist  = None,
                 prefix   = '',
                 machine  = 'x86', version  = 'unknown version',
                 direct  = True):
        super().__init__(exelist or ['lld-link.exe'], for_machine,
                         prefix, always_args, machine=machine, version=version, direct=direct)

    def get_output_args(self, outputname )  :
        # If we're being driven indirectly by clang just skip /MACHINE
        # as clang's target triple will handle the machine selection
        if self.machine is None:
            return self._apply_prefix(["/OUT:{}".format((outputname))])

        return super().get_output_args(outputname)

    def get_gui_app_args(self, value )  :
        return self.get_win_subsystem_args("windows" if value else "console")

    def get_win_subsystem_args(self, value )  :
        return self._apply_prefix(['/SUBSYSTEM:{}'.format((value.upper()))])


class XilinkDynamicLinker(VisualStudioLikeLinkerMixin, DynamicLinker):

    """Intel's Xilink.exe."""

    id = 'xilink'

    def __init__(self, for_machine , always_args , *,
                 exelist  = None,
                 prefix   = '',
                 machine  = 'x86', version  = 'unknown version',
                 direct  = True):
        super().__init__(['xilink.exe'], for_machine, '', always_args, version=version)

    def get_gui_app_args(self, value )  :
        return self.get_win_subsystem_args("windows" if value else "console")

    def get_win_subsystem_args(self, value )  :
        return self._apply_prefix(['/SUBSYSTEM:{}'.format((value.upper()))])


class SolarisDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """Sys-V derived linker used on Solaris and OpenSolaris."""

    id = 'ld.solaris'

    def get_link_whole_for(self, args )  :
        if not args:
            return args
        return self._apply_prefix('--whole-archive') + args + self._apply_prefix('--no-whole-archive')

    def get_pie_args(self)  :
        # Available in Solaris 11.2 and later
        pc, stdo, stde = mesonlib.Popen_safe(self.exelist + self._apply_prefix('-zhelp'))
        for line in (stdo + stde).split('\n'):
            if '-z type' in line:
                if 'pie' in line:
                    return ['-z', 'type=pie']
                break
        return []

    def get_asneeded_args(self)  :
        return self._apply_prefix(['-z', 'ignore'])

    def no_undefined_args(self)  :
        return ['-z', 'defs']

    def get_allow_undefined_args(self)  :
        return ['-z', 'nodefs']

    def fatal_warnings(self)  :
        return ['-z', 'fatal-warnings']

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        if not rpath_paths and not install_rpath and not build_rpath:
            return ([], set())
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        all_paths = mesonlib.OrderedSet([os.path.join('$ORIGIN', p) for p in processed_rpaths])
        rpath_dirs_to_remove = set()
        for p in all_paths:
            rpath_dirs_to_remove.add(p.encode('utf8'))
        if build_rpath != '':
            all_paths.add(build_rpath)
            for p in build_rpath.split(':'):
                rpath_dirs_to_remove.add(p.encode('utf8'))

        # In order to avoid relinking for RPATH removal, the binary needs to contain just
        # enough space in the ELF header to hold the final installation RPATH.
        paths = ':'.join(all_paths)
        if len(paths) < len(install_rpath):
            padding = 'X' * (len(install_rpath) - len(paths))
            if not paths:
                paths = padding
            else:
                paths = paths + ':' + padding
        return (self._apply_prefix('-rpath,{}'.format((paths))), rpath_dirs_to_remove)

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        sostr = '' if soversion is None else '.' + soversion
        return self._apply_prefix('-soname,{}{}.{}{}'.format((prefix), (shlib_name), (suffix), (sostr)))


class AIXDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """Sys-V derived linker used on AIX"""

    id = 'ld.aix'

    def get_always_args(self)  :
        return self._apply_prefix(['-bnoipath', '-bbigtoc']) + super().get_always_args()

    def no_undefined_args(self)  :
        return self._apply_prefix(['-bernotok'])

    def get_allow_undefined_args(self)  :
        return self._apply_prefix(['-berok'])

    def build_rpath_args(self, env , build_dir , from_dir ,
                         rpath_paths  , build_rpath ,
                         install_rpath )   :
        all_paths = mesonlib.OrderedSet() # type: mesonlib.OrderedSet[str]
        # install_rpath first, followed by other paths, and the system path last
        if install_rpath != '':
            all_paths.add(install_rpath)
        if build_rpath != '':
            all_paths.add(build_rpath)
        for p in rpath_paths:
            all_paths.add(os.path.join(build_dir, p))
        # We should consider allowing the $LIBPATH environment variable
        # to override sys_path.
        sys_path = env.get_compiler_system_dirs(self.for_machine)
        if len(sys_path) == 0:
            # get_compiler_system_dirs doesn't support our compiler.
            # Use the default system library path
            all_paths.update(['/usr/lib', '/lib'])
        else:
            # Include the compiler's default library paths, but filter out paths that don't exist
            for p in sys_path:
                if os.path.isdir(p):
                    all_paths.add(p)
        return (self._apply_prefix('-blibpath:' + ':'.join(all_paths)), set())

    def thread_flags(self, env )  :
        return ['-pthread']


class OptlinkDynamicLinker(VisualStudioLikeLinkerMixin, DynamicLinker):

    """Digital Mars dynamic linker for windows."""

    id = 'optlink'

    def __init__(self, exelist , for_machine ,
                 *, version  = 'unknown version'):
        # Use optlink instead of link so we don't interfer with other link.exe
        # implementations.
        super().__init__(exelist, for_machine, '', [], version=version)

    def get_allow_undefined_args(self)  :
        return []

    def get_debugfile_args(self, targetfile )  :
        # Optlink does not generate pdb files.
        return []

    def get_always_args(self)  :
        return []


class CudaLinker(PosixDynamicLinkerMixin, DynamicLinker):
    """Cuda linker (nvlink)"""

    id = 'nvlink'

    @staticmethod
    def parse_version()  :
        version_cmd = ['nvlink', '--version']
        try:
            _, out, _ = mesonlib.Popen_safe(version_cmd)
        except OSError:
            return 'unknown version'
        # Output example:
        # nvlink: NVIDIA (R) Cuda linker
        # Copyright (c) 2005-2018 NVIDIA Corporation
        # Built on Sun_Sep_30_21:09:22_CDT_2018
        # Cuda compilation tools, release 10.0, V10.0.166
        # we need the most verbose version output. Luckily starting with V
        return out.strip().split('V')[-1]

    def get_accepts_rsp(self)  :
        # nvcc does not support response files
        return False

    def get_lib_prefix(self)  :
        # nvcc doesn't recognize Meson's default .a extension for static libraries on
        # Windows and passes it to cl as an object file, resulting in 'warning D9024 :
        # unrecognized source file type 'xxx.a', object file assumed'.
        #
        # nvcc's --library= option doesn't help: it takes the library name without the
        # extension and assumes that the extension on Windows is .lib; prefixing the
        # library with -Xlinker= seems to work.
        #
        # On Linux, we have to use rely on -Xlinker= too, since nvcc/nvlink chokes on
        # versioned shared libraries:
        #
        #   nvcc fatal : Don't know what to do with 'subprojects/foo/libbar.so.0.1.2'
        #
        from ..compilers import CudaCompiler
        return CudaCompiler.LINKER_PREFIX

    def fatal_warnings(self)  :
        return ['--warning-as-error']

    def get_allow_undefined_args(self)  :
        return []

    def get_soname_args(self, env , prefix , shlib_name ,
                        suffix , soversion , darwin_versions  )  :
        return []
