from distutils.core import setup, Extension

spam_util_module = Extension ('slam_util', libraries = ['isl'], sources = ['slam_util.c'])

setup (name = 'Slam',
        version = '0.1',
        description = 'Screen layout manager',
        py_modules = ['config', 'xclient'],
        ext_modules = [spam_util_module])

