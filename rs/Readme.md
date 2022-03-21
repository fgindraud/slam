SLAM - Screen Layout Automatic Manager
======================================

Daemon used to automatically remember multi screen layouts and restore them later.
Screen layouts are stored for each set of connected screens, identified by their [EDID](https://en.wikipedia.org/wiki/Extended_Display_Identification_Data).

WIP, converting from python/C++ to rust with changes:
- early stages of conversion: read layout from backend, etc...

Compiling and backends
----------------------

_SLAM_ is designed to work with multiple _backends_ to interact with the system.
These backends are defined as optional features of the crate.
Multiple backends could be compiled-in, in which case the first working one is used (but beware of the linking requirements !).
Supported backends :
* X backend using `xcb` : feature `xcb`. Dynamically linked to C xcb library.

Usage
-----

_SLAM_ has few options, a list is available with `-h`.
The database is a json file stored in the _XDG_ config directory if the path is left to the default setting.

Log messages are printed to stdout for simplicity.
The cleanest way to launch _SLAM_ is as a `systemd` user service dependent on the graphical session (TODO sample file).

---------------------------------

Semantics
---------

When the backend layout changes :
* If the current setting is _weird_ (overlapping / clone outputs, maybe check for CRTC transform, etc) : do nothing. Also called _manual layout mode_.
* If the layout is what was just requested to be set: do nothing (we see our own update).
* If the set of physical outputs is different from before (add / remove screen) :
    * If a database entry exists for this set of outputs, use the stored layout.
    * If no database entry, this is a new situation: create a layout enabling the new screen(s) with a default position.
* If same set of outputs, this is a change to software layout: analyze it, normalize to our layout model and store it.

Thus with this set of semantics the stored layouts can be set by using any other tool to change the current layout : `xrandr`, `arandr`, GUIs.
The change from this external tool will be recognized as a _software_ change and be stored, eliminating the need to configure it from _SLAM_ itself.

What is stored :
* Directional relations between outputs (`left-of`, etc).
* Rotation and reflection for each output.
* Mode of each output size+frequency), which must be from the list attached to the output. Defaults to _preferred mode_.
* Primary output for X.

The EDID data may be absent due to video signal forwarding equiment like cheap KVMs often present in conference rooms.
In this case the layout will be stored by using the _output name_ (like `DP-0`) instead of EDID.
The mode will not be stored (as it may not apply to other outputs plugged to this port) and the preferred mode used instead.
TODO target, check after impl if we actually used that.

TODO:
* strategy for default layout:
    * old statistical thing ? required ISL as it just used the set of most used relations which maybe non-sensical together
    * find base with subset of screens and extend with statistical relation ?
