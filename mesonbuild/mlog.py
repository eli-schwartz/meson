# Copyright 2013-2014 The Meson development team

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
import io
import sys
import time
import platform
import typing as T
from contextlib import contextmanager
from pathlib import Path

if T.TYPE_CHECKING:
    from ._typing import StringProtocol, SizedStringProtocol

"""This is (mostly) a standalone module used to write logging
information about Meson runs. Some output goes to screen,
some to logging dir and some goes to both."""

def _windows_ansi()  :
    # windll only exists on windows, so mypy will get mad
    from ctypes import windll, byref  # type: ignore
    from ctypes.wintypes import DWORD

    kernel = windll.kernel32
    stdout = kernel.GetStdHandle(-11)
    mode = DWORD()
    if not kernel.GetConsoleMode(stdout, byref(mode)):
        return False
    # ENABLE_VIRTUAL_TERMINAL_PROCESSING == 0x4
    # If the call to enable VT processing fails (returns 0), we fallback to
    # original behavior
    return bool(kernel.SetConsoleMode(stdout, mode.value | 0x4) or os.environ.get('ANSICON'))

def colorize_console()  :
    _colorize_console = getattr(sys.stdout, 'colorize_console', None)  # type: bool
    if _colorize_console is not None:
        return _colorize_console

    try:
        if platform.system().lower() == 'windows':
            _colorize_console = os.isatty(sys.stdout.fileno()) and _windows_ansi()
        else:
            _colorize_console = os.isatty(sys.stdout.fileno()) and os.environ.get('TERM', 'dumb') != 'dumb'
    except Exception:
        _colorize_console = False

    sys.stdout.colorize_console = _colorize_console  # type: ignore[attr-defined]
    return _colorize_console

def setup_console()  :
    # on Windows, a subprocess might call SetConsoleMode() on the console
    # connected to stdout and turn off ANSI escape processing. Call this after
    # running a subprocess to ensure we turn it on again.
    if platform.system().lower() == 'windows':
        try:
            delattr(sys.stdout, 'colorize_console')
        except AttributeError:
            pass

log_dir = None               # type: T.Optional[str]
log_file = None              # type: T.Optional[T.TextIO]
log_fname = 'meson-log.txt'  # type: str
log_depth = []               # type: T.List[str]
log_timestamp_start = None   # type: T.Optional[float]
log_fatal_warnings = False   # type: bool
log_disable_stdout = False   # type: bool
log_errors_only = False      # type: bool
_in_ci = 'CI' in os.environ  # type: bool
_logged_once = set()         # type: T.Set[T.Tuple[str, ...]]
log_warnings_counter = 0     # type: int

def disable()  :
    global log_disable_stdout
    log_disable_stdout = True

def enable()  :
    global log_disable_stdout
    log_disable_stdout = False

def set_quiet()  :
    global log_errors_only
    log_errors_only = True

def set_verbose()  :
    global log_errors_only
    log_errors_only = False

def initialize(logdir , fatal_warnings  = False)  :
    global log_dir, log_file, log_fatal_warnings
    log_dir = logdir
    log_file = open(os.path.join(logdir, log_fname), 'w', encoding='utf-8')
    log_fatal_warnings = fatal_warnings

def set_timestamp_start(start )  :
    global log_timestamp_start
    log_timestamp_start = start

def shutdown()  :
    global log_file
    if log_file is not None:
        path = log_file.name
        exception_around_goer = log_file
        log_file = None
        exception_around_goer.close()
        return path
    return None

class AnsiDecorator:
    plain_code = "\033[0m"

    def __init__(self, text , code , quoted  = False):
        self.text = text
        self.code = code
        self.quoted = quoted

    def get_text(self, with_codes )  :
        text = self.text
        if with_codes and self.code:
            text = self.code + self.text + AnsiDecorator.plain_code
        if self.quoted:
            text = '"{}"'.format((text))
        return text

    def __len__(self)  :
        return len(self.text)

    def __str__(self)  :
        return self.get_text(colorize_console())

