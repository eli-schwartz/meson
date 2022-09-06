# Copyright 2016 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import sys
import os
from compileall import compile_file

destdir = os.environ.get('DESTDIR')

def destdir_join(d1, d2):
    if not d1:
        return d2
    # c:\destdir + c:\prefix must produce c:\destdir\prefix
    parts = os.path.splitdrive(d2)
    return d1 + parts[1]

def compileall(files):
    for f in files:
        if destdir is not None:
            ddir = os.path.dirname(f)
            fullpath = destdir_join(destdir, f)
        else:
            ddir = None
            fullpath = f

        compile_file(fullpath, ddir, force=True)

def run(args):
    data_file = os.path.join(os.path.dirname(__file__), args[0])
    with open(data_file, 'rb') as f:
        dat = json.load(f)
    compileall(dat)

if __name__ == '__main__':
    run(sys.argv[1:])
