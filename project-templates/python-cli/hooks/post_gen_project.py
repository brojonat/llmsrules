#!/usr/bin/env python
"""Post-generation hook to set executable permissions."""

import os
import stat

# Make simple.py executable
simple_script = "simple.py"
if os.path.exists(simple_script):
    st = os.stat(simple_script)
    os.chmod(simple_script, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
