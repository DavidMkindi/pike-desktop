Pike - Linux build
==================

Run the app:

    ./Pike

The bundled binary already contains Python, the Flask backend and the Qt
WebEngine runtime, so no extra packages are required on a normal desktop.

Optional: install it for the current user so it appears in your application
menu:

    ./install.sh

That copies the binary to ~/.local/bin/pike and adds a launcher entry to
~/.local/share/applications.

Requires a 64-bit Linux desktop with a working X11/Wayland session and OpenGL
(libGL). If the window does not open, try the browser fallback:

    ./Pike --browser

Settings and chat history are stored in ~/.local/share/pike.
