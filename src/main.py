'''
main.py
This is the master run file for reMarkable Connection Utility.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-23  Davis Remmel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

# Compensate for Windows' shortcomings
import sys
import io
use_faulthandler = True
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()
    use_faulthandler = False

# Provide tracebacks in case of crash
if use_faulthandler:
    import faulthandler
    faulthandler.enable(all_threads=True)


import platform
import os
if 'Darwin' == platform.system():
    # Fixes a problem where the main window wouldn't show past the
    # Connection Dialog in macOS 11 (the application appears to stall).
    os.environ['QT_MAC_WANTS_LAYER'] = '1'
    # Fixes a problem reading some PDF files, which are tried to be
    # decoded with 'ascii' instead of 'utf-8' when running as a binary
    # (this could have instead be fixed in the open() calls in
    # document.py, but since RCU is English-only this way may not be
    # problematic).
    os.environ['LANG'] = 'en_US.UTF-8'
if 'Windows' == platform.system():
    # Value of '1' means to infer dark mode (title bar) from system
    # theme.
    # https://www.qt.io/blog/dark-mode-on-windows-11-with-qt-6.5
    os.environ['QT_QPA_PLATFORM'] = 'windows:darkmode=1'

# Give these to all our children
global worker
import worker
global log
import log
global svgtools
import svgtools as svgtools

import model
from controllers import MainUtilityController
from panes import paneslist
from model.docrender import DocRenderPrefs



from pathlib import Path
import sys
from PySide2.QtWidgets import QApplication, QStyleFactory
from PySide2.QtCore import QCoreApplication, Qt, QThreadPool, QSettings
from PySide2.QtGui import QFont, QPalette, QColor, QIcon, QPixmap


# Handle Ctrl-C
import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)

# Standard command line arguments
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-v', '--version',
                    help='print version number and exit',
                    action='store_true')
parser.add_argument('--autoconnect',
                    help='immediately connect to the last-used preset',
                    action='store_true')
parser.add_argument('--dark',
                    help='force dark theme',
                    action='store_true')
parser.add_argument('--no-check-compat',
                    help='skip pane compatibility checks (load anyway)',
                    action='store_true')
parser.add_argument('--no-check-reclaim-storage',
                    help='skip check for deleted documents',
                    action='store_true')
parser.add_argument('--cli',
                    help='run headless (best used with --autoconnect)',
                    action='store_true')
parser.add_argument('--purge-settings',
                    help='delete all saved settings from PC (no confirm)',
                    action='store_true')
# parser.add_argument('--purge-data',
#                     help='delete all saved data/backups from PC (no confirm)',
#                     action='store_true')

# The DocRenderPrefs have a large amount of CLI arguments. It manages
# these itself as to not clog up this file.
DocRenderPrefs.add_cli_args_to_parser(parser)
# Load CLI arguments for each of the available panes.
group = parser.add_mutually_exclusive_group()
for pane in paneslist:
    for arg in pane.cli_args:
        if arg[1] is True:
            group.add_argument(arg[0],
                                help=arg[3],
                                action='store_true')
        else:
            group.add_argument(arg[0],
                                nargs=arg[1],
                                metavar=arg[2],
                                help=arg[3])
# Rendering RMN to PDF will not load the rest of the program and may be
# used alone.
group.add_argument('--render-rmn-pdf-b',
                   nargs=2,
                   metavar=('in.rmn', 'out.pdf'),
                   help='render local RMN archive to PDF (bitmap)')
group.add_argument('--render-rmn-pdf-v',
                   nargs=2,
                   metavar=('in.rmn', 'out.pdf'),
                   help='render local RMN archive to PDF (vector)')

args = parser.parse_args()
if args.cli:
    log.activated = False

# Start main application
if __name__ == '__main__':
    QCoreApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QCoreApplication.setOrganizationName('davisr')
    QCoreApplication.setOrganizationDomain('davisr.me')
    QCoreApplication.setApplicationName('rcu')

    # Make CLI arguments accessible throughout the program
    QCoreApplication.args = args

    # Version is now stored in version.txt
    ui_basepath = '.'
    if hasattr(sys, '_MEIPASS'):
        ui_basepath = sys._MEIPASS
    versiontxt = Path(Path(ui_basepath) / 'version.txt')
    with open(versiontxt, 'r', encoding='utf-8') as f:
        vstring = f.read().splitlines()[0].strip().split('\t')
        sortcode = vstring[0]
        prettyver = vstring[1]
        QCoreApplication.version_sortcode = sortcode
        QCoreApplication.setApplicationVersion(prettyver)
        if args.version:
            log.info(prettyver)
            sys.exit(0)
        else:
            log.info('running version {}'.format(prettyver))

    # Clear config or share data? These are command line arugments
    # that will quit after running.
    if args.purge_settings:
        log.info('purging config!')
        QSettings().clear()
        sys.exit(0)

    # if args.purge_data:
    #     log.info('purging data!')
    #     sys.exit(0)
            
    # Find the share dir
    share_dir = Path(Path.home() / \
                      Path('.local') / \
                      Path('share') / \
                      Path(QCoreApplication.organizationName()) / \
                      Path(QCoreApplication.applicationName()))
    if 'Windows' == platform.system():
        share_dir = Path(Path.home() / \
                          Path('AppData') / \
                          Path('Roaming') / \
                          Path(QCoreApplication.organizationName()) / \
                          Path(QCoreApplication.applicationName()))
    elif 'Darwin' == platform.system():
        share_dir = Path(Path.home() / \
                          Path('Library') / \
                          Path('Application Support') / \
                          Path(QCoreApplication.applicationName()))
    test_sharedir = QSettings().value('main/share_path')
    if test_sharedir:
        QCoreApplication.sharePath = Path(test_sharedir)
    else:
        QCoreApplication.sharePath = share_dir
        QSettings().setValue('main/share_path', str(share_dir))
    QCoreApplication.sharePath.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    palette = QPalette()

    # Keep consistent style across platforms (hard to write code when
    # spacing/geometry is slightly different on every platform).
    app.setStyle(QStyleFactory.create('Fusion'))

    # !!
    # Platform-specific color tweaks must come before dark mode
    # !!

    # Everything has white-highlighted text -- all platforms, either
    # light or dark mode.
    palette.setColor(QPalette.HighlightedText, Qt.white)

    # Qt doesn't auto-detect the accent color on Windows, like it does
    # on macOS.
    if 'Windows' == platform.system():
        # This is called the "accent color" in Windows
        ac_int = QSettings('HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\DWM', QSettings.NativeFormat).value('ColorizationAfterglow')
        ac_bytes = ac_int.to_bytes(4, 'big', signed=True)
        ac_color = QColor.fromRgb(ac_bytes[1], ac_bytes[2],
                                  ac_bytes[3], ac_bytes[0])
        palette.setColor(QPalette.Highlight, ac_color)

    # Dark mode
    QCoreApplication.is_dark_mode = False

    # Detect non-KDE systems dark modes. Don't use system_dark
    # for KDE because it is natural with Qt!
    system_dark = False
    if 'Darwin' == platform.system():
        if 150 > palette.color(QPalette.Window).lightness():
            system_dark = True
    elif 'Windows' == platform.system():
        w_settings = QSettings('HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize', QSettings.NativeFormat)
        if 0 == w_settings.value('AppsUseLightTheme'):
            system_dark = True
    # elif GNOME?
    # TODO... will fail 'light' for now...
    if system_dark:
        log.info('detected implicit/system dark mode')

    # Whatever the accent color is...tone it down. This was originally
    # to match macOS/Finder.app colors. Don't use this for Windows,
    # which has different accent color behavior.
    if 'Darwin' == platform.system():
        # Color brightness varies on macOS
        value_mod = 0.8
        if args.dark or system_dark:
            value_mod = 1.0
        ohlt = palette.color(QPalette.Highlight)
        hsv = ohlt.toHsv()
        hsv.setHsv(hsv.hue(),
                   255,
                   hsv.value() * value_mod)
        palette.setColor(QPalette.Highlight, hsv)

        # If we're in dark mode, and the highlight color is too light,
        # such as macOS Graphite, then tone it down.
        if 150 < palette.color(QPalette.Highlight).lightness():
            hlt = palette.color(QPalette.Highlight)
            hlt.setHsv(hlt.hue(),
                       hlt.saturation(),
                       hlt.value() * 0.6)
            palette.setColor(QPalette.Highlight, hlt)

    # # Fix weak-looking text for lighter highlights. Also matches
    # # macOS/Finder.app.
    # if 170 > palette.color(QPalette.Highlight).lightness():
    #     palette.setColor(QPalette.HighlightedText, Qt.white)
    # else:
    #     palette.setColor(QPalette.HighlightedText, Qt.black)

    # Confirm palette before going further -- QStyleSheet interferes.
    app.setPalette(palette)

    # Apply dark theme on non-KDE systems (or with flag)
    if args.dark or system_dark:
        QCoreApplication.is_dark_mode = True
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(45, 45, 45))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(187, 138, 255))
        # palette.setColor(QPalette.Highlight, QColor(97, 42, 218))
        # palette.setColor(QPalette.HighlightedText, Qt.white)
        darkGray = QColor(53, 53, 53);
        gray = QColor(128, 128, 128);
        black = QColor(25, 25, 25);
        blue = QColor(42, 130, 218);
        palette.setColor(QPalette.Active, QPalette.Button, gray.darker());
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, gray);
        palette.setColor(QPalette.Disabled, QPalette.WindowText, gray);
        palette.setColor(QPalette.Disabled, QPalette.Text, gray);
        palette.setColor(QPalette.Disabled, QPalette.Light, darkGray);
        # Tooltip color, duplicate the highlight color
        tooltip_style = 'QToolTip { '
        tooltip_style += 'color: {}; background-color: {}; border: 1px solid {}; '.format(
            palette.color(QPalette.Text).name(),
            palette.color(QPalette.AlternateBase).name(),
            palette.color(QPalette.Base).name())
        tooltip_style += '}'
        app.setStyleSheet(tooltip_style)
        # Confirm palette
        app.setPalette(palette)

    # Other platform tweaks
    if 'Darwin' == platform.system():
        # macOS font fix must come after stylesheet change
        # macOS font is to get past Qt 5.13.2 issue where there is no
        # spacing after a comma (QTBUG-86496).
        app.setFont(QFont('Lucida Grande'))
    if 'Windows' == platform.system():
        # Todo: only set this to 9pt when the user has not already
        # changed their desktop font size.
        # ...
        app.setFont(QFont('Segoe UI', 9))

    # The model and threadpool are distributed to all panes.
    model = model.RCU(QCoreApplication)
    threadpool = QThreadPool()
    model._app = app

    # Skip main application for rendering RMN to PDF. Use dummy doc.
    if args.render_rmn_pdf_b or args.render_rmn_pdf_v:
        from model.document import Document
        from model.display import ProtoDisplayRM
        model.display = ProtoDisplayRM(model)
        filearg = args.render_rmn_pdf_b or args.render_rmn_pdf_v
        infile = filearg[0]
        outfile = filearg[1]
        doc = Document(model)
        doc.set_local_archive(infile)
        if doc.save_pdf(outfile):
            sys.exit(0)
        else:
            sys.exit(1)

    # Set the application icon (for 'nix and Windows-windowed). macOS
    # gets its icon from PyInstaller, and is special for Mac.
    if 'Darwin' != platform.system():
        icon = QIcon()
        sizes = [16, 24, 32, 48, 64, 128, 256]
        for size in sizes:
            sizestr = "{}x{}".format(size, size)
            icon_path = Path(Path(ui_basepath) / 'icons' / sizestr /
                             'rcu-icon-{}.png'.format(sizestr))
            # Running from source
            if not icon_path.exists():
                icon_path = Path(Path('..') / 'icons' / sizestr /
                                 'rcu-icon-{}.png'.format(sizestr))
            px = QPixmap(str(icon_path))
            icon.addPixmap(px)
        app.setWindowIcon(icon)

    # Start the main application with the Connection Dialog.
    utility_controller = MainUtilityController(model,
                                               threadpool)
    sys.exit(app.exec_())