TV_Loggable = T.Union[str, AnsiDecorator, 'StringProtocol']
TV_LoggableList = T.List[TV_Loggable]

class AnsiText:
    def __init__(self, *args ):
        self.args = args

    def __len__(self)  :
        return sum(len(x) for x in self.args)

    def __str__(self)  :
        return ''.join(str(x) for x in self.args)


def bold(text , quoted  = False)  :
    return AnsiDecorator(text, "\033[1m", quoted=quoted)

def plain(text )  :
    return AnsiDecorator(text, "")

def red(text )  :
    return AnsiDecorator(text, "\033[1;31m")

def green(text )  :
    return AnsiDecorator(text, "\033[1;32m")

def yellow(text )  :
    return AnsiDecorator(text, "\033[1;33m")

def blue(text )  :
    return AnsiDecorator(text, "\033[1;34m")

def cyan(text )  :
    return AnsiDecorator(text, "\033[1;36m")

def normal_red(text )  :
    return AnsiDecorator(text, "\033[31m")

def normal_green(text )  :
    return AnsiDecorator(text, "\033[32m")

def normal_yellow(text )  :
    return AnsiDecorator(text, "\033[33m")

def normal_blue(text )  :
    return AnsiDecorator(text, "\033[34m")

def normal_cyan(text )  :
    return AnsiDecorator(text, "\033[36m")

# This really should be AnsiDecorator or anything that implements
# __str__(), but that requires protocols from typing_extensions
def process_markup(args , keep )  :
    arr = []  # type: T.List[str]
    if log_timestamp_start is not None:
        arr = ['[{:.3f}]'.format(time.monotonic() - log_timestamp_start)]
    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, str):
            arr.append(arg)
        elif isinstance(arg, AnsiDecorator):
            arr.append(arg.get_text(keep))
        else:
            arr.append(str(arg))
    return arr

def force_print(*args , nested , **kwargs )  :
    if log_disable_stdout:
        return
    iostr = io.StringIO()
    kwargs['file'] = iostr
    print(*args, **kwargs)

    raw = iostr.getvalue()
    if log_depth:
        prepend = log_depth[-1] + '| ' if nested else ''
        lines = []
        for l in raw.split('\n'):
            l = l.strip()
            lines.append(prepend + l if l else '')
        raw = '\n'.join(lines)

    # _Something_ is going to get printed.
    try:
        print(raw, end='')
    except UnicodeEncodeError:
        cleaned = raw.encode('ascii', 'replace').decode('ascii')
        print(cleaned, end='')

# We really want a heterogeneous dict for this, but that's in typing_extensions
def debug(*args , **kwargs )  :
    arr = process_markup(args, False)
    if log_file is not None:
        print(*arr, file=log_file, **kwargs)
        log_file.flush()

def _debug_log_cmd(cmd , args )  :
    if not _in_ci:
        return
    args = ['"{}"'.format((x)) for x in args]  # Quote all args, just in case
    debug('!meson_ci!/{} {}'.format(cmd, ' '.join(args)))

def cmd_ci_include(file )  :
    _debug_log_cmd('ci_include', [file])


def log(*args , is_error  = False,
        once  = False, **kwargs )  :
    if once:
        log_once(*args, is_error=is_error, **kwargs)
    else:
        _log(*args, is_error=is_error, **kwargs)


def _log(*args , is_error  = False,
         **kwargs )  :
    nested = kwargs.pop('nested', True)
    arr = process_markup(args, False)
    if log_file is not None:
        print(*arr, file=log_file, **kwargs)
        log_file.flush()
    if colorize_console():
        arr = process_markup(args, True)
    if not log_errors_only or is_error:
        force_print(*arr, nested=nested, **kwargs)

