from distutils.core import setup, Extension

spam_util_module = Extension ('slam_ext',
        libraries = ['isl', 'boost_python'],
        sources = ['ext_boost_wrapper.cpp', 'ext_screen_layout.cpp'])

setup (name = 'Slam',
        version = '0.1',
        description = 'Screen layout manager',
        py_modules = ['config', 'xclient'],
        ext_modules = [spam_util_module])

