
if get_option('style') == 'posix'
  foreach n: ['', '2', '3', '4', '5', '6']
    install_data(
      'test.desktop.in',
      rename: 'test@0@.desktop'.format(n),
      install_dir: installdir
    )
  endforeach
else
  # Use filename substitution
  i18n.merge_file(
    input: 'test.desktop.in',
    output: '@BASENAME@',
    type: 'desktop',
    po_dir: '../po',
    data_dirs: '../po',
    install: true,
    install_dir: installdir,
  )

  # Use filename substitution for another file
  i18n.merge_file(
    input: files('test2.desktop.in'),
    output: '@BASENAME@',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: installdir,
  )

  i18n.merge_file(
    input: 'test.desktop.in',
    output: 'test3.desktop',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: installdir,
  )

  # Regression test when passing File object as input and '@BASENAME@' as output
  # in multiple i18n.merge_file() calls. It used to make target name collision.
  # https://github.com/mesonbuild/meson/issues/9022
  i18n.merge_file(
    input: configure_file(
      input: 'test5.desktop.in.in',
      output: '@BASENAME@',
      configuration: { 'NAME': 'Application' },
    ),
    output: '@BASENAME@',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: installdir,
  )
  i18n.merge_file(
    input: configure_file(
      input: 'test6.desktop.in.in',
      output: '@BASENAME@',
      configuration: { 'NAME': 'Application' },
    ),
    output: '@BASENAME@',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: installdir,
  )

  subdir('data3')
endif
