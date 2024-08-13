# Makefile
# This is the makefile for reMarkable Connection Utility.
# 
# RCU is a management client for the reMarkable Tablet.
# Copyright (C) 2020-23  Davis Remmel
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

SHELL=bash
UNAME := $(shell uname)

# OS detection
# (Windows is only supported via Make-win.bat)
OSNAME=generic
ifeq ($(UNAME), FreeBSD)
	OSNAME=freebsd
else ifeq ($(UNAME), Linux)
	OSNAME := $(shell source /etc/os-release && echo $$ID$$VERSION_ID | cut -d. -f1)
else ifeq ($(UNAME), Darwin)
	OSNAME=macos
endif

# FreeBSD requires python3.9 because that's where the PySide2 port is.
# 
# macOS 10.13 requires python3.8 from Homebrew. macOS 12 already
# includes python3.10 as 'python3'.
# 
# Linux users may have a variety of pythons, so just test for the
# maximum version. Build dependencies, if any, are mentioned in the 
# specific packaging sections (further below).
ifeq ($(UNAME), FreeBSD)
	PYTHON=python3.9
else ifeq ($(UNAME), Darwin)
	PYTHON := $(shell basename $(shell which python3.8 || which python3 || echo "/usr/local/bin/python3.8"))
else
#	GNU/Linux, Generic
	PYTHON := $(shell basename $(shell bash -c "which python3.10 || which python3.9 || which python3.8 || which python3.7 || which python3.6"))
endif

# Grab the RCU version from the src/version.txt file
RCUFULLVER := $(shell cut -f2 src/version.txt)
RCUVER := $(shell cut -f2 src/version.txt | tr -d '(' | tr -d ')')
RCUVERFLAG := $(shell cut -f2 src/version.txt | head -c 1)

all: dist/RCU

FORCE:

build:
	mkdir -p "$@"

dist:
	mkdir -p "$@"


