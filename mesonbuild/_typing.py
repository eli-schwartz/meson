# SPDX-License-Identifer: Apache-2.0
# Copyright 2020 The Meson development team
# Copyright © 2020-2021 Intel Corporation

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Meson specific typing helpers.

Holds typing helper classes, such as the ImmutableProtocol classes
"""

__all__ = [
    'Protocol',
    'ImmutableListProtocol'
]

import typing

# We can change this to typing when we require python 3.8
from typing_extensions import Protocol


T = typing.TypeVar('T')


class StringProtocol(Protocol):
    def __str__(self)  : ...

class SizedStringProtocol(Protocol, StringProtocol, typing.Sized):
    pass

class ImmutableListProtocol(Protocol[T]):

    """A protocol used in cases where a list is returned, but should not be
    mutated.

    This provides all of the methods of a Sequence, as well as copy(). copy()
    returns a list, which allows mutation as it's a copy and that's (hopefully)
    safe.

    One particular case this is important is for cached values, since python is
    a pass-by-reference language.
    """

    def __iter__(self)  : ...

    @typing.overload
    def __getitem__(self, index )  : ...
    @typing.overload
    def __getitem__(self, index )  : ...

    def __contains__(self, item )  : ...

    def __reversed__(self)  : ...

    def __len__(self)  : ...

    def __add__(self, other )  : ...

    def __eq__(self, other )  : ...
    def __ne__(self, other )  : ...
    def __le__(self, other )  : ...
    def __lt__(self, other )  : ...
    def __gt__(self, other )  : ...
    def __ge__(self, other )  : ...

    def count(self, item )  : ...

    def index(self, item )  : ...

    def copy(self)  : ...


class ImmutableSetProtocol(Protocol[T]):

    """A protocol for a set that cannot be mutated.

    This provides for cases where mutation of the set is undesired. Although
    this will be allowed at runtime, mypy (or another type checker), will see
    any attempt to use mutative methods as an error.
    """

    def __iter__(self)  : ...

    def __contains__(self, item )  : ...

    def __len__(self)  : ...

    def __add__(self, other )  : ...

    def __eq__(self, other )  : ...
    def __ne__(self, other )  : ...
    def __le__(self, other )  : ...
    def __lt__(self, other )  : ...
    def __gt__(self, other )  : ...
    def __ge__(self, other )  : ...

    def copy(self)  : ...

    def difference(self, other )  : ...

    def intersection(self, other )  : ...

    def issubset(self, other )  : ...

    def issuperset(self, other )  : ...

    def symmetric_difference(self, other )  : ...

    def union(self, other )  : ...
