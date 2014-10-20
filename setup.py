from distutils.core import setup, Extension

spam_util_module = Extension ('slam_ext',
        libraries = ['isl', 'boost_python'],
        sources = ['ext/boost_wrapper.cpp', 'ext/screen_layout.cpp'])

setup (name = 'Slam',
        version = '0.1',
        description = 'Screen layout manager',
        py_modules = ['main', 'layout', 'xcb_backend'],
        ext_modules = [spam_util_module])

