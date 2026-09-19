qt6 = import('qt6')
qt6_dep = dependency('qt6', modules: ['Core', 'Gui', 'Widgets'])
test_inc = include_directories('../common', '../gui')

test_qt_sources = qt6.preprocess(
  moc_headers: ['../gui/shm_binder.h'],
  include_directories: test_inc,
  dependencies: qt6_dep,
)

binder_test = executable('binder_test',
  'binder_test.cpp',
  '../gui/shm_binder.cpp',
  test_qt_sources,
  include_directories: test_inc,
  dependencies: qt6_dep,
  link_args: [
    '-static-libstdc++', '-static-libgcc',
    '-pie', '-Wl,-z,nocopyreloc', '-Wl,-z,indirect-extern-access',
  ],
  install: false,
)

test('binder_test', binder_test,
  env: ['QT_QPA_PLATFORM=offscreen'],
)

helper_command_test = executable('helper_command_test',
  'helper_command_test.cpp',
  '../gui/mainwindow.cpp',
  '../gui/passdialog.cpp',
  '../gui/shm_binder.cpp',
  '../layer_linux/src/hotkey.cpp',
  '../common/runner_discovery.cpp',
  gui_qt_sources,
  include_directories: [test_inc, gui_inc],
  dependencies: qt6_dep,
  link_args: [
    '-static-libstdc++', '-static-libgcc',
    '-pie', '-Wl,-z,nocopyreloc', '-Wl,-z,indirect-extern-access',
  ],
  install: false,
)

test('helper_command_test', helper_command_test,
  env: ['QT_QPA_PLATFORM=offscreen'],
  timeout: 30,
)

test('bundled_runtime_test', find_program('bash'),
  args: [files('bundled_runtime_test.sh')],
  timeout: 30,
)

test('bundle_launcher_test', find_program('python3'),
  args: [files('../packaging/test_ubuntu_bundle.py')],
  timeout: 30,
)
