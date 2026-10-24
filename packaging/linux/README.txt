Pike for Linux
==============

Two install options are published for each release:

  Pike-<version>-Linux-amd64.deb
      Debian / Ubuntu installer. Install with:

          sudo apt install ./Pike-<version>-Linux-amd64.deb

      This adds Pike to your application menu and creates a `pike` command.
      Remove it later with:  sudo apt remove pike

  Pike-<version>-Linux-x86_64.AppImage
      Portable single-file executable. Make it executable and run it:

          chmod +x Pike-<version>-Linux-x86_64.AppImage
          ./Pike-<version>-Linux-x86_64.AppImage

      If AppImages do not start on your distribution, install FUSE 2
      (`libfuse2`) or run it with:  --appimage-extract-and-run

Both bundles contain Python, the Flask backend and the Qt WebEngine runtime,
so no extra packages are required on a normal 64-bit desktop.

Settings and chat history are stored in ~/.local/share/pike.
