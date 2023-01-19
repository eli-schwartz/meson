project('bar', 'c', license: 'Apache-2.0', license_files: 'LICENSE')

executable('bar', 'bar.c')

license = meson.project_license()[0]
if license != 'Apache-2.0'
    error('The license should be Apache-2.0, but it is: ' + license)
endif
#subproject('fibber')

#meson.install_dependency_manifest('/usr/share/licenses/bar/depmf.json')
