#!/usr/bin/env bash

# uninstall.sh
# Uninstall RCU's binary from the user's home folder and
# remove the applications entry.

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

# Delete binary
echo -n "Deleting RCU executable from $bindir/rcu..." && \
    rm -f "$bindir/rcu" && \
    echo "done."

# Delete icon
echo -n "Deleting RCU icon from $appdir/davisr-rcu.png..." && \
    rm -f "$appdir/davisr-rcu.png" && \
    echo "done."

# Delete desktop entry
echo -n "Deleting RCU desktop entry..." && \
    xdg-desktop-menu uninstall davisr-rcu.desktop && \
    echo "done."
