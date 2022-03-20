# Copyright 2015 The Meson development team
# Copyright © 2021 Intel Corporation

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import typing as T
import xml.etree.ElementTree as ET

from . import ModuleReturnValue, ExtensionModule
from .. import build
from .. import coredata
from .. import mlog
from ..dependencies import find_external_dependency, Dependency, ExternalLibrary
from ..mesonlib import MesonException, File, FileOrString, version_compare, Popen_safe
from ..interpreter import extract_required_kwarg
from ..interpreter.type_checking import NoneType
from ..interpreterbase import ContainerTypeInfo, FeatureDeprecated, KwargInfo, noPosargs, FeatureNew, typed_kwargs
from ..programs import ExternalProgram, NonExistingExternalProgram

class QtBaseModule(ExtensionModule):
    _tools_detected = False
    _rcc_supports_depfiles = False
    _moc_supports_depfiles = False

    def __init__(self, interpreter: 'Interpreter', qt_version: int = 5):
        ExtensionModule.__init__(self, interpreter)
        self.qt_version = qt_version
        self.tools: T.Dict[str, ExternalProgram] = {
            'moc': NonExistingExternalProgram('moc'),
            'uic': NonExistingExternalProgram('uic'),
            'rcc': NonExistingExternalProgram('rcc'),
            'lrelease': NonExistingExternalProgram('lrelease'),
        }
        self.methods.update({
            'has_tools': self.has_tools,
            'preprocess': self.preprocess,
            'compile_translations': self.compile_translations,
            'compile_resources': self.compile_resources,
            'compile_ui': self.compile_ui,
            'compile_moc': self.compile_moc,
        })

    def compilers_detect(self, state: 'ModuleState', qt_dep: 'QtDependencyType') -> None:
        """Detect Qt (4 or 5) moc, uic, rcc in the specified bindir or in PATH"""
        # It is important that this list does not change order as the order of
        # the returned ExternalPrograms will change as well
        wanted = '== {}'.format((qt_dep.version))

        def gen_bins() -> T.Generator[T.Tuple[str, str], None, None]:
            for b in self.tools:
                if qt_dep.bindir:
                    yield os.path.join(qt_dep.bindir, b), b
                # prefer the <tool>-qt<version> of the tool to the plain one, as we
                # don't know what the unsuffixed one points to without calling it.
                yield '{}-qt{}'.format((b), (qt_dep.qtver)), b
                yield b, b

        for b, name in gen_bins():
            if self.tools[name].found():
                continue

            if name == 'lrelease':
                arg = ['-version']
            elif version_compare(qt_dep.version, '>= 5'):
                arg = ['--version']
            else:
                arg = ['-v']

            # Ensure that the version of qt and each tool are the same
            def get_version(p: ExternalProgram) -> str:
                _, out, err = Popen_safe(p.get_command() + arg)
                if b.startswith('lrelease') or not qt_dep.version.startswith('4'):
                    care = out
                else:
                    care = err
                return care.split(' ')[-1].replace(')', '').strip()

            p = state.find_program(b, required=False,
                                   version_func=get_version,
                                   wanted=wanted)
            if p.found():
                self.tools[name] = p

    def _detect_tools(self, state: 'ModuleState', method: str, required: bool = True) -> None:
        if self._tools_detected:
            return
        self._tools_detected = True
        mlog.log('Detecting Qt{} tools'.format((self.qt_version)))
        kwargs = {'required': required, 'modules': 'Core', 'method': method}
        # Just pick one to make mypy happy
        qt = T.cast('QtPkgConfigDependency', find_external_dependency('qt{}'.format((self.qt_version)), state.environment, kwargs))
        if qt.found():
            # Get all tools and then make sure that they are the right version
            self.compilers_detect(state, qt)
            if version_compare(qt.version, '>=5.15.0'):
                self._moc_supports_depfiles = True
            else:
                mlog.warning('moc dependencies will not work properly until you move to Qt >= 5.15', fatal=False)
            if version_compare(qt.version, '>=5.14.0'):
                self._rcc_supports_depfiles = True
            else:
                mlog.warning('rcc dependencies will not work properly until you move to Qt >= 5.14:',
                             mlog.bold('https://bugreports.qt.io/browse/QTBUG-45460'), fatal=False)
        else:
            suffix = '-qt{}'.format((self.qt_version))
            self.tools['moc'] = NonExistingExternalProgram(name='moc' + suffix)
            self.tools['uic'] = NonExistingExternalProgram(name='uic' + suffix)
            self.tools['rcc'] = NonExistingExternalProgram(name='rcc' + suffix)
            self.tools['lrelease'] = NonExistingExternalProgram(name='lrelease' + suffix)

    @staticmethod
    def _qrc_nodes(state: 'ModuleState', rcc_file: 'FileOrString') -> T.Tuple[str, T.List[str]]:
        abspath: str
        if isinstance(rcc_file, str):
            abspath = os.path.join(state.environment.source_dir, state.subdir, rcc_file)
            rcc_dirname = os.path.dirname(abspath)
        else:
            abspath = rcc_file.absolute_path(state.environment.source_dir, state.environment.build_dir)
            rcc_dirname = os.path.dirname(abspath)

        # FIXME: what error are we actually trying to check here?
        try:
            tree = ET.parse(abspath)
            root = tree.getroot()
            result: T.List[str] = []
            for child in root[0]:
                if child.tag != 'file':
                    mlog.warning("malformed rcc file: ", os.path.join(state.subdir, str(rcc_file)))
                    break
                else:
                    result.append(child.text)

            return rcc_dirname, result
        except Exception:
            raise MesonException('Unable to parse resource file {}'.format((abspath)))

    def _parse_qrc_deps(self, state: 'ModuleState',
                        rcc_file_: T.Union['FileOrString', build.CustomTarget, build.CustomTargetIndex, build.GeneratedList]) -> T.List[File]:
        result: T.List[File] = []
        inputs: T.Sequence['FileOrString'] = []
        if isinstance(rcc_file_, (str, File)):
            inputs = [rcc_file_]
        else:
            inputs = rcc_file_.get_outputs()

        for rcc_file in inputs:
            rcc_dirname, nodes = self._qrc_nodes(state, rcc_file)
            for resource_path in nodes:
                # We need to guess if the pointed resource is:
                #   a) in build directory -> implies a generated file
                #   b) in source directory
                #   c) somewhere else external dependency file to bundle
                #
                # Also from qrc documentation: relative path are always from qrc file
                # So relative path must always be computed from qrc file !
                if os.path.isabs(resource_path):
                    # a)
                    if resource_path.startswith(os.path.abspath(state.environment.build_dir)):
                        resource_relpath = os.path.relpath(resource_path, state.environment.build_dir)
                        result.append(File(is_built=True, subdir='', fname=resource_relpath))
                    # either b) or c)
                    else:
                        result.append(File(is_built=False, subdir=state.subdir, fname=resource_path))
                else:
                    path_from_rcc = os.path.normpath(os.path.join(rcc_dirname, resource_path))
                    # a)
                    if path_from_rcc.startswith(state.environment.build_dir):
                        result.append(File(is_built=True, subdir=state.subdir, fname=resource_path))
                    # b)
                    else:
                        result.append(File(is_built=False, subdir=state.subdir, fname=path_from_rcc))
        return result

    @FeatureNew('qt.has_tools', '0.54.0')
    @noPosargs
    @typed_kwargs(
        'qt.has_tools',
        KwargInfo('required', (bool, coredata.UserFeatureOption), default=False),
        KwargInfo('method', str, default='auto'),
    )
    def has_tools(self, state: 'ModuleState', args: T.Tuple, kwargs: 'HasToolKwArgs') -> bool:
        method = kwargs.get('method', 'auto')
        # We have to cast here because TypedDicts are invariant, even though
        # ExtractRequiredKwArgs is a subset of HasToolKwArgs, type checkers
        # will insist this is wrong
        disabled, required, feature = extract_required_kwarg(kwargs, state.subproject, default=False)
        if disabled:
            mlog.log('qt.has_tools skipped: feature', mlog.bold(feature), 'disabled')
            return False
        self._detect_tools(state, method, required=False)
        for tool in self.tools.values():
            if not tool.found():
                if required:
                    raise MesonException('Qt tools not found')
                return False
        return True

    @FeatureNew('qt.compile_resources', '0.59.0')
    @noPosargs
    @typed_kwargs(
        'qt.compile_resources',
        KwargInfo('name', (str, NoneType)),
        KwargInfo(
            'sources',
            ContainerTypeInfo(list, (File, str, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList), allow_empty=False),
            listify=True,
            required=True,
        ),
        KwargInfo('extra_args', ContainerTypeInfo(list, str), listify=True, default=[]),
        KwargInfo('method', str, default='auto')
    )
    def compile_resources(self, state: 'ModuleState', args: T.Tuple, kwargs: 'ResourceCompilerKwArgs') -> ModuleReturnValue:
        """Compile Qt resources files.

        Uses CustomTargets to generate .cpp files from .qrc files.
        """
        if any(isinstance(s, (build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)) for s in kwargs['sources']):
            FeatureNew.single_use('qt.compile_resources: custom_target or generator for "sources" keyword argument',
                                  '0.60.0', state.subproject, location=state.current_node)
        out = self._compile_resources_impl(state, kwargs)
        return ModuleReturnValue(out, [out])

    def _compile_resources_impl(self, state: 'ModuleState', kwargs: 'ResourceCompilerKwArgs') -> T.List[build.CustomTarget]:
        # Avoid the FeatureNew when dispatching from preprocess
        self._detect_tools(state, kwargs['method'])
        if not self.tools['rcc'].found():
            err_msg = ("{0} sources specified and couldn't find {1}, "
                       "please check your qt{2} installation")
            raise MesonException(err_msg.format('RCC', 'rcc-qt{}'.format((self.qt_version)), self.qt_version))

        # List of generated CustomTargets
        targets: T.List[build.CustomTarget] = []

        # depfile arguments
        DEPFILE_ARGS: T.List[str] = ['--depfile', '@DEPFILE@'] if self._rcc_supports_depfiles else []

        name = kwargs['name']
        sources: T.List['FileOrString'] = []
        for s in kwargs['sources']:
            if isinstance(s, (str, File)):
                sources.append(s)
            else:
                sources.extend(s.get_outputs())
        extra_args = kwargs['extra_args']

        # If a name was set generate a single .cpp file from all of the qrc
        # files, otherwise generate one .cpp file per qrc file.
        if name:
            qrc_deps: T.List[File] = []
            for s in sources:
                qrc_deps.extend(self._parse_qrc_deps(state, s))

            res_target = build.CustomTarget(
                name,
                state.subdir,
                state.subproject,
                self.tools['rcc'].get_command() + ['-name', name, '-o', '@OUTPUT@'] + extra_args + ['@INPUT@'] + DEPFILE_ARGS,
                sources,
                ['{}.cpp'.format((name))],
                depend_files=qrc_deps,
                depfile='{}.d'.format((name)),
            )
            targets.append(res_target)
        else:
            for rcc_file in sources:
                qrc_deps = self._parse_qrc_deps(state, rcc_file)
                if isinstance(rcc_file, str):
                    basename = os.path.basename(rcc_file)
                else:
                    basename = os.path.basename(rcc_file.fname)
                name = 'qt{}-{}'.format((self.qt_version), (basename.replace(".", "_")))
                res_target = build.CustomTarget(
                    name,
                    state.subdir,
                    state.subproject,
                    self.tools['rcc'].get_command() + ['-name', '@BASENAME@', '-o', '@OUTPUT@'] + extra_args + ['@INPUT@'] + DEPFILE_ARGS,
                    [rcc_file],
                    ['{}.cpp'.format((name))],
                    depend_files=qrc_deps,
                    depfile='{}.d'.format((name)),
                )
                targets.append(res_target)

        return targets

    @FeatureNew('qt.compile_ui', '0.59.0')
    @noPosargs
    @typed_kwargs(
        'qt.compile_ui',
        KwargInfo(
            'sources',
            ContainerTypeInfo(list, (File, str, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList), allow_empty=False),
            listify=True,
            required=True,
        ),
        KwargInfo('extra_args', ContainerTypeInfo(list, str), listify=True, default=[]),
        KwargInfo('method', str, default='auto')
    )
    def compile_ui(self, state: 'ModuleState', args: T.Tuple, kwargs: 'UICompilerKwArgs') -> ModuleReturnValue:
        """Compile UI resources into cpp headers."""
        if any(isinstance(s, (build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)) for s in kwargs['sources']):
            FeatureNew.single_use('qt.compile_ui: custom_target or generator for "sources" keyword argument',
                                  '0.60.0', state.subproject, location=state.current_node)
        out = self._compile_ui_impl(state, kwargs)
        return ModuleReturnValue(out, [out])

    def _compile_ui_impl(self, state: 'ModuleState', kwargs: 'UICompilerKwArgs') -> build.GeneratedList:
        # Avoid the FeatureNew when dispatching from preprocess
        self._detect_tools(state, kwargs['method'])
        if not self.tools['uic'].found():
            err_msg = ("{0} sources specified and couldn't find {1}, "
                       "please check your qt{2} installation")
            raise MesonException(err_msg.format('UIC', 'uic-qt{}'.format((self.qt_version)), self.qt_version))

        # TODO: This generator isn't added to the generator list in the Interpreter
        gen = build.Generator(
            self.tools['uic'],
            kwargs['extra_args'] + ['-o', '@OUTPUT@', '@INPUT@'],
            ['ui_@BASENAME@.h'],
            name='Qt{} ui'.format((self.qt_version)))
        return gen.process_files(kwargs['sources'], state)

    @FeatureNew('qt.compile_moc', '0.59.0')
    @noPosargs
    @typed_kwargs(
        'qt.compile_moc',
        KwargInfo(
            'sources',
            ContainerTypeInfo(list, (File, str, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)),
            listify=True,
            default=[],
        ),
        KwargInfo(
            'headers',
            ContainerTypeInfo(list, (File, str, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)),
            listify=True,
            default=[]
        ),
        KwargInfo('extra_args', ContainerTypeInfo(list, str), listify=True, default=[]),
        KwargInfo('method', str, default='auto'),
        KwargInfo('include_directories', ContainerTypeInfo(list, (build.IncludeDirs, str)), listify=True, default=[]),
        KwargInfo('dependencies', ContainerTypeInfo(list, (Dependency, ExternalLibrary)), listify=True, default=[]),
    )
    def compile_moc(self, state: 'ModuleState', args: T.Tuple, kwargs: 'MocCompilerKwArgs') -> ModuleReturnValue:
        if any(isinstance(s, (build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)) for s in kwargs['headers']):
            FeatureNew.single_use('qt.compile_moc: custom_target or generator for "headers" keyword argument',
                                  '0.60.0', state.subproject, location=state.current_node)
        if any(isinstance(s, (build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)) for s in kwargs['sources']):
            FeatureNew.single_use('qt.compile_moc: custom_target or generator for "sources" keyword argument',
                                  '0.60.0', state.subproject, location=state.current_node)
        out = self._compile_moc_impl(state, kwargs)
        return ModuleReturnValue(out, [out])

    def _compile_moc_impl(self, state: 'ModuleState', kwargs: 'MocCompilerKwArgs') -> T.List[build.GeneratedList]:
        # Avoid the FeatureNew when dispatching from preprocess
        self._detect_tools(state, kwargs['method'])
        if not self.tools['moc'].found():
            err_msg = ("{0} sources specified and couldn't find {1}, "
                       "please check your qt{2} installation")
            raise MesonException(err_msg.format('MOC', 'uic-qt{}'.format((self.qt_version)), self.qt_version))

        if not (kwargs['headers'] or kwargs['sources']):
            raise build.InvalidArguments('At least one of the "headers" or "sources" keyword arguments must be provided and not empty')

        inc = state.get_include_args(include_dirs=kwargs['include_directories'])
        compile_args: T.List[str] = []
        for dep in kwargs['dependencies']:
            compile_args.extend([a for a in dep.get_all_compile_args() if a.startswith(('-I', '-D'))])

        output: T.List[build.GeneratedList] = []

        # depfile arguments (defaults to <output-name>.d)
        DEPFILE_ARGS: T.List[str] = ['--output-dep-file'] if self._moc_supports_depfiles else []

        arguments = kwargs['extra_args'] + DEPFILE_ARGS + inc + compile_args + ['@INPUT@', '-o', '@OUTPUT@']
        if kwargs['headers']:
            moc_gen = build.Generator(
                self.tools['moc'], arguments, ['moc_@BASENAME@.cpp'],
                depfile='moc_@BASENAME@.cpp.d',
                name='Qt{} moc header'.format((self.qt_version)))
            output.append(moc_gen.process_files(kwargs['headers'], state))
        if kwargs['sources']:
            moc_gen = build.Generator(
                self.tools['moc'], arguments, ['@BASENAME@.moc'],
                depfile='@BASENAME.moc.d@',
                name='Qt{} moc source'.format((self.qt_version)))
            output.append(moc_gen.process_files(kwargs['sources'], state))

        return output

    # We can't use typed_pos_args here, the signature is ambiguous
    @typed_kwargs(
        'qt.preprocess',
        KwargInfo('sources', ContainerTypeInfo(list, (File, str)), listify=True, default=[], deprecated='0.59.0'),
        KwargInfo('qresources', ContainerTypeInfo(list, (File, str)), listify=True, default=[]),
        KwargInfo('ui_files', ContainerTypeInfo(list, (File, str, build.CustomTarget)), listify=True, default=[]),
        KwargInfo('moc_sources', ContainerTypeInfo(list, (File, str, build.CustomTarget)), listify=True, default=[]),
        KwargInfo('moc_headers', ContainerTypeInfo(list, (File, str, build.CustomTarget)), listify=True, default=[]),
        KwargInfo('moc_extra_arguments', ContainerTypeInfo(list, str), listify=True, default=[], since='0.44.0'),
        KwargInfo('rcc_extra_arguments', ContainerTypeInfo(list, str), listify=True, default=[], since='0.49.0'),
        KwargInfo('uic_extra_arguments', ContainerTypeInfo(list, str), listify=True, default=[], since='0.49.0'),
        KwargInfo('method', str, default='auto'),
        KwargInfo('include_directories', ContainerTypeInfo(list, (build.IncludeDirs, str)), listify=True, default=[]),
        KwargInfo('dependencies', ContainerTypeInfo(list, (Dependency, ExternalLibrary)), listify=True, default=[]),
    )
    def preprocess(self, state: 'ModuleState', args: T.List[T.Union[str, File]], kwargs: 'PreprocessKwArgs') -> ModuleReturnValue:
        _sources = args[1:]
        if _sources:
            FeatureDeprecated.single_use('qt.preprocess positional sources', '0.59', state.subproject, location=state.current_node)
        # List is invariant, os we have to cast...
        sources = T.cast('T.List[T.Union[str, File, build.GeneratedList, build.CustomTarget]]',
                         _sources + kwargs['sources'])
        for s in sources:
            if not isinstance(s, (str, File)):
                raise build.InvalidArguments('Variadic arguments to qt.preprocess must be Strings or Files')
        method = kwargs['method']

        if kwargs['qresources']:
            # custom output name set? -> one output file, multiple otherwise
            rcc_kwargs: 'ResourceCompilerKwArgs' = {'name': '', 'sources': kwargs['qresources'], 'extra_args': kwargs['rcc_extra_arguments'], 'method': method}
            if args:
                name = args[0]
                if not isinstance(name, str):
                    raise build.InvalidArguments('First argument to qt.preprocess must be a string')
                rcc_kwargs['name'] = name
            sources.extend(self._compile_resources_impl(state, rcc_kwargs))

        if kwargs['ui_files']:
            ui_kwargs: 'UICompilerKwArgs' = {'sources': kwargs['ui_files'], 'extra_args': kwargs['uic_extra_arguments'], 'method': method}
            sources.append(self._compile_ui_impl(state, ui_kwargs))

        if kwargs['moc_headers'] or kwargs['moc_sources']:
            moc_kwargs: 'MocCompilerKwArgs' = {
                'extra_args': kwargs['moc_extra_arguments'],
                'sources': kwargs['moc_sources'],
                'headers': kwargs['moc_headers'],
                'include_directories': kwargs['include_directories'],
                'dependencies': kwargs['dependencies'],
                'method': method,
            }
            sources.extend(self._compile_moc_impl(state, moc_kwargs))

        return ModuleReturnValue(sources, [sources])

    @FeatureNew('qt.compile_translations', '0.44.0')
    @noPosargs
    @typed_kwargs(
        'qt.compile_translations',
        KwargInfo('build_by_default', bool, default=False),
        KwargInfo('install', bool, default=False),
        KwargInfo('install_dir', (str, NoneType)),
        KwargInfo('method', str, default='auto'),
        KwargInfo('qresource', (str, NoneType), since='0.56.0'),
        KwargInfo('rcc_extra_arguments', ContainerTypeInfo(list, str), listify=True, default=[], since='0.56.0'),
        KwargInfo('ts_files', ContainerTypeInfo(list, (str, File, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)), listify=True, default=[]),
    )
    def compile_translations(self, state: 'ModuleState', args: T.Tuple, kwargs: 'CompileTranslationsKwArgs') -> ModuleReturnValue:
        ts_files = kwargs['ts_files']
        if any(isinstance(s, (build.CustomTarget, build.CustomTargetIndex, build.GeneratedList)) for s in ts_files):
            FeatureNew.single_use('qt.compile_translations: custom_target or generator for "ts_files" keyword argument',
                                  '0.60.0', state.subproject, location=state.current_node)
        install_dir = kwargs['install_dir']
        qresource = kwargs['qresource']
        if qresource:
            if ts_files:
                raise MesonException('qt.compile_translations: Cannot specify both ts_files and qresource')
            if os.path.dirname(qresource) != '':
                raise MesonException('qt.compile_translations: qresource file name must not contain a subdirectory.')
            qresource_file = File.from_built_file(state.subdir, qresource)
            infile_abs = os.path.join(state.environment.source_dir, qresource_file.relative_name())
            outfile_abs = os.path.join(state.environment.build_dir, qresource_file.relative_name())
            os.makedirs(os.path.dirname(outfile_abs), exist_ok=True)
            shutil.copy2(infile_abs, outfile_abs)
            self.interpreter.add_build_def_file(infile_abs)

            _, nodes = self._qrc_nodes(state, qresource_file)
            for c in nodes:
                if c.endswith('.qm'):
                    ts_files.append(c.rstrip('.qm') + '.ts')
                else:
                    raise MesonException('qt.compile_translations: qresource can only contain qm files, found {}'.format((c)))
            results = self.preprocess(state, [], {'qresources': qresource_file, 'rcc_extra_arguments': kwargs['rcc_extra_arguments']})
        self._detect_tools(state, kwargs['method'])
        translations: T.List[build.CustomTarget] = []
        for ts in ts_files:
            if not self.tools['lrelease'].found():
                raise MesonException('qt.compile_translations: ' +
                                     self.tools['lrelease'].name + ' not found')
            if qresource:
                # In this case we know that ts_files is always a List[str], as
                # it's generated above and no ts_files are passed in. However,
                # mypy can't figure that out so we use assert to assure it that
                # what we're doing is safe
                assert isinstance(ts, str), 'for mypy'
                outdir = os.path.dirname(os.path.normpath(os.path.join(state.subdir, ts)))
                ts = os.path.basename(ts)
            else:
                outdir = state.subdir
            cmd: T.List[T.Union[ExternalProgram, str]] = [self.tools['lrelease'], '@INPUT@', '-qm', '@OUTPUT@']
            lrelease_target = build.CustomTarget(
                'qt{}-compile-{}'.format((self.qt_version), (ts)),
                outdir,
                state.subproject,
                cmd,
                [ts],
                ['@BASENAME@.qm'],
                install=kwargs['install'],
                install_dir=install_dir,
                install_tag=['i18n'],
                build_by_default=kwargs['build_by_default'],
            )
            translations.append(lrelease_target)
        if qresource:
            return ModuleReturnValue(results.return_value[0], [results.new_objects, translations])
        else:
            return ModuleReturnValue(translations, [translations])
