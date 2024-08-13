'''
template.py
This is the model for a template.

RCU is a management client for the reMarkable Tablet.
Copyright (C) 2020-21  Davis Remmel

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

# These need to be cleaned up -- not all these imports are required
from pathlib import Path
import log
import json
from PySide2.QtCore import QByteArray
from worker import Worker
import tempfile
import uuid
import tarfile
import zipfile
import svgtools
import os


def rmdir(path):
    for child in path.glob('*'):
        if child.is_file():
            child.unlink()
        else:
            rmdir(child)
    path.rmdir()

class Template:
    syspathpfx = '/usr/share/remarkable/templates'
    userpathpfx = '$HOME/.local/share/remarkable/templates'
    
    def __init__(self, model):
        self.model = model
        self.name = None
        self.filename = None
        self.iconcode = None
        self.categories = []
        self.landscape = False
        #self.usertemplate = False
        self.svg = None
        
    def is_valid(self):
        # Check if this template is valid (can be used with the device)
        if not self.name:
            log.error('not valid: no name')
            return False
        if not self.filename:
            log.error('not valid: no filename')
            return False
        if not self.iconcode:
            log.error('not valid: no iconcode')
            return False
        if not len(self.categories):
            log.error('not valid: no categories')
            return False
        if not self.svg:
            log.error('not valid: no svg')
            return False
        return True
        
    def from_dict(self, adict):
        self.name = adict['name']
        if 'filename' in adict:
            # If it has a filename, accept it, otherwise give it a uuid.
            self.filename = adict['filename'] or 'Blank'
        else:
            self.filename = uuid.uuid4().__str__()
        self.iconcode = adict['iconCode']
        self.categories = adict['categories']
        #if 'userTemplate' in adict:
        #    self.usertemplate = adict['userTemplate']
        if 'landscape' in adict:
            if type(adict['landscape']) is bool:
                self.landscape = adict['landscape']
            elif adict['landscape'] == 'true':
                self.landscape = True
        # Clear the SVG--this function can be called when refreshing the
        # templates view, and if we are re-loading the rest of the
        # information, we ought to reload the SVG preview as well.
        self.svg = None
        return self
    
    def get_svg(self):
        if not self.svg:
            # Load the SVG from device
            self.load_svg_from_device()
        return self.svg
    
    def load_svg_from_device(self):
        cmd = 'cat "/usr/share/remarkable/templates/{}.svg"'.format(
            self.filename)
        out, err = self.model.run_cmd(cmd, raw=True)
        if len(err):
            # not a dealbreaking error
            log.error('could not get svg for template')
            log.error(err)
            return self.load_svg_from_device_pngbackup()
        self.svg = QByteArray(out)

    def load_svg_from_device_pngbackup(self):
        # If an SVG is unavailable, try to load the PNG and shove it
        # into an SVG container.
        cmd = 'cat "/usr/share/remarkable/templates/{}.png"'.format(
            self.filename)
        out, err = self.model.run_cmd(cmd, raw=True)
        if len(err):
            # since svg and png failed, we can't do any more
            log.error('could not get png for template')
            log.error(err)
            log.error('template broken: {}'.format(self.filename))
            return
        # Make tmpfile (todo: refactor later to not need this)
        th, tmp = tempfile.mkstemp('.svg')
        os.close(th)
        tmpfile = Path(tmp)
        with open(tmpfile, 'wb') as f:
            f.write(out)
            f.close()
        self.svg = QByteArray(svgtools.png_to_svg(tmpfile))
        tmpfile.unlink()
        
    def load_svg_from_bytes(self, abytes):
        self.svg = QByteArray(abytes)
        
    def to_dict(self, with_filename=False):
        # Don't export filenames because the template exports
        # should be transferrable and not overwrite existing
        # ones. UUID filenames are given upon import.
        adict = {
            'name': self.name,
            'iconCode': self.iconcode,
            'categories': self.categories,
            #'userTemplate': self.usertemplate,
            'landscape': self.landscape
            }
        if with_filename:
            adict['filename'] = self.filename
        return adict
    
    def orientation(self):
        if self.landscape:
            return 'L'
        return 'P'
    
    def install_to_device(self):
        # Installs this template to the device
        if not self.is_valid():
            log.error('install to device error: template invalid')
            return
        device_templates = self.get_device_templates_dict()
        for t in device_templates['templates']:
            if t['filename'] == self.filename:
                # template already on device
                return
            
        # Ensure user templates dir exists
        cmd = 'mkdir -p "{}"'.format(type(self).userpathpfx)
        self.model.run_cmd(cmd)
        cmd = 'journalctl --vacuum-size=10M'
        self.model.run_cmd(cmd)
        
        # PNG ##
        datab = svgtools.svg_to_png(
            self.svg,
            type(self.model.display).portrait_size)
        uploadpath = '{}/{}.png'.format(
            type(self).userpathpfx,
            self.filename)
        cmd = 'cat > "{}"'.format(uploadpath)
        out, err, stdin = self.model.run_cmd(cmd,
                                             raw_noread=True,
                                             with_stdin=True)
        z = len(datab)
        i = 0
        chunksize = 4096
        while i < z:
            chunk = datab[i:i+chunksize-1]
            stdin.write(chunk)
            i += len(chunk)
        stdin.close()
        linkpath = '{}/{}.png'.format(type(self).syspathpfx,
                                      self.filename)
        cmd = 'ln -s "{}" "{}"'.format(uploadpath, linkpath)
        self.model.run_cmd(cmd)

        # SVG ##
        datab = self.svg
        uploadpath = '{}/{}.svg'.format(
            type(self).userpathpfx,
            self.filename)
        cmd = 'cat > "{}"'.format(uploadpath)
        out, err, stdin = self.model.run_cmd(cmd,
                                             raw_noread=True,
                                             with_stdin=True)
        z = len(datab)
        i = 0
        chunksize = 4096
        while i < z:
            chunk = datab[i:i+chunksize-1]
            stdin.write(chunk)
            i += len(chunk)
        stdin.close()
        linkpath = '{}/{}.svg'.format(type(self).syspathpfx,
                                      self.filename)
        cmd = 'ln -s "{}" "{}"'.format(uploadpath, linkpath)
        self.model.run_cmd(cmd)

        # JSON ##
        datab = json.dumps(self.to_dict(with_filename=True),
                           sort_keys=True, indent=4,
                           ensure_ascii=False).encode('utf-8')
        uploadpath = '{}/{}.json'.format(
            type(self).userpathpfx,
            self.filename)
        cmd = 'cat > "{}"'.format(uploadpath)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        z = len(datab)
        i = 0
        chunksize = 4096
        while i < z:
            chunk = datab[i:i+chunksize-1]
            stdin.write(chunk)
            i += len(chunk)
        stdin.close()

        # set_device_templates_dict
        templates_dict = self.get_device_templates_dict()
        self_dict = self.to_dict(with_filename=True)
        # Go through on-device templates and if this one exists, replace
        # it
        willdel = False
        for i in range(0, len(templates_dict['templates'])):
            t = templates_dict['templates'][i]
            if t['filename'] == self.filename:
                willdel = i
                break
        if willdel is not False:
            templates_dict['templates'].pop(willdel)
        templates_dict['templates'].append(self_dict)
        self.set_device_templates_dict(templates_dict)
        
    def get_device_templates_dict(self):
        # Returns the device's templates as a dict
        cmd = 'cat "{}/templates.json"'.format(
            type(self).syspathpfx)
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('problem getting templates')
            log.error(err)
            return
        return json.loads(out)

    def set_device_templates_dict(self, tdict):
        data = json.dumps(tdict, sort_keys=True, indent=4).encode(
            'utf-8')
        cmd = 'cat > "{}/templates.json"'.format(type(self).syspathpfx)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        z = len(data)
        i = 0
        chunksize = 4096
        while i < z:
            chunk = data[i:i+chunksize-1]
            stdin.write(chunk)
            i += len(chunk)
        stdin.close()
    
    def delete_from_device(self):
        # Removes this template from the device
        # Delete from templates.json first so that if it went wrong,
        # the files would still exist and the user wouldn't be stuck
        # with a bogus json file.
        templates_dict = self.get_device_templates_dict()
        willdel = False
        for i in range(0, len(templates_dict['templates'])):
            t = templates_dict['templates'][i]
            if t['filename'] == self.filename:
                willdel = i
                break
        if willdel is not False:
            templates_dict['templates'].pop(willdel)
        self.set_device_templates_dict(templates_dict)
        # Delete the template's asset files
        files = [
            '"{}/{}.png"'.format(type(self).syspathpfx, self.filename),
            '"{}/{}.png"'.format(type(self).userpathpfx, self.filename),
            '"{}/{}.svg"'.format(type(self).syspathpfx, self.filename),
            '"{}/{}.svg"'.format(type(self).userpathpfx, self.filename),
            '"{}/{}.json"'.format(type(self).userpathpfx, self.filename)
            ]
        files_string = ' '.join(files)
        cmd = 'rm -rf {}'.format(files_string)
        self.model.run_cmd(cmd)

        # Remove this template from the modle
        self.model.templates.discard(self)

    def save_archive(self, filepath):
        # Saves an RMT archive
        tmpdir = Path(tempfile.mkdtemp())
        templatejsonpath = Path(tmpdir / 'template.json')
        with open(templatejsonpath, 'w+') as f:
            f.write(json.dumps(self.to_dict(with_filename=True),
                               sort_keys=True,
                               indent=4))
        svgfilepath = Path(tmpdir / 'template.svg')
        with open(svgfilepath, 'wb+') as f:
            f.write(self.svg.data())
        with tarfile.open(filepath, 'w') as tar:
            tar.add(templatejsonpath, arcname='template.json')
            tar.add(svgfilepath, arcname='template.svg')
            tar.close()
        # cleanup
        rmdir(tmpdir)

    def from_archive(self, filepath):
        # Self-initializes from an RMT archive
        with tarfile.open(filepath, 'r') as tar:
            jsf = tar.extractfile(tar.getmember('template.json'))
            jsdict = json.load(jsf)
            self.from_dict(jsdict)
            svgf = tar.extractfile(tar.getmember('template.svg'))
            self.load_svg_from_bytes(svgf.read())
            tar.close()
        return self

    def repair_links_with_id(self, tid):
        # Repair this template on the device, given an ID.
        # This doesn't really need to check the validity of the given ID
        # because the detection script should have done that, but for
        # reference it wouldn't be a bad idea. (TODO...)
        cmd = 'ln -s "{}/{}.png" "{}/{}.png"'.format(
            type(self).userpathpfx, tid, type(self).syspathpfx, tid)
        self.model.run_cmd(cmd)
        cmd = 'ln -s "{}/{}.svg" "{}/{}.svg"'.format(
            type(self).userpathpfx, tid, type(self).syspathpfx, tid)
        self.model.run_cmd(cmd)

        # Check the json in the tepmlates dict
        cmd = 'cat "{}/{}.json"'.format(type(self).userpathpfx, tid)
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('problem getting template repair json')
            log.err(err)
            return
        tdict = json.loads(out)
        dtdict = self.get_device_templates_dict()
        # check if tdict exists and remove, then re-add
        removeint = None
        for i in range(0, len(dtdict['templates'])):
            t = dtdict['templates'][i]
            if t['filename'] == tdict['filename']:
                removeint = i
                break
        if removeint is not None:
            del dtdict['templates'][i]
        dtdict['templates'].append(tdict)
        self.set_device_templates_dict(dtdict)

    def get_pretty_name_with_orient(self):
        return '{} ({})'.format(self.name, self.orientation())

    def get_id_archive_name(self):
        return '{}.rmt'.format(self.filename)

    def save_png(self, filepath):
        if not self.svg:
            log.error('cannot save png without svg being loaded')
            return
        pngb = svgtools.svg_to_png(
            self.svg,
            type(self.model.display).portrait_size)
        with open(filepath, 'wb+') as f:
            f.write(pngb)
            f.close()
        return True

    def write_svg_to_device(self):
        # Writes the SVG data to the device
        pass
        
