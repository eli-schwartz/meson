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

from glob import glob
from pathlib import Path
import argparse
import errno
import os
import pickle
import shlex
import shutil
import subprocess
import sys
import typing as T

from . import build
from . import environment
from .backend.backends import (
    InstallData, InstallDataBase, InstallEmptyDir, InstallSymlinkData,
    TargetInstallData, ExecutableSerialisation
)
from .coredata import major_versions_differ, MesonVersionMismatchException
from .coredata import version as coredata_version
from .mesonlib import MesonException, Popen_safe, RealPathAction, is_windows, setup_vsenv
from .scripts import depfixer, destdir_join
from .scripts.meson_exe import run_exe
try:
    from __main__ import __file__ as main_file
except ImportError:
    # Happens when running as meson.exe which is native Windows.
    # This is only used for pkexec which is not, so this is fine.
    main_file = None

symlink_warning = '''Warning: trying to copy a symlink that points to a file. This will copy the file,
but this will be changed in a future version of Meson to copy the symlink as is. Please update your
build definitions so that it will not break when the change happens.'''

selinux_updates  = []

def add_arguments(parser )  :
    parser.add_argument('-C', dest='wd', action=RealPathAction,
                        help='directory to cd into before running')
    parser.add_argument('--profile-self', action='store_true', dest='profile',
                        help=argparse.SUPPRESS)
    parser.add_argument('--no-rebuild', default=False, action='store_true',
                        help='Do not rebuild before installing.')
    parser.add_argument('--only-changed', default=False, action='store_true',
                        help='Only overwrite files that are older than the copied file.')
    parser.add_argument('--quiet', default=False, action='store_true',
                        help='Do not print every file that was installed.')
    parser.add_argument('--destdir', default=None,
                        help='Sets or overrides DESTDIR environment. (Since 0.57.0)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Doesn\'t actually install, but print logs. (Since 0.57.0)')
    parser.add_argument('--skip-subprojects', nargs='?', const='*', default='',
                        help='Do not install files from given subprojects. (Since 0.58.0)')
    parser.add_argument('--tags', default=None,
                        help='Install only targets having one of the given tags. (Since 0.60.0)')
    parser.add_argument('--strip', action='store_true',
                        help='Strip targets even if strip option was not set during configure. (Since 0.62.0)')

class DirMaker:
    def __init__(self, lf , makedirs  ):
        self.lf = lf
        self.dirs  = []
        self.all_dirs  = set()
        self.makedirs_impl = makedirs

    def makedirs(self, path , exist_ok  = False)  :
        dirname = os.path.normpath(path)
        self.all_dirs.add(dirname)
        dirs = []
        while dirname != os.path.dirname(dirname):
            if dirname in self.dirs:
                # In dry-run mode the directory does not exist but we would have
                # created it with all its parents otherwise.
                break
            if not os.path.exists(dirname):
                dirs.append(dirname)
            dirname = os.path.dirname(dirname)
        self.makedirs_impl(path, exist_ok=exist_ok)

        # store the directories in creation order, with the parent directory
        # before the child directories. Future calls of makedir() will not
        # create the parent directories, so the last element in the list is
        # the last one to be created. That is the first one to be removed on
        # __exit__
        dirs.reverse()
        self.dirs += dirs

    def __enter__(self)  :
        return self

    def __exit__(self, exception_type , value , traceback )  :
        self.dirs.reverse()
        for d in self.dirs:
            append_to_log(self.lf, d)


def load_install_data(fname )  :
    with open(fname, 'rb') as ifile:
        obj = pickle.load(ifile)
        if not isinstance(obj, InstallData) or not hasattr(obj, 'version'):
            raise MesonVersionMismatchException('<unknown>', coredata_version)
        if major_versions_differ(obj.version, coredata_version):
            raise MesonVersionMismatchException(obj.version, coredata_version)
        return obj

def is_executable(path , follow_symlinks  = False)  :
    '''Checks whether any of the "x" bits are set in the source file mode.'''
    return bool(os.stat(path, follow_symlinks=follow_symlinks).st_mode & 0o111)


