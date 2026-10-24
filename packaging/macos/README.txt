Pike - macOS build
==================

Drag Pike.app into your Applications folder, then open it.

The build is ad-hoc signed but not notarised, so the first launch may be
blocked by Gatekeeper. To allow it:

  * Right-click (or Control-click) Pike.app and choose "Open", then confirm; or
  * Run:  xattr -dr com.apple.quarantine /Applications/Pike.app

Settings and chat history are stored in
~/Library/Application Support/Pike.
