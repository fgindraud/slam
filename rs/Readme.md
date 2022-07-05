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

Semantics
---------

When the backend layout changes :
* If the layout is what was just requested to be set: do nothing (we see our own update).
* If the set of physical outputs is different from before (add / remove screen) :
    * If a database entry exists for this set of outputs, use the stored layout.
    * If no database entry, this is a new situation: create a layout enabling the new screen(s) with a default position.
* If same set of outputs, this is a change to software layout: store it unless it is _unsupported_ (overlapping / clone outputs, maybe check for CRTC transform, etc)

Thus with this set of semantics the stored layouts can be set by using any other tool to change the current layout : `xrandr`, `arandr`, GUIs.
The change from this external tool will be recognized as a _software_ change and be stored, eliminating the need to configure it from _SLAM_ itself.

What is stored :
* Mode of each output (size+frequency). Defaults to _preferred mode_ when autolayouting.
* Coordinates of each output in an abstract space : Screen in X11, windows seems to have the same model
* Rotation and reflection for each output.
* Primary output for X.

The EDID data may be absent due to video signal forwarding equiment like cheap KVMs often present in conference rooms.
In this case, instead of EDID, the layout will be stored by using the _output name_ (like `DP-0`).
This should be enough to disambiguate between two different monitors for what is useful to us : size for layouting.
Note that this require non EDID mode monitors to use the preferred mode !

Autolayouting:
TODO
Provide a manual tool to normalize a layout.
Used for creating new layouts ?

TODO:
* strategy for default layout:
    * old statistical thing ? required ISL as it just used the set of most used relations which maybe non-sensical together
    * find base with subset of screens and extend with statistical relation ?
    