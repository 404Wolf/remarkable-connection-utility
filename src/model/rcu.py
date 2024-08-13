'''
rcu.py
This is the primary model for the Remarkable Connection Utility.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-24  Davis Remmel

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

from .config import Config
import log
import urllib.request

from PySide2.QtCore import QThreadPool, QSettings, QTimer
from PySide2.QtGui import QImage
from worker import Worker
import select
import base64
from .template import Template
from .display import DisplayRMGeneric
from .battery import BatteryRMGeneric

# For loading notebooks
import tarfile
import io
import json
import datetime
from .document import Document
from .collection import Collection

# For recovery mode
import subprocess
import platform
from pathlib import Path
import sys

class RCU:
    default_name = 'reMarkable'
    xochitlconf_path = '$HOME/.config/remarkable/xochitl.conf'

    @classmethod
    def modelnum_to_hwtype(cls, model):
        if 'RM100' == model \
           or 'RM102' == model:
            return 'RM1'
        if 'RM110' == model:
            return 'RM2'

    def __init__(self, QCoreApplication):
        self.config = Config()
        self.settings = QSettings()
        self.threadpool = QThreadPool()

        self.is_in_recovery = False
        self.has_webui = False

        self.boot_disk = '/dev/mmcblk1'

        self.device_info = dict.fromkeys(
            ['model', 'serial', 'osver', 'cpu', 'ram', 'storage_used',
             'storage_max', 'kernel', 'kernel_bootargs', 'rcuname',
             'partition_table', 'cloud_user'])

        self.device_info['rcuname'] = self.default_name
        
        # These are new -- going to load them in the model and then exec
        # some callback in the pane to load async.
        self.templates_pane = None
        self.templates = set()

        self.notebooks_pane = None
        self.last_notebooks_checksum = None
        self.collections = set()
        self.documents = set()
        self.deleted_items = set()

    def is_connected(self):
        return self.config.is_connected()

    def is_using_usb(self):
        host = self.config.host.split(':')[0]
        if '10.11.99.1' != host:
            return False
        return True

    def check_conf(self, key):
        return self.get_xochitl_conf(key) or False

    def toggle_conf(self, key):
        fromval = self.check_conf(key)
        toval = True if False == fromval else False
        log.info('toggle_conf', key, fromval, toval)
        self.set_xochitl_conf(key, toval)

    def connect(self):
        # Connect with the config
        ret = self.config.connect()
        if ret:
            self.load_device_info()
            self.is_in_recovery = False
        return ret

    def connect_restore(self, load_info=True):
        # Connect to a restore OS
        ret = self.config.connect_restore()
        # Test that it is actually the recovery OS!
        if ret:
            cmd = 'uname -a'
            out, err = self.run_cmd(cmd)
            actually_in_ros = False
            if 'rcu-rescue-os' in out.lower():
                actually_in_ros = True
            if actually_in_ros:
                log.info('!! in recovery mode !!')
                self.is_in_recovery = True
                if load_info:
                    log.info('@@@ load info was true!')
                    self.load_device_info()
            else:
                self.is_in_recovery = False
        return self.is_in_recovery

    def reconnect(self):
        if self.is_connected():
            self.config.disconnect()
        return self.connect()

    def reconnect_restore(self, load_info=True):
        if not self.is_connected():
            self.config.disconnect()
        return self.connect_restore(load_info=load_info)

    def run_cmd(self, cmd, raw=False, raw_noread=False,
                with_stdin=False, timeout=10):
        # Runs a command on the device
        if self.is_connected():
            try:
                # log.debug('running command: {}'.format(cmd))
                stdin, out, err = self.config.connection.exec_command(
                    cmd, timeout=timeout)
            except Exception as e:
                # Probably a timeout opening the channel
                self.config.disconnect(force=True)
                return ([], str(e))
            if not raw and not raw_noread:
                return (out.read().decode('utf-8'),
                        err.read().decode('utf-8'))
            if raw:
                return (out.read(), err.read())
            if raw_noread:
                if with_stdin:
                    return (out, err, stdin)
                return (out, err)
        else:
            # Session not active...what do?
            if self.reconnect():
                return self.run_cmd(cmd, raw)
            return ([], 'session is no longer active')

    def put_file(self, localfilepath, remotefilepath):
        # Puts a file to the device
        try:
            sftp = self.config.connection.open_sftp()
            sftp.put(localfilepath, remotefilepath)
        except Exception as e:
            log.error('sftp put error; ' + e.__str__())

    def get_file(self, remotefilepath, localfilepath, callback):
        # Gets a file from the device
        try:
            sftp = self.config.connection.open_sftp()
            sftp.get(remotefilepath, localfilepath, callback)
        except Exception as e:
            log.error('sftp get error; ' + e.__str__())

    def restart_xochitl(self):
        if self.display:
            # Reset display parameters for RM2
            self.display.invalidate_pixel_cache(clear_addr=True)
        cmd = 'systemctl reset-failed xochitl && systemctl restart xochitl'
        self.run_cmd(cmd)

    def stop_xochitl(self):
        if self.display:
            # Reset display parameters for RM2
            self.display.invalidate_pixel_cache(clear_addr=True)
        cmd = 'systemctl reset-failed xochitl && systemctl stop xochitl'
        self.run_cmd(cmd)

    def start_xochitl(self):
        cmd = 'systemctl reset-failed xochitl && systemctl start xochitl'
        self.run_cmd(cmd)

    def remount_home_as_readonly(self):
        cmd = 'mount -o remount,ro /home'
        out, err = self.run_cmd(cmd)
        if err and len(err):
            # Some kind of problem -- was it actually mounted ro? If
            # not, just abort.
            log.err('problem in remount_home_as_readonly')
            log.err(str(err))
            return False
        log.info('remounted home as readonly')
        return True

    def remount_home_reset(self):
        cmd = 'mount -o remount /home'
        out, err = self.run_cmd(cmd)
        if err and len(err):
            log.err('problem in remount_home_reset')
            log.err(str(err))
            return False
        log.info('remounted home as normal')
        return True

    def restart_hw(self):
        if self.display:
            # Reset display parameters for RM2
            self.display.invalidate_pixel_cache(clear_addr=True)
        self.run_cmd('/sbin/reboot')
        self.reconnect()


    def _retry_load_ros(self, cb):
        def retry(i):
            completed = False
            if i > 0:
                i -= 1
                completed = self._upload_recovery_os_for_real()
                if completed:
                    cb(completed)
                    return
                log.info('could not load the recovery os. {} retries left'.format(
                    i))
                QTimer.singleShot(2000, lambda: retry(i))
            else:
                cb(completed)
        retry(5)

    def _retry_connect_ros(self, cb, load_info=True):
        def retry(i):
            completed = False
            if i > 0:
                i -= 1
                log.info('reconnecting to restore os...')
                completed = self.reconnect_restore(load_info=load_info)
                if completed:
                    cb(completed)
                    return
                log.info('could not connect to the recovery os. {} retries left'.format(
                    i))
                QTimer.singleShot(5000, lambda: retry(i))
            else:
                cb(completed)
        retry(12)

    def upload_recovery_os(self, endcb, load_info=True):
        def loadretrydone(completed):
            if completed:
                # success, try to connect
                self._retry_connect_ros(endcb, load_info=load_info)
            else:
                # fail, done
                log.error('could not load recovery os. aborting')
                endcb(completed)
        self._retry_load_ros(loadretrydone)

    def _upload_recovery_os_for_real(self):
        selfdir = Path(__file__).parent
        if hasattr(sys, '_MEIPASS'):
            recoverydir = Path(selfdir.parent / 'recovery_os_build')
        else:
            recoverydir = Path(selfdir.parent.parent / 'recovery_os_build')
        cmd = {
            'FreeBSD': 'cd "{}" && ./imx_usb.fbsd12'.format(recoverydir),
            'Linux': 'cd "{}" && ./imx_usb.linux'.format(recoverydir),
            'Darwin': 'cd "{}" && ./imx_usb.mac'.format(recoverydir),
            'Windows': 'cd /d "{}" && .\imx_usb.win10'.format(recoverydir)
        }
        plat = platform.system()
        # The imx_usb utility does not use an error return code. I
        # should probably fix this there, but for now just look at the
        # result of the command for the 'error string'. TODO...
        done = subprocess.run(cmd[plat],
                              shell=True,
                              encoding='utf-8',
                              stderr=subprocess.PIPE)
        if 'no matching USB device found' in done.stderr:
            return False
        return True
        

    ##################
    #   DEVICE INFO  #
    ##################
    def register_device_info_pane(self, do_pane):
        self.device_info_pane = do_pane
        log.info('device_info registered')
    def load_device_info(self):
        # Loads device information. This is done here, rather than in
        # the Device Info pane, because this is very useful for other
        # panes to use in decisions.

        # Find the eMMC boot disk (needs to be done explicitly for RM2
        # compatibility).
        out, err = self.run_cmd('''cat /etc/fstab \
                                       | grep -v '^#' | grep '/home' \
                                       | head -n 1 | awk '{print $1}' \
                                       | cut -d'p' -f1''')
        if len(err):
            log.error('could not find boot disk--using default')
        elif len(out) > 2:
            self.boot_disk = out.strip()

        # Guard against microSD mod, which mounts as mmcblk0
        if '/dev/mmcblk0' == self.boot_disk:
            self.boot_disk = '/dev/mmcblk1'
        
        log.info('boot disk is {}'.format(self.boot_disk))

        # Get serial and model numbers
        out, err = self.run_cmd('''dd if={}boot1 bs=1 skip=4 \
                                   count=15'''.format(self.boot_disk))
        if len(out) != 15:
            log.error('Unable to get serial number. ' + err)
            self.device_info['serial'] = None
            self.device_info['model'] = None
        else:
            self.device_info['serial'] = out
            self.device_info['model'] = out[0:5]

        out, err = self.run_cmd(
            '''cat /usr/share/remarkable/update.conf \
               | grep REMARKABLE_RELEASE_VERSION \
               | head -n 1 | cut -d'=' -f2''')
        out = out.strip('\n')
        if len(out) >= 3 and len(out) <= 11:
            self.device_info['osver'] = out
        else:
            log.info('os version not found--trying /etc/os-release')
            out, err = self.run_cmd('(source /etc/os-release && echo $NAME)')
            out = out.strip('\n')
            if len(out) >= 3 and len(out) <= 50:
                self.device_info['osver'] = out
            else:
                log.error('Unable to get OS version. ' + err)
                self.device_info['osver'] = None

        # Once we know the model and osver, we can set the
        # device-specific attributes.
        self.display = DisplayRMGeneric.from_model(self)
        self.battery = BatteryRMGeneric.from_model(self)

        # Continue...
        out, err = self.run_cmd('''cat /proc/cpuinfo \
                                   | grep Hardware \
                                   | cut -d' ' -f2- \
                                   | sed 's/ (Device Tree)//g' ''')
        out = out.strip('\n')
        if len(out) < 5 or len(out) > 100:
            log.error('Unable to get CPU type. ' + err)
            self.device_info['cpu'] = None
        else:
            self.device_info['cpu'] = out

        out, err = self.run_cmd('''free \
                                   | grep Mem \
                                   | awk '{print $2}' ''')
        out = out.strip('\n')
        if len(out) < 4 or len(out) > 8:
            log.error('Unable to get RAM. ' + err)
            self.device_info['ram'] = None
        else:
            self.device_info['ram'] = int(int(out) / 1000)

        self.load_device_storage()

        out, err = self.run_cmd('uname -a')
        out = out.strip('\n')
        if len(out) < 15 or len(out) > 150:
            log.error('Unable to get kernel id. ' + err)
            self.device_info['kernel'] = None
        else:
            self.device_info['kernel'] = out

        out, err = self.run_cmd(
            'dmesg | grep "Kernel command line" | cut -d: -f2 \
            | tail -c +2')
        out = out.strip('\n')
        if len(out) < 15 or len(out) > 300:
            log.error('Unable to get kernel bootargs. ' + err)
            self.device_info['kernel_bootargs'] = None
        else:
            self.device_info['kernel_bootargs'] = out

        out, err = self.run_cmd('/sbin/fdisk -l')
        if len(out) < 500 or len(out) > 5000:
            log.error('Unable to get partition table. ' + err)
            self.device_info['partition_table'] = None
        else:
            self.device_info['partition_table'] = base64.b64encode(
                bytes(out, 'utf-8')).decode('utf-8')

        # Check if this is a reMarkable Cloud user.
        out, err = self.run_cmd('grep "usertoken" {}'.format(self.xochitlconf_path))
        out = out.strip('\n')
        if len(out):
            self.device_info['cloud_user'] = True
        else:
            self.device_info['cloud_user'] = False

        self.load_device_name()
        
        if hasattr(self, 'device_info_pane'):
            self.device_info_pane.update_view(loadinfo=False)

    def load_device_storage(self):
        out, err = self.run_cmd('''df | grep '/home$' | head -n 1 \
                                   | awk '{print $2 " " $3}' ''')
        out = out.strip('\n')
        storparts = out.split(' ')
        if len(storparts) != 2:
            log.error('Unable to get storage use. ' + err)
            self.device_info['storage_min'] = None
            self.device_info['storage_used'] = None
            self.device_info['storage_pct'] = None
            self.device_info['storage_max'] = None
        else:
            self.device_info['storage_max'] = round(
                int(storparts[0]) / 1000000, 1)
            self.device_info['storage_used'] = round(
                int(storparts[1]) / 1000000, 1)

        if hasattr(self, 'device_info_pane'):
            self.device_info_pane.update_view(loadinfo=False)

    def load_device_name(self):
        # Just loads the device name (broken out because its quicker)
        namefile = '$HOME/.rcu-name'
        
        cmd = 'cat "{}"'.format(namefile)
        out, err = self.run_cmd(cmd)
        if len(err):
            log.info('device does not have a name ({})'.format(
                err.strip()))
            self.device_info['rcuname'] = type(self).default_name
            return
        realname = out.strip('\n').strip()
        self.device_info['rcuname'] = realname

    def set_device_name(self, name):
        namefile = '$HOME/.rcu-name'

        if not name or name == '':
            self.device_info['rcuname'] = type(self).default_name
            cmd = 'rm -f "{}"'.format(namefile)
            self.run_cmd(cmd)
        else:
            cmd = 'echo "{}" > "{}"'.format(name, namefile)
            out, err, sin = self.run_cmd(cmd, raw_noread=True,
                                               with_stdin=True)
            sin.write(name.encode('utf-8'))
            sin.close()
            self.device_info['rcuname'] = name
            log.info('set device name to {}'.format(name))

    def _qt_from_conf_value(self, val):
        if 'true' == val:
            return True
        elif 'false' == val:
            return False
        # try number
        try:
            val = float(val)
            return val
        except:
            pass
        return val

    def _qt_to_conf_value(self, val):
        if True == val:
            return 'true'
        elif False == val:
            return 'false'
        return str(val)

    def get_xochitl_conf(self, key):
        # Returns configuration parameters inside xochitl.conf.
        # xochitlconf_path=
        cmd = 'cat "{}" | grep "{}" | cut -d= -f2'.format(
            self.xochitlconf_path, key)
        out, err = self.run_cmd(cmd)
        if len(err.strip()):
            log.error(err)
            return
        val = out.strip()
        # log.debug('get_xochitl_conf', key, val)
        return self._qt_from_conf_value(val)

    def set_xochitl_conf(self, key, val, restart=True):
        # Sets configuration parameters inside xochitl.conf.
        # xochitlconf_path
        replacement = '{}={}'.format(key, self._qt_to_conf_value(val))
        cmd = 'sed -i "s/^{}=.*$/{}/g" "{}"'.format(
            key, replacement, self.xochitlconf_path)
        # log.debug(cmd)
        out, err = self.run_cmd(cmd)
        if len(err.strip()):
            log.error(err)
        # assume success? maybe pass $? back ...
        if restart:
            self.restart_xochitl()

    def get_systemd_service(self, name):
        # Returns whether service is enabled or not.
        cmd = '/bin/systemctl is-enabled {}'.format(name)
        out, err = self.run_cmd(cmd)
        if len(err.strip()):
            log.error(err)
            return
        return out.strip() == 'enabled'

    def set_systemd_service(self, name, enable=True):
        c = 'enable' if enable else 'disable'
        log.info('set_systemd_service', name, enable)
        cmd = '/bin/systemctl {} {}'.format(c, name)
        out, err = self.run_cmd(cmd)

    def is_gt_eq_xochitl_version(self, string_to_test):
        # Use this function whenever testing for versions (or inferring
        # capabilities).
        v_now = list(map(int, self.device_info['osver'].split('.')))
        v_test = list(map(int, string_to_test.split('.')))
        ret = True
        for i, tv in enumerate(v_test):
            nv = v_now[i]
            if not tv <= nv:
                ret = False
        return ret

    #################
    #   TEMPLATES   #
    #################
    def register_templates_pane(self, templates_pane):
        self.templates_pane = templates_pane
        
    def load_templates(self, trigger_ui=True):
        # Loads the templates, but not fully; just enough to emit an
        # item back for the GUI. Templates can be loaded
        # fully within themselves (which saves GUI thread time)
        log.info('loading templates')
        
        # When re-loading templates, sometimes they get deleted. So,
        # we need to keep a list of the ones that no longer exist,
        # so they can be removed from the primary list.
        new_templates = set()

        templates_obj = Template(self).get_device_templates_dict()
        for t in templates_obj['templates']:
            # If this already exists in the old set, use that. Using
            # get_template().from_dict() will keep the old template
            # object, but update it with new information and clear
            # the SVG.
            template = self.get_template(t['filename']).from_dict(t)
            new_templates.add(template)
        self.templates = new_templates

        if self.templates_pane and trigger_ui:
            self.templates_pane.load_items()
        
        # templates_obj = Template(self).get_device_templates_dict()
        # for t in templates_obj['templates']:
        #     template = Template(self).from_dict(t)
        #     self.add_template(template)

    def template_is_loaded(self, tfilename):
        for template in self.templates:
            if template.filename == tfilename:
                return True
        return False

    def get_template(self, tfilename):
        # Search for a template that already exists, or return a new one
        # if it doesn't.
        for template in self.templates:
            if template.filename == tfilename:
                # already exists
                # reset svg so it reloads on a new click
                template.svg = None
                return template
        return Template(self)

    def add_template(self, atemplate):
        # Only add if not already exists (because this function can
        # be used for a refresh).
        usetemplate = self.get_template(atemplate.filename)
        # clone
        usetemplate.from_dict(atemplate.to_dict(with_filename=True))
        usetemplate.svg = atemplate.svg
        self.templates.add(usetemplate)
        if self.templates_pane:
            self.templates_pane.load_items()
        return usetemplate

    def add_new_template_from_dict(self, adict):
        template = Template(self).from_dict(adict)
        return self.add_template(template)

    def add_new_template_from_archive(self, rmtfile):
        template = Template(self).from_archive(rmtfile)
        return self.add_template(template)


    ###############
    #  NOTEBOOKS  #
    ###############
    def register_notebooks_pane(self, nb_pane):
        self.notebooks_pane = nb_pane
    
    def load_notebooks(self, trigger_ui=True, force=False):
        # Determine if there are changed notebooks to load based on the
        # checksum of the directory listing (fast method to prevent
        # excessive data transmission).
        cmd = '''cd $HOME/.local/share/remarkable/xochitl && ls -lha *.content *.metadata | md5sum | cut -d' ' -f1'''
        out, err = self.run_cmd(cmd)
        if len(err):
            log.error('problem getting documents list')
            log.error(err)
            log.error('aborting notebook load')
            return False
        new_checksum = out.strip()
        if self.last_notebooks_checksum == new_checksum and not force:
            #log.info('notebooks are already up-to-date')
            return False
        self.last_notebooks_checksum = new_checksum
        log.info('loading notebooks')

        ## Todo: relocate this into the Notebook() class, like it is
        ## for the templates.
        # Read the notebook metadata
        cmd = '''find $HOME/.local/share/remarkable/xochitl \
                      -maxdepth 1 \
                      -name "*.content" -o -name "*.metadata" \
                      | sed "s!.*/!!" \
                      | tar -T /dev/stdin -cf - \
                      -C $HOME/.local/share/remarkable/xochitl'''
        out, err = self.run_cmd(cmd, raw=True)
        if len(err.decode('utf-8')):
            log.error('problem getting metadata/content archive')
            log.error(err)
            return False

        mdarchive = tarfile.open(fileobj=io.BytesIO(out))
        gathered_ids = set()
        for ti in mdarchive.getmembers():
            gathered_ids.add(ti.name.split('.')[0])

        # Make a set of the new items. If the collections or notebooks
        # already exist, use those, but reload them with new metadata.
        # Otherwise, make new ones. Add them to these sets, then
        # replace the master sets with these new ones.
        new_collections = set()
        new_documents = set()
        new_deleted_items = set()
        
        i = 0
        for uuid in gathered_ids:
            try:
                contentfile = mdarchive.extractfile(uuid + '.content')
                metadatafile = mdarchive.extractfile(uuid + '.metadata')
                content = json.load(contentfile)
                metadata = json.load(metadatafile)
            except Exception as e:
                log.error('unable to parse content/metadata')
                log.error(e)
                continue

            if 'fileType' not in content:
                filetype = None
            elif '' == content['fileType']:
                filetype = 'notebook'
            else:
                filetype = content['fileType']

            metadata['id'] = uuid
            metadata['filetype'] = filetype

            item = None
            if 'CollectionType' == metadata['type']:
                collection = self.get_collection(metadata['id']).from_dict(metadata)
                collection._content_dict = content
                if not collection.deleted:
                    new_collections.add(collection)
                else:
                    new_deleted_items.add(collection)
            elif 'DocumentType' == metadata['type']:
                document = self.get_document(metadata['id']).from_dict(metadata)
                if not document.deleted:
                    new_documents.add(document)
                else:
                    new_deleted_items.add(document)
        mdarchive.close()

        self.collections = new_collections
        self.documents = new_documents
        self.deleted_items = new_deleted_items

        if self.notebooks_pane and trigger_ui:
            self.notebooks_pane.load_items()

        # Reload the device info too--storage probably changed.
        self.load_device_storage()

        return True

    def document_exists(self, did):
        for document in self.documents:
            if document.uuid == did:
                return True
        return False

    def collection_exists(self, cid):
        for collection in self.collections:
            if collection.uuid == cid:
                return True
        return False

    def get_collection(self, cid):
        # Returns the existing collection, or returns a new one if it
        # didn't exist.
        for collection in self.collections:
            if collection.uuid == cid:
                return collection
        collection = Collection(self)
        return collection

    def get_document(self, did):
        # Returns the existing document, or returns a new one if it
        # didn't exist.
        for document in self.documents:
            if document.uuid == did:
                return document
        return Document(self)