def append_to_log(lf , line )  :
    lf.write(line)
    if not line.endswith('\n'):
        lf.write('\n')
    lf.flush()


def set_chown(path , user    = None,
              group    = None,
              dir_fd  = None, follow_symlinks  = True)  :
    # shutil.chown will call os.chown without passing all the parameters
    # and particularly follow_symlinks, thus we replace it temporary
    # with a lambda with all the parameters so that follow_symlinks will
    # be actually passed properly.
    # Not nice, but better than actually rewriting shutil.chown until
    # this python bug is fixed: https://bugs.python.org/issue18108
    real_os_chown = os.chown

    def chown(path     ,
              uid , gid , *, dir_fd  = dir_fd,
              follow_symlinks  = follow_symlinks)  :
        """Override the default behavior of os.chown

        Use a real function rather than a lambda to help mypy out. Also real
        functions are faster.
        """
        real_os_chown(path, uid, gid, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    try:
        os.chown = chown
        shutil.chown(path, user, group)
    finally:
        os.chown = real_os_chown


def set_chmod(path , mode , dir_fd  = None,
              follow_symlinks  = True)  :
    try:
        os.chmod(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    except (NotImplementedError, OSError, SystemError):
        if not os.path.islink(path):
            os.chmod(path, mode, dir_fd=dir_fd)


def sanitize_permissions(path , umask  )  :
    # TODO: with python 3.8 or typing_extensions we could replace this with
    # `umask: T.Union[T.Literal['preserve'], int]`, which would be more correct
    if umask == 'preserve':
        return
    assert isinstance(umask, int), 'umask should only be "preserver" or an integer'
    new_perms = 0o777 if is_executable(path, follow_symlinks=False) else 0o666
    new_perms &= ~umask
    try:
        set_chmod(path, new_perms, follow_symlinks=False)
    except PermissionError as e:
        print('{!r}: Unable to set permissions {!r}: {}, ignoring...'.format((path), (new_perms), (e.strerror)))


def set_mode(path , mode , default_umask  )  :
    if mode is None or all(m is None for m in [mode.perms_s, mode.owner, mode.group]):
        # Just sanitize permissions with the default umask
        sanitize_permissions(path, default_umask)
        return
    # No chown() on Windows, and must set one of owner/group
    if not is_windows() and (mode.owner is not None or mode.group is not None):
        try:
            set_chown(path, mode.owner, mode.group, follow_symlinks=False)
        except PermissionError as e:
            print('{!r}: Unable to set owner {!r} and group {!r}: {}, ignoring...'.format((path), (mode.owner), (mode.group), (e.strerror)))
        except LookupError:
            print('{!r}: Non-existent owner {!r} or group {!r}: ignoring...'.format((path), (mode.owner), (mode.group)))
        except OSError as e:
            if e.errno == errno.EINVAL:
                print('{!r}: Non-existent numeric owner {!r} or group {!r}: ignoring...'.format((path), (mode.owner), (mode.group)))
            else:
                raise
    # Must set permissions *after* setting owner/group otherwise the
    # setuid/setgid bits will get wiped by chmod
    # NOTE: On Windows you can set read/write perms; the rest are ignored
    if mode.perms_s is not None:
        try:
            set_chmod(path, mode.perms, follow_symlinks=False)
        except PermissionError as e:
            print('{!r}: Unable to set permissions {!r}: {}, ignoring...'.format((path), (mode.perms_s), (e.strerror)))
    else:
        sanitize_permissions(path, default_umask)


def restore_selinux_contexts()  :
    '''
    Restores the SELinux context for files in @selinux_updates

    If $DESTDIR is set, do not warn if the call fails.
    '''
    try:
        subprocess.check_call(['selinuxenabled'])
    except (FileNotFoundError, NotADirectoryError, PermissionError, subprocess.CalledProcessError):
        # If we don't have selinux or selinuxenabled returned 1, failure
        # is ignored quietly.
        return

    if not shutil.which('restorecon'):
        # If we don't have restorecon, failure is ignored quietly.
        return

    if not selinux_updates:
        # If the list of files is empty, do not try to call restorecon.
        return

    proc, out, err = Popen_safe(['restorecon', '-F', '-f-', '-0'], ('\0'.join(f for f in selinux_updates) + '\0'))
    if proc.returncode != 0:
        print('Failed to restore SELinux context of installed files...',
              'Standard output:', out,
              'Standard error:', err, sep='\n')

def get_destdir_path(destdir , fullprefix , path )  :
    if os.path.isabs(path):
        output = destdir_join(destdir, path)
    else:
        output = os.path.join(fullprefix, path)
    return output


def check_for_stampfile(fname )  :
    '''Some languages e.g. Rust have output files
    whose names are not known at configure time.
    Check if this is the case and return the real
    file instead.'''
    if fname.endswith('.so') or fname.endswith('.dll'):
        if os.stat(fname).st_size == 0:
            (base, suffix) = os.path.splitext(fname)
            files = glob(base + '-*' + suffix)
            if len(files) > 1:
                print("Stale dynamic library files in build dir. Can't install.")
                sys.exit(1)
            if len(files) == 1:
                return files[0]
    elif fname.endswith('.a') or fname.endswith('.lib'):
        if os.stat(fname).st_size == 0:
            (base, suffix) = os.path.splitext(fname)
            files = glob(base + '-*' + '.rlib')
            if len(files) > 1:
                print("Stale static library files in build dir. Can't install.")
                sys.exit(1)
            if len(files) == 1:
                return files[0]
    return fname


class Installer:

    def __init__(self, options , lf ):
        self.did_install_something = False
        self.printed_symlink_error = False
        self.options = options
        self.lf = lf
        self.preserved_file_count = 0
        self.dry_run = options.dry_run
        # [''] means skip none,
        # ['*'] means skip all,
        # ['sub1', ...] means skip only those.
        self.skip_subprojects = [i.strip() for i in options.skip_subprojects.split(',')]
        self.tags = [i.strip() for i in options.tags.split(',')] if options.tags else None

    def remove(self, *args , **kwargs )  :
        if not self.dry_run:
            os.remove(*args, **kwargs)

    def symlink(self, *args , **kwargs )  :
        if not self.dry_run:
            os.symlink(*args, **kwargs)

    def makedirs(self, *args , **kwargs )  :
        if not self.dry_run:
            os.makedirs(*args, **kwargs)

    def copy(self, *args , **kwargs )  :
        if not self.dry_run:
            shutil.copy(*args, **kwargs)

    def copy2(self, *args , **kwargs )  :
        if not self.dry_run:
            shutil.copy2(*args, **kwargs)

    def copyfile(self, *args , **kwargs )  :
        if not self.dry_run:
            shutil.copyfile(*args, **kwargs)

    def copystat(self, *args , **kwargs )  :
        if not self.dry_run:
            shutil.copystat(*args, **kwargs)

    def fix_rpath(self, *args , **kwargs )  :
        if not self.dry_run:
            depfixer.fix_rpath(*args, **kwargs)

    def set_chown(self, *args , **kwargs )  :
        if not self.dry_run:
            set_chown(*args, **kwargs)

    def set_chmod(self, *args , **kwargs )  :
        if not self.dry_run:
            set_chmod(*args, **kwargs)

    def sanitize_permissions(self, *args , **kwargs )  :
        if not self.dry_run:
            sanitize_permissions(*args, **kwargs)

    def set_mode(self, *args , **kwargs )  :
        if not self.dry_run:
            set_mode(*args, **kwargs)

    def restore_selinux_contexts(self, destdir )  :
        if not self.dry_run and not destdir:
            restore_selinux_contexts()

    def Popen_safe(self, *args , **kwargs )    :
        if not self.dry_run:
            p, o, e = Popen_safe(*args, **kwargs)
            return p.returncode, o, e
        return 0, '', ''

    def run_exe(self, *args , **kwargs )  :
        if not self.dry_run:
            return run_exe(*args, **kwargs)
        return 0

    def should_install(self, d  
                                         
                                        )  :
        if d.subproject and (d.subproject in self.skip_subprojects or '*' in self.skip_subprojects):
            return False
        if self.tags and d.tag not in self.tags:
            return False
        return True

    def log(self, msg )  :
        if not self.options.quiet:
            print(msg)

    def should_preserve_existing_file(self, from_file , to_file )  :
        if not self.options.only_changed:
            return False
        # Always replace danging symlinks
        if os.path.islink(from_file) and not os.path.isfile(from_file):
            return False
        from_time = os.stat(from_file).st_mtime
        to_time = os.stat(to_file).st_mtime
        return from_time <= to_time

    def do_copyfile(self, from_file , to_file ,
                    makedirs   = None)  :
        outdir = os.path.split(to_file)[0]
        if not os.path.isfile(from_file) and not os.path.islink(from_file):
            raise MesonException('Tried to install something that isn\'t a file: {!r}'.format((from_file)))
        # copyfile fails if the target file already exists, so remove it to
        # allow overwriting a previous install. If the target is not a file, we
        # want to give a readable error.
        if os.path.exists(to_file):
            if not os.path.isfile(to_file):
                raise MesonException('Destination {!r} already exists and is not a file'.format((to_file)))
            if self.should_preserve_existing_file(from_file, to_file):
                append_to_log(self.lf, '# Preserving old file {}\n'.format((to_file)))
                self.preserved_file_count += 1
                return False
            self.remove(to_file)
        elif makedirs:
            # Unpack tuple
            dirmaker, outdir = makedirs
            # Create dirs if needed
            dirmaker.makedirs(outdir, exist_ok=True)
        self.log('Installing {} to {}'.format((from_file), (outdir)))
        if os.path.islink(from_file):
            if not os.path.exists(from_file):
                # Dangling symlink. Replicate as is.
                self.copy(from_file, outdir, follow_symlinks=False)
            else:
                # Remove this entire branch when changing the behaviour to duplicate
                # symlinks rather than copying what they point to.
                print(symlink_warning)
                self.copy2(from_file, to_file)
        else:
            self.copy2(from_file, to_file)
        selinux_updates.append(to_file)
        append_to_log(self.lf, to_file)
        return True

    def do_symlink(self, target , link , full_dst_dir , allow_missing )  :
        abs_target = target
        if not os.path.isabs(target):
            abs_target = os.path.join(full_dst_dir, target)
        if not os.path.exists(abs_target) and not allow_missing:
            raise MesonException('Tried to install symlink to missing file {}'.format((abs_target)))
        if os.path.exists(link):
            if not os.path.islink(link):
                raise MesonException('Destination {!r} already exists and is not a symlink'.format((link)))
            self.remove(link)
        if not self.printed_symlink_error:
            self.log('Installing symlink pointing to {} to {}'.format((target), (link)))
        try:
            self.symlink(target, link, target_is_directory=os.path.isdir(abs_target))
        except (NotImplementedError, OSError):
            if not self.printed_symlink_error:
                print("Symlink creation does not work on this platform. "
                      "Skipping all symlinking.")
                self.printed_symlink_error = True
            return False
        append_to_log(self.lf, link)
        return True

    def do_copydir(self, data , src_dir , dst_dir ,
                   exclude  ,
                   install_mode , dm )  :
        '''
        Copies the contents of directory @src_dir into @dst_dir.

        For directory
            /foo/
              bar/
                excluded
                foobar
              file
        do_copydir(..., '/foo', '/dst/dir', {'bar/excluded'}) creates
            /dst/
              dir/
                bar/
                  foobar
                file

        Args:
            src_dir: str, absolute path to the source directory
            dst_dir: str, absolute path to the destination directory
            exclude: (set(str), set(str)), tuple of (exclude_files, exclude_dirs),
                     each element of the set is a path relative to src_dir.
        '''
        if not os.path.isabs(src_dir):
            raise ValueError('src_dir must be absolute, got {}'.format((src_dir)))
        if not os.path.isabs(dst_dir):
            raise ValueError('dst_dir must be absolute, got {}'.format((dst_dir)))
        if exclude is not None:
            exclude_files, exclude_dirs = exclude
        else:
            exclude_files = exclude_dirs = set()
        for root, dirs, files in os.walk(src_dir):
            assert os.path.isabs(root)
            for d in dirs[:]:
                abs_src = os.path.join(root, d)
                filepart = os.path.relpath(abs_src, start=src_dir)
                abs_dst = os.path.join(dst_dir, filepart)
                # Remove these so they aren't visited by os.walk at all.
                if filepart in exclude_dirs:
                    dirs.remove(d)
                    continue
                if os.path.isdir(abs_dst):
                    continue
                if os.path.exists(abs_dst):
                    print('Tried to copy directory {} but a file of that name already exists.'.format((abs_dst)))
                    sys.exit(1)
                dm.makedirs(abs_dst)
                self.copystat(abs_src, abs_dst)
                self.sanitize_permissions(abs_dst, data.install_umask)
            for f in files:
                abs_src = os.path.join(root, f)
                filepart = os.path.relpath(abs_src, start=src_dir)
                if filepart in exclude_files:
                    continue
                abs_dst = os.path.join(dst_dir, filepart)
                if os.path.isdir(abs_dst):
                    print('Tried to copy file {} but a directory of that name already exists.'.format((abs_dst)))
                    sys.exit(1)
                parent_dir = os.path.dirname(abs_dst)
                if not os.path.isdir(parent_dir):
                    dm.makedirs(parent_dir)
                    self.copystat(os.path.dirname(abs_src), parent_dir)
                # FIXME: what about symlinks?
                self.do_copyfile(abs_src, abs_dst)
                self.set_mode(abs_dst, install_mode, data.install_umask)

    def do_install(self, datafilename )  :
        d = load_install_data(datafilename)

        destdir = self.options.destdir
        if destdir is None:
            destdir = os.environ.get('DESTDIR')
        if destdir and not os.path.isabs(destdir):
            destdir = os.path.join(d.build_dir, destdir)
        # Override in the env because some scripts could use it and require an
        # absolute path.
        if destdir is not None:
            os.environ['DESTDIR'] = destdir
        destdir = destdir or ''
        fullprefix = destdir_join(destdir, d.prefix)

        if d.install_umask != 'preserve':
            assert isinstance(d.install_umask, int)
            os.umask(d.install_umask)

        self.did_install_something = False
        try:
            with DirMaker(self.lf, self.makedirs) as dm:
                self.install_subdirs(d, dm, destdir, fullprefix) # Must be first, because it needs to delete the old subtree.
                self.install_targets(d, dm, destdir, fullprefix)
                self.install_headers(d, dm, destdir, fullprefix)
                self.install_man(d, dm, destdir, fullprefix)
                self.install_emptydir(d, dm, destdir, fullprefix)
                self.install_data(d, dm, destdir, fullprefix)
                self.install_symlinks(d, dm, destdir, fullprefix)
                self.restore_selinux_contexts(destdir)
                self.run_install_script(d, destdir, fullprefix)
                if not self.did_install_something:
                    self.log('Nothing to install.')
                if not self.options.quiet and self.preserved_file_count > 0:
                    self.log('Preserved {} unchanged files, see {} for the full list'
                             .format(self.preserved_file_count, os.path.normpath(self.lf.name)))
        except PermissionError:
            if shutil.which('pkexec') is not None and 'PKEXEC_UID' not in os.environ and destdir == '':
                print('Installation failed due to insufficient permissions.')
                print('Attempting to use polkit to gain elevated privileges...')
                os.execlp('pkexec', 'pkexec', sys.executable, main_file, *sys.argv[1:],
                          '-C', os.getcwd())
            else:
                raise

    def do_strip(self, strip_bin , fname , outname )  :
        self.log('Stripping target {!r}.'.format((fname)))
        returncode, stdo, stde = self.Popen_safe(strip_bin + [outname])
        if returncode != 0:
            print('Could not strip file.\n')
            print('Stdout:\n{}\n'.format((stdo)))
            print('Stderr:\n{}\n'.format((stde)))
            sys.exit(1)

    def install_subdirs(self, d , dm , destdir , fullprefix )  :
        for i in d.install_subdirs:
            if not self.should_install(i):
                continue
            self.did_install_something = True
            full_dst_dir = get_destdir_path(destdir, fullprefix, i.install_path)
            self.log('Installing subdir {} to {}'.format((i.path), (full_dst_dir)))
            dm.makedirs(full_dst_dir, exist_ok=True)
            self.do_copydir(d, i.path, full_dst_dir, i.exclude, i.install_mode, dm)

    def install_data(self, d , dm , destdir , fullprefix )  :
        for i in d.data:
            if not self.should_install(i):
                continue
            fullfilename = i.path
            outfilename = get_destdir_path(destdir, fullprefix, i.install_path)
            outdir = os.path.dirname(outfilename)
            if self.do_copyfile(fullfilename, outfilename, makedirs=(dm, outdir)):
                self.did_install_something = True
            self.set_mode(outfilename, i.install_mode, d.install_umask)

    def install_symlinks(self, d , dm , destdir , fullprefix )  :
        for s in d.symlinks:
            if not self.should_install(s):
                continue
            full_dst_dir = get_destdir_path(destdir, fullprefix, s.install_path)
            full_link_name = get_destdir_path(destdir, fullprefix, s.name)
            dm.makedirs(full_dst_dir, exist_ok=True)
            if self.do_symlink(s.target, full_link_name, full_dst_dir, s.allow_missing):
                self.did_install_something = True

    def install_man(self, d , dm , destdir , fullprefix )  :
        for m in d.man:
            if not self.should_install(m):
                continue
            full_source_filename = m.path
            outfilename = get_destdir_path(destdir, fullprefix, m.install_path)
            outdir = os.path.dirname(outfilename)
            if self.do_copyfile(full_source_filename, outfilename, makedirs=(dm, outdir)):
                self.did_install_something = True
            self.set_mode(outfilename, m.install_mode, d.install_umask)

    def install_emptydir(self, d , dm , destdir , fullprefix )  :
        for e in d.emptydir:
            if not self.should_install(e):
                continue
            self.did_install_something = True
            full_dst_dir = get_destdir_path(destdir, fullprefix, e.path)
            self.log('Installing new directory {}'.format((full_dst_dir)))
            if os.path.isfile(full_dst_dir):
                print('Tried to create directory {} but a file of that name already exists.'.format((full_dst_dir)))
                sys.exit(1)
            dm.makedirs(full_dst_dir, exist_ok=True)
            self.set_mode(full_dst_dir, e.install_mode, d.install_umask)

    def install_headers(self, d , dm , destdir , fullprefix )  :
        for t in d.headers:
            if not self.should_install(t):
                continue
            fullfilename = t.path
            fname = os.path.basename(fullfilename)
            outdir = get_destdir_path(destdir, fullprefix, t.install_path)
            outfilename = os.path.join(outdir, fname)
            if self.do_copyfile(fullfilename, outfilename, makedirs=(dm, outdir)):
                self.did_install_something = True
            self.set_mode(outfilename, t.install_mode, d.install_umask)

    def run_install_script(self, d , destdir , fullprefix )  :
        env = {'MESON_SOURCE_ROOT': d.source_dir,
               'MESON_BUILD_ROOT': d.build_dir,
               'MESON_INSTALL_PREFIX': d.prefix,
               'MESON_INSTALL_DESTDIR_PREFIX': fullprefix,
               'MESONINTROSPECT': ' '.join([shlex.quote(x) for x in d.mesonintrospect]),
               }
        if self.options.quiet:
            env['MESON_INSTALL_QUIET'] = '1'

        for i in d.install_scripts:
            if not self.should_install(i):
                continue
            name = ' '.join(i.cmd_args)
            if i.skip_if_destdir and destdir:
                self.log('Skipping custom install script because DESTDIR is set {!r}'.format((name)))
                continue
            self.did_install_something = True  # Custom script must report itself if it does nothing.
            self.log('Running custom install script {!r}'.format((name)))
            try:
                rc = self.run_exe(i, env)
            except OSError:
                print('FAILED: install script \'{}\' could not be run, stopped'.format((name)))
                # POSIX shells return 127 when a command could not be found
                sys.exit(127)
            if rc != 0:
                print('FAILED: install script \'{}\' exit code {}, stopped'.format((name), (rc)))
                sys.exit(rc)

    def install_targets(self, d , dm , destdir , fullprefix )  :
        for t in d.targets:
            if not self.should_install(t):
                continue
            if not os.path.exists(t.fname):
                # For example, import libraries of shared modules are optional
                if t.optional:
                    self.log('File {!r} not found, skipping'.format((t.fname)))
                    continue
                else:
                    raise MesonException('File {!r} could not be found'.format((t.fname)))
            file_copied = False # not set when a directory is copied
            fname = check_for_stampfile(t.fname)
            outdir = get_destdir_path(destdir, fullprefix, t.outdir)
            outname = os.path.join(outdir, os.path.basename(fname))
            final_path = os.path.join(d.prefix, t.outdir, os.path.basename(fname))
            should_strip = t.strip or (t.can_strip and self.options.strip)
            install_rpath = t.install_rpath
            install_name_mappings = t.install_name_mappings
            install_mode = t.install_mode
            if not os.path.exists(fname):
                raise MesonException('File {!r} could not be found'.format((fname)))
            elif os.path.isfile(fname):
                file_copied = self.do_copyfile(fname, outname, makedirs=(dm, outdir))
                self.set_mode(outname, install_mode, d.install_umask)
                if should_strip and d.strip_bin is not None:
                    if fname.endswith('.jar'):
                        self.log('Not stripping jar target: {}'.format(os.path.basename(fname)))
                        continue
                    self.do_strip(d.strip_bin, fname, outname)
                if fname.endswith('.js'):
                    # Emscripten outputs js files and optionally a wasm file.
                    # If one was generated, install it as well.
                    wasm_source = os.path.splitext(fname)[0] + '.wasm'
                    if os.path.exists(wasm_source):
                        wasm_output = os.path.splitext(outname)[0] + '.wasm'
                        file_copied = self.do_copyfile(wasm_source, wasm_output)
            elif os.path.isdir(fname):
                fname = os.path.join(d.build_dir, fname.rstrip('/'))
                outname = os.path.join(outdir, os.path.basename(fname))
                dm.makedirs(outdir, exist_ok=True)
                self.do_copydir(d, fname, outname, None, install_mode, dm)
            else:
                raise RuntimeError('Unknown file type for {!r}'.format((fname)))
            if file_copied:
                self.did_install_something = True
                try:
                    self.fix_rpath(outname, t.rpath_dirs_to_remove, install_rpath, final_path,
                                   install_name_mappings, verbose=False)
                except SystemExit as e:
                    if isinstance(e.code, int) and e.code == 0:
                        pass
                    else:
                        raise

def rebuild_all(wd )  :
    if not (Path(wd) / 'build.ninja').is_file():
        print('Only ninja backend is supported to rebuild the project before installation.')
        return True

    ninja = environment.detect_ninja()
    if not ninja:
        print("Can't find ninja, can't rebuild test.")
        return False

    ret = subprocess.run(ninja + ['-C', wd]).returncode
    if ret != 0:
        print('Could not rebuild {}'.format((wd)))
        return False

    return True


def run(opts )  :
    datafilename = 'meson-private/install.dat'
    private_dir = os.path.dirname(datafilename)
    log_dir = os.path.join(private_dir, '../meson-logs')
    if not os.path.exists(os.path.join(opts.wd, datafilename)):
        sys.exit('Install data not found. Run this command in build directory root.')
    if not opts.no_rebuild:
        b = build.load(opts.wd)
        setup_vsenv(b.need_vsenv)
        if not rebuild_all(opts.wd):
            sys.exit(-1)
    os.chdir(opts.wd)
    with open(os.path.join(log_dir, 'install-log.txt'), 'w', encoding='utf-8') as lf:
        installer = Installer(opts, lf)
        append_to_log(lf, '# List of files installed by Meson')
        append_to_log(lf, '# Does not contain files installed by custom scripts.')
        if opts.profile:
            import cProfile as profile
            fname = os.path.join(private_dir, 'profile-installer.log')
            profile.runctx('installer.do_install(datafilename)', globals(), locals(), filename=fname)
        else:
            installer.do_install(datafilename)
    return 0
