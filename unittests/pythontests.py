# Copyright 2016-2021 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import glob
import os
import unittest
import pathlib
import subprocess

from run_tests import (
    Backend
)

from .allplatformstests import git_init

from .baseplatformtests import BasePlatformTests
from mesonbuild.mesonlib import TemporaryDirectoryWinProof

class PythonTests(BasePlatformTests):
    '''
    Tests that verify compilation of python extension modules
    '''

    def test_bad_versions(self):
        if self.backend is not Backend.ninja:
            raise unittest.SkipTest(f'Skipping python tests with {self.backend.name} backend')

        testdir = os.path.join(self.src_root, 'test cases', 'python', '8 different python versions')

        # The test is configured to error out with MESON_SKIP_TEST
        # in case it could not find python
        with self.assertRaises(unittest.SkipTest):
            self.init(testdir, extra_args=['-Dpython=not-python'])
        self.wipe()

        # While dir is an external command on both Windows and Linux,
        # it certainly isn't python
        with self.assertRaises(unittest.SkipTest):
            self.init(testdir, extra_args=['-Dpython=dir'])
        self.wipe()

    def test_dist(self):
        with TemporaryDirectoryWinProof() as dirstr:
            dirobj = pathlib.Path(dirstr)
            mesonfile = dirobj / 'meson.build'
            mesonfile.write_text('''project('test', 'c', version: '1')
pymod = import('python')
python = pymod.find_installation('python3', required: true)
''', encoding='utf-8')
            git_init(dirstr)
            self.init(dirstr)
            subprocess.check_call(self.meson_command + ['dist', '-C', self.builddir], stdout=subprocess.DEVNULL)

    def test_bytecompile(self):
        testdir = os.path.join(self.src_root, 'test cases', 'python', '2 extmodule')

        self.init(testdir, extra_args=['-Dpython2=enabled', '-Dpython.bytecompile=1'])
        self.build()
        self.install()

        count = 0
        for root, dirs, files in os.walk(self.installdir):
            for file in files:
                realfile = os.path.join(root, file)
                if file.endswith('.py'):
                    cached = glob.glob(realfile+'?') + glob.glob(os.path.join(root, '__pycache__', os.path.splitext(file)[0] + '*.pyc'))
                    self.assertEqual(len(cached), 2)
                    count += 1
        # there are 5 files x 2 installations
        self.assertEqual(count, 10)
