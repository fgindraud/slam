from distutils.core import setup, Extension

slam_util_module = Extension ("slam_ext",
        libraries = ["isl", "boost_python3"],
        sources = ["ext/boost_wrapper.cpp", "ext/screen_layout.cpp"])

setup (name = "Slam",
        version = "0.2",
        description = "Screen layout manager",
        py_modules = ["main", "util", "layout", "xcb_backend"],
        ext_modules = [slam_util_module])

