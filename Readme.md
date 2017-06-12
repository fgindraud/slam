SLAM - Screen Layout Automatic Manager
======================================

Python daemon that listens to Xcb Randr events, and manages screen layouts.
It stores layout for each set of connected screens (using EDID to differentiate different screens on same output).
It can restore old layouts when you plug the same screens as before.
It also updates its layout database when you manually change the layout, using 'xrandr' or a graphical tool.

Usage
-----

The daemon is available as a python library.
To launch it, you need to create a python file importing the library, and start this python file as the daemon:

    import slam
    slam.start(<options>)

An example file is available at `examples/slam` with a description of possible parameters.
You should probably not use this for more than 3 screens (exponential algorithm for position computation)

Todo
----

* more resistant to stupid hardware
	* statistical layout if not Edid
* Move away from superexponential ISL craziness (use tree and lockpoints)
* dbus interface :
	* backlight change
	* force normalize of manual state
	* get state info
	* force backend reload (interface for hotplug events)
* Plugin system to make additionnal actions when change of layout :
	* Background
	* i3 configure by screens ?
* Force reload of state in X when udev hotplug event ?

Install
-------

Requires:
* python >= 3.4
* ISL library
* Boost::Python
* xcffib python Xcb binding

Use standard distutils (--user will place it in a user local directory):

    python setup.py install [--user]

