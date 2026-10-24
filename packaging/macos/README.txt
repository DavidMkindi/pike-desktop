Pike for macOS
==============

Two install options are published for each release:

  Pike-<version>-macOS-<arch>.dmg
      Open the disk image and drag Pike into your Applications folder.

  Pike-<version>-macOS-<arch>.pkg
      Double-click to install Pike into /Applications.

The builds are ad-hoc signed but not notarised, so the first launch may be
blocked by Gatekeeper. To allow it:

  * Right-click (or Control-click) Pike.app and choose "Open", then confirm; or
  * Run:  xattr -dr com.apple.quarantine /Applications/Pike.app

Settings and chat history are stored in
~/Library/Application Support/Pike.
