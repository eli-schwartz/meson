install_data(
    'com.mesonbuild.install.policy',
    install_dir: get_option('datadir') / 'polkit-1/actions'
)

install_subdir(
    'syntax-highlighting/vim',
    install_dir: get_option('datadir') / 'vim/vimfiles',
    exclude_files: 'README',
    strip_directory: true,
)

bashcomp = dependency('bash-completion', required: false)
if bashcomp.found()
    bashcomp_dir = bashcomp.get_variable('completionsdir')
else
    bashcomp_dir = get_option('datadir') / 'bash-completion/completions'
endif
install_data('shell-completions/bash/meson', install_dir: bashcomp_dir)


install_data(
    'shell-completions/zsh/_meson',
    install_dir: get_option('datadir') / 'zsh/site-functions/'
)