def log_once(*args , is_error  = False,
             **kwargs )  :
    """Log variant that only prints a given message one time per meson invocation.

    This considers ansi decorated values by the values they wrap without
    regard for the AnsiDecorator itself.
    """
    def to_str(x )  :
        if isinstance(x, str):
            return x
        if isinstance(x, AnsiDecorator):
            return x.text
        return str(x)
    t = tuple(to_str(a) for a in args)
    if t in _logged_once:
        return
    _logged_once.add(t)
    _log(*args, is_error=is_error, **kwargs)

# This isn't strictly correct. What we really want here is something like:
# class StringProtocol(typing_extensions.Protocol):
#
#      def __str__(self) -> str: ...
#
# This would more accurately embody what this function can handle, but we
# don't have that yet, so instead we'll do some casting to work around it
def get_error_location_string(fname , lineno )  :
    return '{}:{}:'.format((fname), (lineno))

def _log_error(severity , *rargs ,
               once  = False, fatal  = True, **kwargs )  :
    from .mesonlib import MesonException, relpath

    # The typing requirements here are non-obvious. Lists are invariant,
    # therefore T.List[A] and T.List[T.Union[A, B]] are not able to be joined
    if severity == 'notice':
        label = [bold('NOTICE:')]  # type: TV_LoggableList
    elif severity == 'warning':
        label = [yellow('WARNING:')]
    elif severity == 'error':
        label = [red('ERROR:')]
    elif severity == 'deprecation':
        label = [red('DEPRECATION:')]
    else:
        raise MesonException('Invalid severity ' + severity)
    # rargs is a tuple, not a list
    args = label + list(rargs)

    location = kwargs.pop('location', None)
    if location is not None:
        location_file = relpath(location.filename, os.getcwd())
        location_str = get_error_location_string(location_file, location.lineno)
        # Unions are frankly awful, and we have to T.cast here to get mypy
        # to understand that the list concatenation is safe
        location_list = T.cast('TV_LoggableList', [location_str])
        args = location_list + args

    log(*args, once=once, **kwargs)

    global log_warnings_counter
    log_warnings_counter += 1

    if log_fatal_warnings and fatal:
        raise MesonException("Fatal warnings enabled, aborting")

def error(*args , **kwargs )  :
    return _log_error('error', *args, **kwargs, is_error=True)

def warning(*args , **kwargs )  :
    return _log_error('warning', *args, **kwargs, is_error=True)

def deprecation(*args , **kwargs )  :
    return _log_error('deprecation', *args, **kwargs, is_error=True)

def notice(*args , **kwargs )  :
    return _log_error('notice', *args, **kwargs, is_error=False)

def get_relative_path(target , current )  :
    """Get the path to target from current"""
    # Go up "current" until we find a common ancestor to target
    acc = ['.']
    for part in [current, *current.parents]:
        try:
            path = target.relative_to(part)
            return Path(*acc, path)
        except ValueError:
            pass
        acc += ['..']

    # we failed, should not get here
    return target

def exception(e , prefix  = None)  :
    if prefix is None:
        prefix = red('ERROR:')
    log()
    args = []  # type: T.List[T.Union[AnsiDecorator, str]]
    if all(getattr(e, a, None) is not None for a in ['file', 'lineno', 'colno']):
        # Mypy doesn't follow hasattr, and it's pretty easy to visually inspect
        # that this is correct, so we'll just ignore it.
        path = get_relative_path(Path(e.file), Path(os.getcwd()))  # type: ignore
        args.append('{}:{}:{}:'.format((path), (e.lineno), (e.colno)))  # type: ignore
    if prefix:
        args.append(prefix)
    args.append(str(e))
    log(*args)

# Format a list for logging purposes as a string. It separates
# all but the last item with commas, and the last with 'and'.
def format_list(input_list )  :
    l = len(input_list)
    if l > 2:
        return ' and '.join([', '.join(input_list[:-1]), input_list[-1]])
    elif l == 2:
        return ' and '.join(input_list)
    elif l == 1:
        return input_list[0]
    else:
        return ''

@contextmanager
def nested(name  = '')    :
    global log_depth
    log_depth.append(name)
    try:
        yield
    finally:
        log_depth.pop()
