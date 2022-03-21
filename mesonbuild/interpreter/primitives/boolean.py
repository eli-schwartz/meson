# Copyright 2021 The Meson development team
# SPDX-license-identifier: Apache-2.0

from ...interpreterbase import (
    ObjectHolder,
    MesonOperator,
    typed_pos_args,
    noKwargs,
    noPosargs,

    TYPE_var,
    TYPE_kwargs,

    InvalidArguments
)

import typing as T

if T.TYPE_CHECKING:
    # Object holders need the actual interpreter
    from ...interpreter import Interpreter

class BooleanHolder(ObjectHolder[bool]):
    def __init__(self, obj , interpreter )  :
        super().__init__(obj, interpreter)
        self.methods.update({
            'to_int': self.to_int_method,
            'to_string': self.to_string_method,
        })

        self.trivial_operators.update({
            MesonOperator.BOOL: (None, lambda x: self.held_object),
            MesonOperator.NOT: (None, lambda x: not self.held_object),
            MesonOperator.EQUALS: (bool, lambda x: self.held_object == x),
            MesonOperator.NOT_EQUALS: (bool, lambda x: self.held_object != x),
        })

    def display_name(self)  :
        return 'bool'

    @noKwargs
    @noPosargs
    def to_int_method(self, args , kwargs )  :
        return 1 if self.held_object else 0

    @noKwargs
    @typed_pos_args('bool.to_string', optargs=[str, str])
    def to_string_method(self, args  , kwargs )  :
        true_str = args[0] or 'true'
        false_str = args[1] or 'false'
        if any(x is not None for x in args) and not all(x is not None for x in args):
            raise InvalidArguments('bool.to_string() must have either no arguments or exactly two string arguments that signify what values to return for true and false.')
        return true_str if self.held_object else false_str
