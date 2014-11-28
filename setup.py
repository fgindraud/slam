# Copyright (c) 2013-2015 Francois GINDRAUD
# 
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from distutils.core import setup, Extension


setup (
        # Base info
        name = "slam",
        version = "0.4.1",

        # Code content
        packages = ["slam"],
        ext_modules = [
            Extension ("slam.ext",
                libraries = ["isl", "boost_python3"],
                sources = ["ext/boost_wrapper.cpp", "ext/screen_layout.cpp"])
            ],

        # Metadata
        description = "Screen layout manager",
        url = "https://github.com/lereldarion/slam",

        author = "François GINDRAUD",
        author_email = "francois.gindraud@gmail.com",
        
        license = "MIT",

        # Classification
        classifiers = [
            "Development Status :: 3 - Alpha",
            "Environment :: No Input/Output (Daemon)",
            "Intended Audience :: End Users/Desktop",
            "License :: OSI Approved :: MIT License",
            "Operating System :: Unix",
            "Programming Language :: Python :: 3",
            "Topic :: Desktop Environment",
            "Topic :: Desktop Environment :: Window Managers"
            ]
        )

