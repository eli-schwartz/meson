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

# This file contains the base representation for import('modname')

import typing as T

from .. import build, mesonlib
from ..mesonlib import relpath, HoldableObject, MachineChoice
from ..interpreterbase.decorators import noKwargs, noPosargs

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter
    from ..interpreter.interpreterobjects import MachineHolder
    from ..interpreterbase import TYPE_var, TYPE_kwargs
    from ..programs import ExternalProgram
    from ..wrap import WrapMode
    from ..build import EnvironmentVariables

class ModuleState:
    """Object passed to all module methods.

    This is a WIP API provided to modules, it should be extended to have everything
    needed so modules does not touch any other part of Meson internal APIs.
    """

    def __init__(self, interpreter )  :
        # Keep it private, it should be accessed only through methods.
        self._interpreter = interpreter

        self.source_root = interpreter.environment.get_source_dir()
        self.build_to_src = relpath(interpreter.environment.get_source_dir(),
                                    interpreter.environment.get_build_dir())
        self.subproject = interpreter.subproject
        self.subdir = interpreter.subdir
        self.current_lineno = interpreter.current_lineno
        self.environment = interpreter.environment
        self.project_name = interpreter.build.project_name
        self.project_version = interpreter.build.dep_manifest[interpreter.active_projectname].version
        # The backend object is under-used right now, but we will need it:
        # https://github.com/mesonbuild/meson/issues/1419
        self.backend = interpreter.backend
        self.targets = interpreter.build.targets
        self.data = interpreter.build.data
        self.headers = interpreter.build.get_headers()
        self.man = interpreter.build.get_man()
        self.global_args = interpreter.build.global_args.host
        self.project_args = interpreter.build.projects_args.host.get(interpreter.subproject, {})
        self.build_machine = T.cast('MachineHolder', interpreter.builtin['build_machine']).held_object
        self.host_machine = T.cast('MachineHolder', interpreter.builtin['host_machine']).held_object
        self.target_machine = T.cast('MachineHolder', interpreter.builtin['target_machine']).held_object
        self.current_node = interpreter.current_node

    def get_include_args(self, include_dirs  , prefix  = '-I')  :
        if not include_dirs:
            return []

        srcdir = self.environment.get_source_dir()
        builddir = self.environment.get_build_dir()

        dirs_str  = []
        for dirs in include_dirs:
            if isinstance(dirs, str):
                dirs_str += ['{}{}'.format((prefix), (dirs))]
            else:
                dirs_str.extend(['{}{}'.format((prefix), (i)) for i in dirs.to_string_list(srcdir, builddir)])
                dirs_str.extend(['{}{}'.format((prefix), (i)) for i in dirs.get_extra_build_dirs()])

        return dirs_str

    def find_program(self, prog  , required  = True,
                     version_func   = None,
                     wanted  = None, silent  = False,
                     for_machine  = MachineChoice.HOST)  :
        return self._interpreter.find_program_impl(prog, required=required, version_func=version_func,
                                                   wanted=wanted, silent=silent, for_machine=for_machine)

    def test(self, args     ,
             workdir  = None,
             env     = None,
             depends   = None)  :
        kwargs = {'workdir': workdir,
                  'env': env,
                  'depends': depends,
                  }
        # typed_* takes a list, and gives a tuple to func_test. Violating that constraint
        # makes the universe (or at least use of this function) implode
        real_args = list(args)
        # TODO: Use interpreter internal API, but we need to go through @typed_kwargs
        self._interpreter.func_test(self.current_node, real_args, kwargs)

    def get_option(self, name , subproject  = '',
                   machine  = MachineChoice.HOST,
                   lang  = None,
                   module  = None)     :
        return self.environment.coredata.get_option(mesonlib.OptionKey(name, subproject, machine, lang, module))

    def is_user_defined_option(self, name , subproject  = '',
                               machine  = MachineChoice.HOST,
                               lang  = None,
                               module  = None)  :
        key = mesonlib.OptionKey(name, subproject, machine, lang, module)
        return key in self._interpreter.user_defined_options.cmd_line_options


class ModuleObject(HoldableObject):
    """Base class for all objects returned by modules
    """
    def __init__(self)  :
        self.methods                                      = {}





class MutableModuleObject(ModuleObject):
    pass

class NewExtensionModule(ModuleObject):

    """Class for modern modules

    provides the found method.
    """

    def __init__(self)  :
        super().__init__()
        self.methods.update({
            'found': self.found_method,
        })

    @noPosargs
    @noKwargs
    def found_method(self, state , args , kwargs )  :
        return self.found()

    @staticmethod
    def found()  :
        return True

    def get_devenv(self)  :
        return None

# FIXME: Port all modules to stop using self.interpreter and use API on
# ModuleState instead. Modules should stop using this class and instead use
# ModuleObject base class.
class ExtensionModule(NewExtensionModule):
    def __init__(self, interpreter )  :
        super().__init__()
        self.interpreter = interpreter

class NotFoundExtensionModule(NewExtensionModule):

    """Class for modern modules

    provides the found method.
    """

    @staticmethod
    def found()  :
        return False


def is_module_library(fname):
    '''
    Check if the file is a library-like file generated by a module-specific
    target, such as GirTarget or TypelibTarget
    '''
    if hasattr(fname, 'fname'):
        fname = fname.fname
    suffix = fname.split('.')[-1]
    return suffix in ('gir', 'typelib')


class ModuleReturnValue:
    def __init__(self, return_value ,
                 new_objects  )  :
        self.return_value = return_value
        assert isinstance(new_objects, list)
        self.new_objects   = new_objects

class GResourceTarget(build.CustomTarget):
    pass

class GResourceHeaderTarget(build.CustomTarget):
    pass

class GirTarget(build.CustomTarget):
    pass

class TypelibTarget(build.CustomTarget):
    pass

class VapiTarget(build.CustomTarget):
    pass
