# SPDX-License-Identifer: Apache-2.0
# Copyright 2021 The Meson development team

from .common import cmake_is_debug
from .. import mlog

from pathlib import Path
import re
import typing as T

if T.TYPE_CHECKING:
    from .traceparser import CMakeTraceParser
    from ..environment import Environment
    from ..compilers import Compiler

class ResolvedTarget:
    def __init__(self)  :
        self.include_directories  = []
        self.link_flags           = []
        self.public_compile_opts  = []
        self.libraries            = []

def resolve_cmake_trace_targets(target_name ,
                                trace ,
                                env ,
                                *,
                                clib_compiler  = None,
                                not_found_warning   = lambda x: None)  :
    res = ResolvedTarget()
    targets = [target_name]

    # recognise arguments we should pass directly to the linker
    reg_is_lib = re.compile(r'^(-l[a-zA-Z0-9_]+|-l?pthread)$')
    reg_is_maybe_bare_lib = re.compile(r'^[a-zA-Z0-9_]+$')

    is_debug = cmake_is_debug(env)

    processed_targets  = []
    while len(targets) > 0:
        curr = targets.pop(0)

        # Skip already processed targets
        if curr in processed_targets:
            continue

        if curr not in trace.targets:
            if reg_is_lib.match(curr):
                res.libraries += [curr]
            elif Path(curr).is_absolute() and Path(curr).exists():
                res.libraries += [curr]
            elif env.machines.build.is_windows() and reg_is_maybe_bare_lib.match(curr) and clib_compiler is not None:
                # On Windows, CMake library dependencies can be passed as bare library names,
                # CMake brute-forces a combination of prefix/suffix combinations to find the
                # right library. Assume any bare argument passed which is not also a CMake
                # target must be a system library we should try to link against.
                res.libraries += clib_compiler.find_library(curr, env, [])
            else:
                not_found_warning(curr)
            continue

        tgt = trace.targets[curr]
        cfgs = []
        cfg = ''
        mlog.debug(tgt)

        if 'INTERFACE_INCLUDE_DIRECTORIES' in tgt.properties:
            res.include_directories += [x for x in tgt.properties['INTERFACE_INCLUDE_DIRECTORIES'] if x]

        if 'INTERFACE_LINK_OPTIONS' in tgt.properties:
            res.link_flags += [x for x in tgt.properties['INTERFACE_LINK_OPTIONS'] if x]

        if 'INTERFACE_COMPILE_DEFINITIONS' in tgt.properties:
            res.public_compile_opts += ['-D' + re.sub('^-D', '', x) for x in tgt.properties['INTERFACE_COMPILE_DEFINITIONS'] if x]

        if 'INTERFACE_COMPILE_OPTIONS' in tgt.properties:
            res.public_compile_opts += [x for x in tgt.properties['INTERFACE_COMPILE_OPTIONS'] if x]

        if 'IMPORTED_CONFIGURATIONS' in tgt.properties:
            cfgs = [x for x in tgt.properties['IMPORTED_CONFIGURATIONS'] if x]
            cfg = cfgs[0]

        if is_debug:
            if 'DEBUG' in cfgs:
                cfg = 'DEBUG'
            elif 'RELEASE' in cfgs:
                cfg = 'RELEASE'
        else:
            if 'RELEASE' in cfgs:
                cfg = 'RELEASE'

        if 'IMPORTED_IMPLIB_{}'.format((cfg)) in tgt.properties:
            res.libraries += [x for x in tgt.properties['IMPORTED_IMPLIB_{}'.format((cfg))] if x]
        elif 'IMPORTED_IMPLIB' in tgt.properties:
            res.libraries += [x for x in tgt.properties['IMPORTED_IMPLIB'] if x]
        elif 'IMPORTED_LOCATION_{}'.format((cfg)) in tgt.properties:
            res.libraries += [x for x in tgt.properties['IMPORTED_LOCATION_{}'.format((cfg))] if x]
        elif 'IMPORTED_LOCATION' in tgt.properties:
            res.libraries += [x for x in tgt.properties['IMPORTED_LOCATION'] if x]

        if 'LINK_LIBRARIES' in tgt.properties:
            targets += [x for x in tgt.properties['LINK_LIBRARIES'] if x]
        if 'INTERFACE_LINK_LIBRARIES' in tgt.properties:
            targets += [x for x in tgt.properties['INTERFACE_LINK_LIBRARIES'] if x]

        if 'IMPORTED_LINK_DEPENDENT_LIBRARIES_{}'.format((cfg)) in tgt.properties:
            targets += [x for x in tgt.properties['IMPORTED_LINK_DEPENDENT_LIBRARIES_{}'.format((cfg))] if x]
        elif 'IMPORTED_LINK_DEPENDENT_LIBRARIES' in tgt.properties:
            targets += [x for x in tgt.properties['IMPORTED_LINK_DEPENDENT_LIBRARIES'] if x]

        processed_targets += [curr]

    res.include_directories = sorted(set(res.include_directories))
    res.link_flags          = sorted(set(res.link_flags))
    res.public_compile_opts = sorted(set(res.public_compile_opts))
    res.libraries           = sorted(set(res.libraries))

    return res
