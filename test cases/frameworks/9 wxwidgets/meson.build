project('wxwidgets test', 'cpp', default_options : ['cpp_std=c++11'])

# multiple calls to the same dependency should work
# https://github.com/mesonbuild/meson/issues/1937
wxd = dependency('wxwidgets', version : '>=5', required : false)
wxd = dependency('wxwidgets', version : '>=3.0.0', required : false)

if not wxd.found()
  error('MESON_SKIP_TEST: wxwidgets dependency not found')
endif

wp = executable('wxprog', 'wxprog.cpp', dependencies : wxd)

test('wxtest', wp)

# WxWidgets framework is available, we can use required here
wx_stc = dependency('wxwidgets', version : '>=3.0.0', modules : ['std', 'stc'])
stc_exe = executable('wxstc', 'wxstc.cpp', dependencies : wx_stc)
test('wxstctest', stc_exe)

# Check we can apply a version constraint
dependency('wxwidgets', version: '>=@0@'.format(wxd.version()))
