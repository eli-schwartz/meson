# Copyright 2021 The Meson development team
# SPDX-license-identifier: Apache-2.0
from __future__ import annotations

import re
import os

import typing as T

from ...mesonlib import version_compare
from ...interpreterbase import (
    ObjectHolder,
    MesonOperator,
    FeatureNew,
    typed_operator,
    noArgsFlattening,
    noKwargs,
    noPosargs,
    typed_pos_args,

    InvalidArguments,
)


if T.TYPE_CHECKING:
    # Object holders need the actual interpreter
    from ...interpreter import Interpreter
    from ...interpreterbase import TYPE_var, TYPE_kwargs

class StringHolder(ObjectHolder[str]):
    def __init__(self, obj , interpreter )  :
        super().__init__(obj, interpreter)
        self.methods.update({
            'contains': self.contains_method,
            'startswith': self.startswith_method,
            'endswith': self.endswith_method,
            'format': self.format_method,
            'join': self.join_method,
            'replace': self.replace_method,
            'split': self.split_method,
            'strip': self.strip_method,
            'substring': self.substring_method,
            'to_int': self.to_int_method,
            'to_lower': self.to_lower_method,
            'to_upper': self.to_upper_method,
            'underscorify': self.underscorify_method,
            'version_compare': self.version_compare_method,
        })

        self.trivial_operators.update({
            # Arithmetic
            MesonOperator.PLUS: (str, lambda x: self.held_object + x),

            # Comparison
            MesonOperator.EQUALS: (str, lambda x: self.held_object == x),
            MesonOperator.NOT_EQUALS: (str, lambda x: self.held_object != x),
            MesonOperator.GREATER: (str, lambda x: self.held_object > x),
            MesonOperator.LESS: (str, lambda x: self.held_object < x),
            MesonOperator.GREATER_EQUALS: (str, lambda x: self.held_object >= x),
            MesonOperator.LESS_EQUALS: (str, lambda x: self.held_object <= x),
        })

        # Use actual methods for functions that require additional checks
        self.operators.update({
            MesonOperator.DIV: self.op_div,
            MesonOperator.INDEX: self.op_index,
        })

    def display_name(self)  :
        return 'str'

    @noKwargs
    @typed_pos_args('str.contains', str)
    def contains_method(self, args , kwargs )  :
        return self.held_object.find(args[0]) >= 0

    @noKwargs
    @typed_pos_args('str.startswith', str)
    def startswith_method(self, args , kwargs )  :
        return self.held_object.startswith(args[0])

    @noKwargs
    @typed_pos_args('str.endswith', str)
    def endswith_method(self, args , kwargs )  :
        return self.held_object.endswith(args[0])

    @noArgsFlattening
    @noKwargs
    @typed_pos_args('str.format', varargs=object)
    def format_method(self, args , kwargs )  :
        arg_strings  = []
        for arg in args[0]:
            if isinstance(arg, bool): # Python boolean is upper case.
                arg = str(arg).lower()
            arg_strings.append(str(arg))

        def arg_replace(match )  :
            idx = int(match.group(1))
            if idx >= len(arg_strings):
                raise InvalidArguments('Format placeholder @{}@ out of range.'.format((idx)))
            return arg_strings[idx]

        return re.sub(r'@(\d+)@', arg_replace, self.held_object)

    @noKwargs
    @typed_pos_args('str.join', varargs=str)
    def join_method(self, args , kwargs )  :
        return self.held_object.join(args[0])

    @noKwargs
    @typed_pos_args('str.replace', str, str)
    def replace_method(self, args  , kwargs )  :
        return self.held_object.replace(args[0], args[1])

    @noKwargs
    @typed_pos_args('str.split', optargs=[str])
    def split_method(self, args , kwargs )  :
        return self.held_object.split(args[0])

    @noKwargs
    @typed_pos_args('str.strip', optargs=[str])
    def strip_method(self, args , kwargs )  :
        return self.held_object.strip(args[0])

    @noKwargs
    @typed_pos_args('str.substring', optargs=[int, int])
    def substring_method(self, args  , kwargs )  :
        start = args[0] if args[0] is not None else 0
        end   = args[1] if args[1] is not None else len(self.held_object)
        return self.held_object[start:end]

    @noKwargs
    @noPosargs
    def to_int_method(self, args , kwargs )  :
        try:
            return int(self.held_object)
        except ValueError:
            raise InvalidArguments('String {!r} cannot be converted to int'.format((self.held_object)))

    @noKwargs
    @noPosargs
    def to_lower_method(self, args , kwargs )  :
        return self.held_object.lower()

    @noKwargs
    @noPosargs
    def to_upper_method(self, args , kwargs )  :
        return self.held_object.upper()

    @noKwargs
    @noPosargs
    def underscorify_method(self, args , kwargs )  :
        return re.sub(r'[^a-zA-Z0-9]', '_', self.held_object)

    @noKwargs
    @typed_pos_args('str.version_compare', str)
    def version_compare_method(self, args , kwargs )  :
        return version_compare(self.held_object, args[0])

    @FeatureNew('/ with string arguments', '0.49.0')
    @typed_operator(MesonOperator.DIV, str)
    def op_div(self, other )  :
        return os.path.join(self.held_object, other).replace('\\', '/')

    @typed_operator(MesonOperator.INDEX, int)
    def op_index(self, other )  :
        try:
            return self.held_object[other]
        except IndexError:
            raise InvalidArguments('Index {} out of bounds of string of size {}.'.format((other), (len(self.held_object))))


class MesonVersionString(str):
    pass

class MesonVersionStringHolder(StringHolder):
    @noKwargs
    @typed_pos_args('str.version_compare', str)
    def version_compare_method(self, args , kwargs )  :
        self.interpreter.tmp_meson_version = args[0]
        return version_compare(self.held_object, args[0])
