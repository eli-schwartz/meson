if get_option('style') == 'posix'
  install_data('test.desktop.in', rename: 'test.plugin', install_dir: installdir)
else
  i18n.merge_file(
    input: 'test.desktop.in',
    output: 'test.plugin',
    type: 'desktop',
    po_dir: '../po',
    data_dirs: '../po',
    args: ['--keyword=Description'],
    install: true,
    install_dir: installdir,
  )
endif
