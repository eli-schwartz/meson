# Copyright 2013-2021 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .baseobjects import InterpreterObject, MesonInterpreterObject, ObjectHolder, TYPE_var, HoldableTypes
from .exceptions import InvalidArguments
from ..mesonlib import HoldableObject, MesonBugException

def _unholder(obj )  :
    if isinstance(obj, ObjectHolder):
        assert isinstance(obj.held_object, HoldableTypes)
        return obj.held_object
    elif isinstance(obj, MesonInterpreterObject):
        return obj
    elif isinstance(obj, HoldableObject):
        raise MesonBugException('Argument {} of type {} is not held by an ObjectHolder.'.format((obj), (type(obj).__name__)))
    elif isinstance(obj, InterpreterObject):
        raise InvalidArguments('Argument {} of type {} cannot be passed to a method or function'.format((obj), (type(obj).__name__)))
    raise MesonBugException('Unknown object {} of type {} in the parameters.'.format((obj), (type(obj).__name__)))
