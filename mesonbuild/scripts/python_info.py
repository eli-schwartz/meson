#!/usr/bin/env python

# ignore all lints for this file, since it is run by python2 as well

# type: ignore
# pylint: disable=deprecated-module

import sys

# do not inject mesonbuild.scripts
# python -P would work too, but is exclusive to >=3.11
if sys.path[0].endswith('scripts'):
    del sys.path[0]

import json, os, sysconfig

def get_distutils_paths(scheme=None, prefix=None):
    import distutils.dist
    distribution = distutils.dist.Distribution()
    install_cmd = distribution.get_command_obj('install')
    if prefix is not None:
        install_cmd.prefix = prefix
    if scheme:
        install_cmd.select_scheme(scheme)
    install_cmd.finalize_options()
    return {
        'data': install_cmd.install_data,
        'include': os.path.dirname(install_cmd.install_headers),
        'platlib': install_cmd.install_platlib,
        'purelib': install_cmd.install_purelib,
        'scripts': install_cmd.install_scripts,
    }

# On Debian derivatives, the Python interpreter shipped by the distribution uses
# a custom install scheme, deb_system, for the system install, and changes the
# default scheme to a custom one pointing to /usr/local and replacing
# site-packages with dist-packages.
# See https://github.com/mesonbuild/meson/issues/8739.
#
# We should be using sysconfig, but before 3.10.3, Debian only patches distutils.
# So we may end up falling back.

def get_install_paths():
    if sys.version_info >= (3, 10):
        scheme = sysconfig.get_default_scheme()
    else:
        scheme = sysconfig._get_default_scheme()

    if sys.version_info >= (3, 10, 3):
        if 'deb_system' in sysconfig.get_scheme_names():
            scheme = 'deb_system'
    else:
        import distutils.command.install
        if 'deb_system' in distutils.command.install.INSTALL_SCHEMES:
            paths = get_distutils_paths(scheme='deb_system')
            install_paths = get_distutils_paths(scheme='deb_system', prefix='')
            return paths, install_paths

    paths = sysconfig.get_paths(scheme=scheme)
    empty_vars = {'base': '', 'platbase': '', 'installed_base': ''}
    install_paths = sysconfig.get_paths(scheme=scheme, vars=empty_vars)
    return paths, install_paths

paths, install_paths = get_install_paths()

def links_against_libpython():
    from distutils.core import Distribution, Extension
    cmd = Distribution().get_command_obj('build_ext')
    cmd.ensure_finalized()
    return bool(cmd.get_libraries(Extension('dummy', [])))

variables = sysconfig.get_config_vars()
variables.update({'base_prefix': getattr(sys, 'base_prefix', sys.prefix)})

is_pypy = '__pypy__' in sys.builtin_module_names

if sys.version_info < (3, 0):
    suffix = variables.get('SO')
elif sys.version_info < (3, 8, 7):
    # https://bugs.python.org/issue?@action=redirect&bpo=39825
    from distutils.sysconfig import get_config_var
    suffix = get_config_var('EXT_SUFFIX')
else:
    suffix = variables.get('EXT_SUFFIX')

print(json.dumps({
  'variables': variables,
  'paths': paths,
  'sysconfig_paths': sysconfig.get_paths(),
  'install_paths': install_paths,
  'version': sysconfig.get_python_version(),
  'platform': sysconfig.get_platform(),
  'is_pypy': is_pypy,
  'is_venv': sys.prefix != variables['base_prefix'],
  'link_libpython': links_against_libpython(),
  'suffix': suffix,
}))