##############################
###  Build: Documentation  ###
########################################################################
.PHONY: doc
doc: manual/manual.pdf
manualdeps := $(shell ls manual/*-*.tex)
manual/manual.pdf: $(manualdeps)
	cat $(manualdeps) \
		| sed 's/%%RCUFULLVER%%/${RCUFULLVER}/g' \
		> manual/manual.tex
	(cd manual && pdflatex -shell-escape manual.tex && pdflatex -shell-escape manual.tex)


############################
###  Build: Python venv  ###
########################################################################
venv:
ifeq ($(UNAME), FreeBSD)
	${PYTHON} -m venv --system-site-packages venv
	. venv/bin/activate; \
	pip install --upgrade pip; \
	pip install --ignore-installed -r src/requirements.txt; \
	pip install -r src/requirements2-freebsd.txt
#	Don't use system site packages anywhere else--weird conflicts
#	may occur.
else ifeq ($(UNAME), Darwin)
	${PYTHON} -m venv venv
	. venv/bin/activate; \
	pip install --upgrade pip; \
	pip install -r src/requirements.txt; \
	pip install -r src/requirements2-macos.txt
else
	(${PYTHON} -m venv venv || ${PYTHON} -m venv venv --without-pip)
	. venv/bin/activate; \
	pip install --upgrade pip; \
	pip install -r src/requirements.txt; \
	pip install -r src/requirements2.txt
endif

.PHONY: clean-venv
clean-venv:
	rm -rf venv


######################
###  Build: Icons  ###
########################################################################
icons/windows-icon.ico: build
	convert \
		"icons/16x16/rcu-icon-16x16.png" \
		"icons/24x24/rcu-icon-24x24.png" \
		"icons/32x32/rcu-icon-32x32.png" \
		"icons/48x48/rcu-icon-48x48.png" \
		"icons/64x64/rcu-icon-64x64.png" \
		"icons/128x128/rcu-icon-128x128.png" \
		"icons/256x256/rcu-icon-256x256.png" \
		-colors 256 "$@"


#################################
###  Build: Main Application  ###
########################################################################
dist/RCU: venv FORCE
ifeq ($(UNAME), FreeBSD)
	. venv/bin/activate; \
	pyinstaller --hiddenimport PySide2.QtXml \
		--add-data "/usr/local/lib/qt5/plugins/platforms/libqxcb.so:PySide2/plugins/platforms" \
		--add-data "./src/views:views" \
		--add-data "./src/panes:panes" \
		--add-data "./src/model/pens/pencil_textures_linear:model/pens/pencil_textures_linear" \
		--add-data "./src/model/pens/pencil_textures_log:model/pens/pencil_textures_log" \
		--add-data "./src/model/pens/paintbrush_textures_log:model/pens/paintbrush_textures_log" \
		--add-data "./src/licenses:licenses" \
		--add-data "./src/version.txt:." \
		--add-data "./recovery_os_build:recovery_os_build" \
		--add-data "./icons:icons" \
		--copy-metadata pikepdf \
		--onefile \
		--name RCU \
		--console \
		src/main.py; \
	deactivate
endif
ifeq ($(UNAME), Linux)
	. venv/bin/activate; \
	pyinstaller \
		--hiddenimport PySide2.QtXml \
		--hiddenimport charset_normalizer.md__mypyc \
		--add-data "./src/views:views" \
		--add-data "./src/panes:panes" \
		--add-data "./src/model/pens/pencil_textures_linear:model/pens/pencil_textures_linear" \
		--add-data "./src/model/pens/pencil_textures_log:model/pens/pencil_textures_log" \
		--add-data "./src/model/pens/paintbrush_textures_log:model/pens/paintbrush_textures_log" \
		--add-data "./src/licenses:licenses" \
		--add-data "./src/version.txt:." \
		--add-data "./recovery_os_build:recovery_os_build" \
		--add-data "./icons:icons" \
		--copy-metadata pikepdf \
		--onefile \
		--name RCU \
		--console \
		src/main.py; \
	deactivate
endif
ifeq ($(UNAME), Darwin)
	. venv/bin/activate; \
	pyinstaller --hiddenimport PySide2.QtXml \
		--add-data "../gs/lib/libgs.dylib:lib/." \
		--add-data "./src/views:views" \
		--add-data "./src/panes:panes" \
		--add-data "./src/model/pens/pencil_textures_linear:model/pens/pencil_textures_linear" \
		--add-data "./src/model/pens/pencil_textures_log:model/pens/pencil_textures_log" \
		--add-data "./src/model/pens/paintbrush_textures_log:model/pens/paintbrush_textures_log" \
		--add-data "./src/licenses:licenses" \
		--add-data "./src/version.txt:." \
		--add-data "./recovery_os_build:recovery_os_build" \
		--add-data "./icons:icons" \
		--copy-metadata pikepdf \
		--osx-bundle-identifier "me.davisr.rcu" \
		--name RCU \
		--windowed \
		--icon "./icons/mac-icon.icns" \
		src/main.py; \
	deactivate
endif


###############################
###  Run: Main Application  ###
########################################################################
.PHONY: run
run: venv
	. venv/bin/activate; \
	(cd src && ${PYTHON} -B main.py)


###################
###  Packaging  ###
########################################################################
.PHONY: package
package: dist/rcu-${RCUVER}-${OSNAME}.tar.gz

PKG_EXCLUDE=--exclude=.git --exclude=build --exclude=dist --exclude=venv --exclude=recovery_os


#################################
###  Package: Remote Generic  ###
#######################################################################
# This is used for all remote Unix-like operating systems.
define remote-generic-package =
	ssh rcu-proxmox 'sudo /build-scripts/rcu-build-$1-up.sh'
	sleep 30
	ssh rcu-build-$1 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-$1 'mkdir -p $$HOME/Downloads/rcu' && \
	tar ${PKG_EXCLUDE} -cf - * \
		| ssh rcu-build-$1 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-$1 'cd $$HOME/Downloads/rcu && (gmake package || make package)' && \
	scp rcu-build-$1:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-$1*.tar.gz' dist/
	ssh rcu-proxmox 'sudo /build-scripts/rcu-build-$1-down.sh'
endef


######################################
###  Package: GNU/Linux (generic)  ###
########################################################################
# This depends upon being BEFORE any targets with a static $OSNAME, like
# 'macos' and 'windows', which have special packaging requiremnets that
# override this recipe.
dist/rcu-${RCUVER}-${OSNAME}.tar.gz: doc dist dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-${OSNAME}"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-${OSNAME}/User Manual.pdf"
	cp "dist/RCU" "dist/rcu-${RCUVER}-${OSNAME}/rcu"
	cp package_support/gnulinux/* dist/rcu-${RCUVER}-${OSNAME}/
	cp package_support/generic/* dist/rcu-${RCUVER}-${OSNAME}/
	cp icons/mac-icon.iconset/icon_512x512.png dist/rcu-${RCUVER}-${OSNAME}/davisr-rcu.png
	cp -r 'icons/mac-icon.iconset/' 'dist/rcu-${RCUVER}-${OSNAME}/Extra Icons'
	chmod +x dist/rcu-${RCUVER}-${OSNAME}/*.sh
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-${OSNAME}"

.PHONY: remote-ubuntu22-package
# needs packages: make binutils python3.10-venv libxcb-xinerama0
remote-ubuntu22-package: doc dist
	$(call remote-generic-package,ubuntu22)

.PHONY: remote-ubuntu20-package
# needs packages: make binutils python3.8-venv libxcb-xinerama0
remote-ubuntu20-package: doc dist
	$(call remote-generic-package,ubuntu20)

.PHONY: remote-fedora-package
# needs packages: make binutils python3.8 python3-pyside2
remote-fedora-package: doc dist
	$(call remote-generic-package,fedora)

.PHONY: remote-debian-package
# needs to have python3.10 installed manually. run as root:
# 
# apt install wget build-essential libreadline-dev libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev zlib1g-dev
# wget https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz
# tar xf Python-3.10.14.tgz
# cd Python-3.10.14
# ./configure --enable-optimizations --enable-shared
# make -j4 && make altinstall
# 
# also needs packages: libxcb-xinerama0
remote-debian-package: doc dist
	$(call remote-generic-package,debian)

.PHONY: remote-opensuse-package
# needs packages: make
remote-opensuse-package: doc dist
	$(call remote-generic-package,opensuse)

.PHONY: remote-rhel7-package
# needs packages: python3
remote-rhel7-package: doc dist
	$(call remote-generic-package,rhel7)

.PHONY: remote-freebsd-package
# needs packages: gmake bash rust qpdf py39-pyside2
remote-freebsd-package: doc dist
	$(call remote-generic-package,freebsd)


###########################
###  Package: macOS 11  ###
########################################################################
dist/rcu-${RCUVER}-macos.tar.gz: doc dist dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-macos"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-macos/User Manual.pdf"
	cp -a "dist/RCU.app" "dist/rcu-${RCUVER}-macos/RCU.app"
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-macos"

.PHONY: remote-macos-package
remote-macos-package: doc dist
	$(call remote-generic-package,macos)


#############################
###  Package: Windows 10  ###
########################################################################
# Remote-only package for Windows (use Make-win.bat for local packaging)
.PHONY: remote-windows-package
remote-windows-package: build dist doc package-source
	ssh rcu-proxmox 'sudo /build-scripts/rcu-build-windows-up.sh'
	sleep 30
	- ssh rcu-build-windows 'rmdir /S /Q Downloads\rcu'
# Use remote packaging
	ssh rcu-build-windows 'mkdir Downloads\rcu'
	scp dist/rcu-${RCUVER}-source.tar.gz rcu-build-windows:'Downloads'
	ssh rcu-build-windows 'cd Downloads && tar -xf rcu-${RCUVER}-source.tar.gz'
	ssh rcu-build-windows 'cd Downloads\rcu && Make-win.bat windowed'
	ssh rcu-build-windows 'cd Downloads\rcu && Make-win.bat console'
	mkdir "dist/rcu-${RCUVER}-windows"
	scp rcu-build-windows:'Downloads/rcu/dist/RCU.exe' dist/rcu-${RCUVER}-windows/
	scp rcu-build-windows:'Downloads/rcu/dist/RCU-CLI.exe' dist/rcu-${RCUVER}-windows/
	cp 'manual/manual.pdf' 'dist/rcu-${RCUVER}-windows/User Manual.pdf'
	cp package_support/windows/* dist/rcu-${RCUVER}-windows/
	cp -r 'icons/mac-icon.iconset/' 'dist/rcu-${RCUVER}-windows/Extra Icons'
	ssh rcu-proxmox 'sudo /build-scripts/rcu-build-windows-down.sh'
	(cd dist && zip -r rcu-${RCUVER}-windows.zip rcu-${RCUVER}-windows)
	rm -rf dist/rcu-${RCUVER}-windows


#################
###  Sources  ###
########################################################################
.PHONY: package-source
package-source: dist/rcu-${RCUVER}-source.tar.gz
dist/rcu-${RCUVER}-source.tar.gz: dist clean-build clean-python stage-doc
	tar ${PKG_EXCLUDE} -zcf "$@" -C ../ rcu

# The recovery OS contains Linux, U-Boot, and rootfs. It is very large
# (hundreds of megabytes) and packaged seperately from the regular RCU
# application source.
.PHONY: package-source-ros
package-source-ros: dist/rcu-${RCUVER}-ros-source.tar.gz
dist/rcu-${RCUVER}-ros-source.tar.gz: dist
	tar --exclude=.git -zcf "$@" -C ../ rcu/recovery_os


########################
###  Release Bundle  ###
########################################################################
.PHONY: release
release: remote-macos-package remote-windows-package remote-ubuntu22-package remote-ubuntu20-package remote-fedora-package remote-opensuse-package remote-rhel7-package remote-freebsd-package remote-debian-package package-source package-source-ros dist/SHA256

dist/SHA256: dist
	(cd dist && sha256sum * > SHA256)

.PHONY: release-signature
release-signature: dist/SHA256.asc
dist/SHA256.asc: dist/SHA256
	(gpg --detach-sign --armor $<)


#################
###  Cleanup  ###
########################################################################
.PHONY: clean
clean: clean-build clean-dist clean-python clean-doc

.PHONY: clean-build
clean-build:
	rm -rf "build"

.PHONY: clean-dist
clean-dist:
	rm -rf "dist"

.PHONY: clean-doc
clean-doc:
	- find manual -name "*.aux" -o -name "*.log" -o -name "*.out" -o -name "*.toc" -o -name "manual.tex" -o -name "manual.pdf" -o -name "_minted-manual" | xargs rm -rf

# stage-doc is like clean-doc, but leaves the manual.pdf and will auto-build
.PHONY: stage-doc
stage-doc: doc
	- find manual -name "*.aux" -o -name "*.log" -o -name "*.out" -o -name "*.toc" -o -name "manual.tex" -o -name "_minted-manual" | xargs rm -rf

.PHONY: clean-python
clean-python:
	- find . -type f -name "*.core" -exec rm -f {} \;
	- find . -type d -name venv -prune -o -name "__pycache__" -exec rm -rf {} \;
	rm -rf *.spec
