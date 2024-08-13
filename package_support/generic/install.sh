#!/usr/bin/env bash

# install.sh
# Install RCU's binary to the user's home folder and add an
# applications entry (XDG-compliant: FreeBSD and GNU/Linux).

# RCU is a management client for the reMarkable Tablet.
# Copyright (C) 2020  Davis Remmel
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see
# <https://www.gnu.org/licenses/>.

bindir="$HOME/.local/bin"
appdir="$HOME/.local/share/applications"

mkdir -p "$bindir"
mkdir -p "$appdir"

# Copy binary
echo -n "Copying RCU executable to $bindir/rcu..." && \
    cp rcu "$bindir"/ && \
    echo "done."

# Copy icon
echo -n "Copying RCU icon to $appdir/davisr-rcu.png..." && \
    cp davisr-rcu.png "$appdir"/ && \
    echo "done."

# Write desktop entry
echo -n "Writing RCU desktop entry..." && \
cat > "/tmp/davisr-rcu.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RCU
Comment=Manage your reMarkable tablet
Path=$bindir
Exec=$bindir/rcu
Icon=$appdir/davisr-rcu.png
Terminal=false
Categories=Utility;
Version=1.0
EOF
if [[ 0 == $? ]]
then
    xdg-desktop-menu install "/tmp/davisr-rcu.desktop" && \
	rm "/tmp/davisr-rcu.desktop" && \
	echo "done."
fi
