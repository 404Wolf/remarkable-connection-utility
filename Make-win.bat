:: Make-win.bat
:: This is the Windows makefile for reMarkable Connection Utility.
::
:: RCU is a management client for the reMarkable Tablet.
:: Copyright (C) 2020-23  Davis Remmel
:: 
:: This program is free software: you can redistribute it and/or modify
:: it under the terms of the GNU Affero General Public License as
:: published by the Free Software Foundation, either version 3 of the
:: License, or (at your option) any later version.
:: 
:: This program is distributed in the hope that it will be useful,
:: but WITHOUT ANY WARRANTY; without even the implied warranty of
:: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
:: GNU Affero General Public License for more details.
:: 
:: You should have received a copy of the GNU Affero General Public License
:: along with this program.  If not, see <https://www.gnu.org/licenses/>.
:: 
:: Usage:
::   `Make-win.bat {windowed|console|package}`
:: 
:: Build server notes:
::   * Windows 10 22H2
::   * Install Python 3.9 from Windows Store
::   * Install MS VCpp 14 or greater
::     * https://visualstudio.microsoft.com/visual-cpp-build-tools/
::     * select Desktop Development with C++, Install, should be about 8 gigs or so
::   * needs a couple of reboots...
::   * Install Ghostscript 10.01.2 to C:\Program Files\gs\gs10.01.2\.
::     * https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10012/gs10012w64.exe)
::   * disable virus threat protection settings
::     * Start > Settings > Update & Security > Windows Security > Virus & threat protection
::     * turn off Real Time Protection, turn off Cloud Delivered Protection

set exename=RCU
set exeflag=windowed

if %1==console (
   set exename=RCU-CLI
   set exeflag=console
)

:: if %1==package (
::    FOR /F "tokens=2 delims=	" %%G IN (src/version.txt) DO (
::       set "rcuver=!!G"
::    )
::    set "packagedir=dist/rcu-%rcuver%-windows"
::    ::Make-win.bat windowed
::    ::Make-win.bat console
::    :: other stuff
::    mkdir "%packagedir%"
::    copy "dist\RCU.exe" "%packagedir%"
::    copy "dist\RCU-CLI.exe" "%packagedir%"
::    copy "manual\manual.pdf" "%packagedir%\User Manual.pdf"
::    copy "package_support\windows" "%packagedir%"
::    mkdir "%packagedir%\Extra Icons"
::    copy "icons\mac-icon.iconset" "%packagedir%\Extra Icons"
::    tar -acf "dist\%packagedir%.zip" "%packagedir%"
:: )

if NOT %1==package (
   if not exist ..\venv (
       python -m venv ..\venv
       call ..\venv\Scripts\activate.bat
       python.exe -m pip install --upgrade pip
       pip install -r src\requirements.txt
       pip install -r src\requirements2.txt
   ) else (
       call ..\venv\Scripts\activate.bat
   )
   
   pyinstaller --hiddenimport PySide2.QtXml ^
   	--copy-metadata pikepdf ^
	--add-data "\Program Files\gs\gs10.01.2\bin\gsdll64.dll;." ^
   	--add-data ".\src\views;views" ^
   	--add-data ".\src\panes;panes" ^
   	--add-data ".\src\model\pens\pencil_textures_linear;model\pens\pencil_textures_linear" ^
   	--add-data ".\src\model\pens\pencil_textures_log;model\pens\pencil_textures_log" ^
   	--add-data ".\src\model\pens\paintbrush_textures_log;model\pens\paintbrush_textures_log" ^
   	--add-data ".\src\licenses;licenses" ^
   	--add-data ".\src\version.txt;." ^
   	--add-data ".\recovery_os_build;recovery_os_build" ^
   	--add-data ".\icons;icons" ^
   	--icon ".\icons\windows-icon.ico" ^
   	--name %exename% ^
   	--%exeflag% ^
   	--onefile ^
   	src\main.py
)

