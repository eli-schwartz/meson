project('libgcrypt test', 'c')

libgcrypt_dep = dependency('libgcrypt', version : '>= 1.0', method: get_option('method'), required: false)
if not libgcrypt_dep.found()
    error('MESON_SKIP_TEST: libgcrypt not installed with method: ', get_option('method'))
endif
libgcrypt_ver = libgcrypt_dep.version()
assert(libgcrypt_ver.split('.').length() > 1, 'libgcrypt version is "@0@"'.format(libgcrypt_ver))
message('libgcrypt version is "@0@"'.format(libgcrypt_ver))
e = executable('libgcrypt_prog', 'libgcrypt_prog.c', dependencies : libgcrypt_dep)

test('libgcrypttest', e)

# Test using the method keyword:
dependency('libgcrypt', version: '>=@0@'.format(libgcrypt_dep.version()), method: get_option('method'))
