# Copyright 2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import typing as T

from .. import mesonlib, mlog
from .. import build
from ..compilers import Compiler
from ..interpreter.type_checking import SOURCES_KW, STATIC_LIB_KWS
from ..interpreterbase.decorators import KwargInfo, typed_pos_args, typed_kwargs

from . import ExtensionModule, ModuleInfo

if T.TYPE_CHECKING:
    from . import ModuleState
    from ..interpreter import Interpreter, kwargs as kwtypes

    class CheckKw(kwtypes.StaticLibrary):

        compiler: Compiler
        mmx: T.List[mesonlib.FileOrString]
        sse: T.List[mesonlib.FileOrString]
        sse2: T.List[mesonlib.FileOrString]
        sse3: T.List[mesonlib.FileOrString]
        ssse3: T.List[mesonlib.FileOrString]
        sse41: T.List[mesonlib.FileOrString]
        sse42: T.List[mesonlib.FileOrString]
        avx: T.List[mesonlib.FileOrString]
        avx2: T.List[mesonlib.FileOrString]
        neon: T.List[mesonlib.FileOrString]


# FIXME add Altivec and AVX512.
ISETS = (
    'mmx',
    'sse',
    'sse2',
    'sse3',
    'ssse3',
    'sse41',
    'sse42',
    'avx',
    'avx2',
    'neon',
)


class SimdModule(ExtensionModule):

    INFO = ModuleInfo('SIMD', '0.42.0', unstable=True)

    def __init__(self, interpreter: Interpreter):
        super().__init__(interpreter)
        self.methods.update({
            'check': self.check,
        })

    @typed_pos_args('simd.check', str)
    @typed_kwargs('simd.check',
                  KwargInfo('compiler', Compiler, required=True),
                  *[SOURCES_KW.evolve(name=iset) for iset in ISETS],
                  *[a for a in STATIC_LIB_KWS if a.name != 'sources'],
                  allow_unknown=True) # Because we also accept STATIC_LIB_KWS, but we check them in the interpreter call later on.
    def check(self, state: ModuleState, args: T.Tuple[str], kwargs: CheckKw) -> T.List[T.Union[T.List[build.StaticLibrary], build.ConfigurationData]]:
        if 'sources' in kwargs:
            raise mesonlib.MesonException('SIMD module does not support the "sources" keyword')

        result: T.List[build.StaticLibrary] = []
        prefix = args[0]
        compiler = kwargs['compiler']
        conf = build.ConfigurationData()

        local_keys = set((*ISETS, 'compiler'))
        static_lib_kwargs = T.cast('kwtypes.StaticLibrary', {k: v for k, v in kwargs.items() if k not in local_keys})

        for iset in ISETS:
            sources = kwargs[iset] # type: ignore

            cargs = compiler.get_instruction_set_args(iset)
            if cargs is None:
                mlog.log(f'Compiler supports {iset}:', mlog.red('NO'))
                continue

            if not compiler.has_multi_arguments(cargs, state.environment)[0]:
                mlog.log(f'Compiler supports {iset}:', mlog.red('NO'))
                continue

            mlog.log(f'Compiler supports {iset}:', mlog.green('YES'))
            conf.values['HAVE_' + iset.upper()] = ('1', f'Compiler supports {iset}.')

            my_name = f'{prefix}_{iset}'

            my_kwargs = static_lib_kwargs.copy()
            my_kwargs['sources'] = sources # type: ignore

            # Add compile args we derived above to those the user provided us
            lang_args_key = compiler.get_language() + '_args'
            old_lang_args = mesonlib.extract_as_list(my_kwargs, lang_args_key) # type: ignore
            all_lang_args = old_lang_args + cargs
            my_kwargs[lang_args_key] = all_lang_args # type: ignore

            lib = self.interpreter.build_target(state.current_node, (my_name, []), my_kwargs, build.StaticLibrary)

            result.append(lib)

        return [result, conf]

def initialize(interp: Interpreter) -> SimdModule:
    return SimdModule(interp)
