# Copyright 2021 The Meson development team
# SPDX-license-identifier: Apache-2.0

import typing as T

from ...interpreterbase import (
    MesonInterpreterObject,
    IterableObject,
    MesonOperator,
    InvalidArguments,
)

if T.TYPE_CHECKING:
    from ...interpreterbase import SubProject

class RangeHolder(MesonInterpreterObject, IterableObject):
    def __init__(self, start , stop , step , *, subproject )  :
        super().__init__(subproject=subproject)
        self.range = range(start, stop, step)
        self.operators.update({
            MesonOperator.INDEX: self.op_index,
        })

    def op_index(self, other )  :
        try:
            return self.range[other]
        except IndexError:
            raise InvalidArguments('Index {} out of bounds of range.'.format((other)))

    def iter_tuple_size(self)  :
        return None

    def iter_self(self)  :
        return iter(self.range)

    def size(self)  :
        return len(self.range)
