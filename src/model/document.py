'''
document.py
This is the model for notebook Documents.

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

import log
import tempfile
import tarfile
from pathlib import Path
import json
import time
import os

import svgtools
from model.template import Template
from .docrender import DocRender
from .generic_notebook_type import GenericNotebookType


def rmdir(path):
    if path.is_file() and path.exists():
        path.unlink()
    try:
        for child in path.glob('*'):
            if child.is_file():
                child.unlink()
            else:
                rmdir(child)
        path.rmdir()
    except:
        pass


class Document(GenericNotebookType):
    rm_type = 'DocumentType'

    # Pass the model just so documents can handle their own PDF
    # conversion.
    def __init__(self, model):
        super(type(self), self).__init__(model)

        # WIP: replace contentdict references with a vanilla contentdict.
        fv = self.get_format_version()
        if 1 == fv:
            self._content_dict = {
                'dummyDocument': False,
                'extraMetadata': {},
                'fileType': None,
                'fontName': '',
                'lastOpenedPage': 0,
                'legacyEpub': False,
                'lineHeight': -1,
                'margins': 100,
                'orientation': 'portrait',
                'pageCount': 0,
                'textScale': 1,
                'transform': {
                    'm11': 1,
                    'm12': 0,
                    'm13': 0,
                    'm21': 0,
                    'm22': 1,
                    'm23': 0,
                    'm31': 0,
                    'm32': 0,
                    'm33': 1
                },
                'pages': [],
                'redirectionPageMap': []
            }
        elif 2 == fv:
            # WIP: this condition does not get called yet.
            self._content_dict = {
                "documentMetadata": {},
                "extraMetadata": {},
                "formatVersion": fv,
                "pageTags": [],
                "tags": [],
                "zoomMode": "bestFit"
            }

        self._iter_pool = model.documents

        # When use_local_archive is set to a path string, the rendering
        # process will use that local .rmn instead of trying to pull one
        # from the tablet.
        self.use_local_archive = None

        # If the document has a basepdf and is protected by a password,
        # the UI may attach the password here.
        self._pdf_password = None

        # Other metadata keys
        self.set_filetype('notebook')
        self.visible_name = 'Untitled Document'

        # pagedata is not actually an array on the device--it's a plain
        # text file with one line per-page. PDF has every line show
        # 'Blank'. Each line is the name of a template.
        self.pagedata = []

        # ddvk/remarkable-hacks can add a .bookm file to the
        # notebook data. This is a JSON file, and probably needs
        # a proper interface for interacting with this in RCU.
        # TODO...
        self.ddvk_bookmarks = None

    # Set minimum number of properties to not conflict with other docs.
    def from_dict_as_new(self, adict):
        # 'filetype' used to be listed in the .metadata, but now is only
        # found in the contentdict (noticed in firmware 2.9).
        if 'filetype' in adict:
            self.set_filetype(adict['filetype'])
        self.visible_name = adict['visibleName']
        return self

    def load_all_meta_from_extract(self, x_path):
        # This assumes that self.uuid is already correct.
        metadatapath = Path(x_path / Path(self.uuid + '.metadata'))
        if metadatapath.exists() and metadatapath.is_file():
            with open(metadatapath, 'r') as f:
                self.from_dict(json.load(f))
                f.close()
        contentpath = Path(x_path / Path(self.uuid + '.content'))
        if contentpath.exists() and contentpath.is_file():
            with open(contentpath, 'r') as f:
                self._content_dict = json.load(f)
                f.close()
        # Check for (and load) ddvk bookmarks
        bmpath = Path(x_path / Path(self.uuid + '.bookm'))
        if bmpath.exists() and bmpath.is_file():
            try:
                with open(bmpath, 'r') as f:
                    bm = json.load(f)
                    self.ddvk_bookmarks = bm
                    f.close()
                log.info('loaded bookmarks (ddvk/remarkable-hacks)')
            except Exception as e:
                log.error('error loading bookmarks (ddvk/remarkable-hacks)')
                log.error(e)

    def set_local_archive(self, ar_str):
        # todo
        # If using a local archive, load all document metadata now.
        self.use_local_archive = ar_str
        
        mdname = None
        tf = tarfile.open(self.use_local_archive)
        names = tf.getnames()
        tf.close()
        for name in names:
            if '.metadata' in name:
                mdname = name
        if not mdname:
            log.error('no metadata file in archive')
            return
        tf = tarfile.open(self.use_local_archive)
        tm = tf.getmember(mdname)
        tmpmd = tf.extractfile(tm)
        mdj = json.load(tmpmd)
        mdj['id'] = mdname.replace('.metadata', '')
        self.from_dict(mdj)
        tf.close()

        print(self)

    def get_format_version(self):
        # This is a very important function which defines the switches
        # program-wide for handling different Document format versions.
        v = 1
        if 'formatVersion' in self._content_dict:
            # Cast to int as sanity check
            v = int(self._content_dict['formatVersion'])
        return v

    def get_tsfm(self):
        default_tsfm = {
            'm11': 1, 'm12': 0, 'm13': 0,
            'm21': 0, 'm22': 1, 'm23': 0,
            'm31': 0, 'm32': 0, 'm33': 1
        }
        if 'transform' in self._content_dict:
            testkeys = {'m11', 'm12', 'm13',
                        'm21', 'm22', 'm23',
                        'm31', 'm32', 'm33'}
            cdkeys = self._content_dict['transform'].keys()
            if cdkeys >= testkeys:
                tsfm = self._content_dict['transform']
            else:
                tsfm = default_tsfm
        else:
            tsfm = default_tsfm
        return tsfm

    def get_pages_len(self):
        page_length = 0
        try:
            # fw.1, fw.2
            page_length = len(self._content_dict['pages'])
        except:
            # fw.3
            page_length = len(self._content_dict['cPages']['pages'])
        return page_length

    def get_uuid_for_page(self, index):
        if 1 == self.get_format_version():
            return self._content_dict['pages'][index]
        return self._content_dict['cPages']['pages'][index]['id']

    def get_redirection_for_page(self, index):
        # Firmware 2.12 added the ability to add and remove PDF
        # pages from PDF documents.
        if 1 == self.get_format_version():
            # Test the intersection of the map's indexes
            # fw.2
            if 'redirectionPageMap' in self._content_dict \
               and 1 <= len(self._content_dict['redirectionPageMap']):
                return self._content_dict['redirectionPageMap'][index]
            else:
                # No mapping at all
                return index
        # fw.3
        redir_map = []
        for p, page in enumerate(self._content_dict['cPages']['pages']):
            if 'redir' in page:
                redir_map += [page['redir']['value']]
            else:
                redir_map += [-1]
        return redir_map[index]

    def get_filetype(self):
        # Pre-fw.2.9, the "filetype" was an attribute in the metadata
        # dict. After, it became "fileType" in the contentdict.
        fv = self.get_format_version()
        if 1 == fv:
            # fw.2.9 and later
            if 'fileType' in self._content_dict \
               and self._content_dict['fileType'] is not None:
                return self._content_dict['fileType']
            # fw.2.8 and earlier
            if 'filetype' in self._metadata_dict \
               and self._metadata_dict['filetype'] is not None:
                return self._metadata_dict['filetype']
            return self._content_dict['fileType']
        elif 2 == fv:
            return self._content_dict['fileType']

    def set_filetype(self, filetype):
        # Pre-fw.2.9, the "filetype" was an attribute in the metadata
        # dict. After, it became "fileType" in the contentdict.
        # TODO: should we set both, or just leave it in the contentdict?
        # Later firmwares seem to just infer it, or overwrite it when
        # it is incorrect.
        fv = self.get_format_version()
        if 1 == fv:
            self._content_dict['fileType'] = filetype
        elif 2 == fv:
            self._content_dict['fileType'] = filetype

    def write_metadata_out(self):
        # Always increment the version number by 1 before writing, to
        # force a cloud sync of new data (if the user has that).
        self.version += 1
        
        js = json.dumps(self.as_dict(), sort_keys=True, indent=4)
        cmd = 'cat > "{}/{}.metadata"'.format(type(self).pathpfx,
                                              self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(js)
        stdin.close()

    def write_content_out(self):
        jsons = json.dumps(self._content_dict, sort_keys=True,
                           indent=4)
        cmd = 'cat > "{}/{}.content"'.format(type(self).pathpfx,
                                             self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(jsons)
        stdin.close()

    def write_pagedata_out(self):
        pds = '\n'.join(self.pagedata)
        cmd = 'cat > "{}/{}.pagedata"'.format(type(self).pathpfx,
                                              self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(pds)
        stdin.close()

    def write_ddvk_bookmarks_out(self):
        if not self.ddvk_bookmarks:
            return False
        jsons = json.dumps(self.ddvk_bookmarks, sort_keys=True,
                           indent=4)
        cmd = 'cat > "{}/{}.bookm"'.format(type(self).pathpfx,
                                           self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(jsons)
        stdin.close()

    def get_manifest_strings(self):
        # Document Files
        pathpfx = '$HOME/.local/share/remarkable/xochitl'
        taritems = [
            self.uuid,
            self.uuid + '.content',
            self.uuid + '.metadata',
            self.uuid + '.pagedata',
            self.uuid + '.highlights',
            self.uuid + '.bookm'
            ]
        _filetype = self.get_filetype()
        if 'pdf' == _filetype:
            taritems.append(self.uuid + '.' + _filetype)
        elif 'epub' == _filetype:
            taritems.append(self.uuid + '.' + _filetype)
            # also rm-converted pdf
            taritems.append(self.uuid + '.pdf')
        taritemstring = ' '.join(taritems)
        return (pathpfx, taritemstring)

        # Template Files
        #pathpfx = '/usr/share/remarkable/templates'

    def estimate_size(self, abort_func=lambda: ()):
        r = self.get_manifest_strings()
        pathpfx = r[0]
        taritemstring = r[1]
        # get estimated file size
        cmd = '(cd {} && du -ck {} 2>/dev/null | grep total | cut -f1)'.format(
            pathpfx, taritemstring)
        if abort_func():
            return
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('error getting estimated file archive size')
            log.error(err)
            return False
        # Adds 4k for good measure
        estsizeb = (int(out) + 4) * 1024
        return estsizeb

    def upload_file(self, filepath, parent=None, bytes_cb=lambda x: (),
                    abort_func=lambda x=None: (), visible_name=None):
        # Uploads a PDF or Epub file to the tablet.

        # This is going to be a new document that is written back out to
        # the tablet.
        txbytes = 0

        # This ought to be a dummy document, so we can use itself
        _filetype = filepath.suffix.replace('.', '').lower()
        self.set_filetype(_filetype)
        self.last_modified = str(round(time.time() * 1000))
        self.visible_name = visible_name or filepath.stem

        if parent:
            self.parent = parent.uuid

        # Using new UUID, upload PDF to tablet
        log.info('uploading document', self.uuid)
        r_destfile = '{}/{}.{}'.format(
            type(self).pathpfx, self.uuid, _filetype)
        cmd = 'cat > "{}"'.format(r_destfile)
        out, err, stdin = self.model.run_cmd(
            cmd, raw_noread=True, with_stdin=True)
        f = open(filepath, 'rb')
        while True:
            if abort_func():
                self.model.run_cmd('killall cat')
                break
            chunk = f.read(4096)
            if chunk:
                stdin.write(chunk)
                txbytes += len(chunk)
                bytes_cb(txbytes)
            else:
                break
        f.close()
        stdin.close()

        if abort_func():
            self.delete(force=True)
            return txbytes

        self.write_metadata_out()
        self.write_content_out()
        # .pagedata is generated automatically by tablet

        return txbytes

    def upload_archive(self, filepath, parent,
                       bytes_cb=lambda x: (),
                       abort_func=lambda x=None: ()):
        # Uploads an .rmn archive to the tablet. It used to be that
        # this function directly extracted a .rmn into the tablet's
        # share/data directory, but that has a number of drawbacks
        # and caused some customer complaints. This 'raw' extract
        # always removed an existing document sharing the same ID,
        # including if an .rmn was subsequently uploaded into a
        # parent folder. Customers seem to expect a kind-of-
        # duplication. So, this no longer clobbers the existing
        # share dir, and will now upload .rmn with new document
        # IDs and metadata.

        tf = tarfile.open(filepath)
        members = tf.getmembers()

        # In the case of .epub, there may be multiple primary files
        # (a generated .pdf, too).
        primfile_members = []
        rmfile_members = []
        template_members = []

        # Do a run-through just to load document metadata/content.
        for m in members:
            if m.isfile() and m.name.endswith('.metadata'):
                try:
                    metadata = json.load(tf.extractfile(m))
                    self.from_dict_as_new(metadata)
                except Exception as e:
                    log.error('unable to set document metadata')
                    log.error(e)
            elif m.isfile() and m.name.endswith('.content'):
                try:
                    self._content_dict = json.load(tf.extractfile(m))
                except Exception as e:
                    log.error('unable to set document content')
                    log.error(e)
            elif m.isfile() and m.name.endswith('.pagedata'):
                try:
                    self.pagedata = []
                    pd_text = tf.extractfile(m).read().decode('utf-8')
                    for line in pd_text.splitlines():
                        self.pagedata.append(line)
                except Exception as e:
                    log.error('unable to set document pagedata')
                    log.error(e)
            elif m.isfile() and (m.name.endswith('.pdf') \
                                 or m.name.endswith('.epub')):
                primfile_members.append(m)
            elif m.isfile() and (m.name.endswith('.lines') \
                                 or m.name.endswith('.rm') \
                                 or m.name.endswith('-metadata.json')):
                rmfile_members.append(m)
            elif m.isfile() and m.name.endswith('.rmt'):
                template_members.append(m)
            elif m.isfile() and m.name.endswith('.bookm'):
                try:
                    bm = json.load(tf.extractfile(m))
                    self.ddvk_bookmarks = bm
                except Exception as e:
                    log.error('unable to set ddvk bookmarks')
                    log.error(e)
            # elif m.isdir():
            #     # This is the .rm/-metadata.json directory, and needs to
            #     # be re-created on the target device.
            #     data_dir_member = m
            

        # Change the parent, if necessary
        if parent:
            self.parent = parent.uuid

        # Write the primary files out
        log.info('uploading archive', self.uuid)
        txbytes = 0
        for m in primfile_members:
            ext = Path(m.name).suffix
            cmd = 'cat > "{}/{}{}"'.format(
                type(self).pathpfx,
                self.uuid,
                ext)
            out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                                 with_stdin=True)
            f = tf.extractfile(m)
            while True:
                if abort_func():
                    # Force reconnect to terminate tar
                    self.model.run_cmd('killall cat')
                    break
                chunk = f.read(4096)
                if chunk:
                    stdin.write(chunk)
                    txbytes += len(chunk)
                    bytes_cb(txbytes)
                else:
                    break
            stdin.close()
            f.close()

        # Write .rm files (and associated) out
        cmd = 'mkdir -p "{}/{}"'.format(type(self).pathpfx,
                                        self.uuid)
        self.model.run_cmd(cmd)
        for m in rmfile_members:
            fname = Path(m.name).name
            cmd = 'cat > "{}/{}/{}"'.format(
                type(self).pathpfx,
                self.uuid,
                fname)
            out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                                 with_stdin=True)
            f = tf.extractfile(m)
            while True:
                if abort_func():
                    # Force reconnect to terminate tar
                    self.model.run_cmd('killall cat')
                    break
                chunk = f.read(4096)
                if chunk:
                    stdin.write(chunk)
                    txbytes += len(chunk)
                    bytes_cb(txbytes)
                else:
                    break
            stdin.close()
            f.close()

        if abort_func():
            tf.close()
            # Delete any uploaded contents. After this point, this
            # document will continue uploading until done.
            self.delete(force=True)
            return txbytes

        # Write metadata out
        self.write_metadata_out()
        self.write_content_out()
        self.write_pagedata_out()
        self.write_ddvk_bookmarks_out()

        # If the templates don't already exist on the device,
        # extract them.
        tmpd = Path(tempfile.mkdtemp())
        for tm in template_members:
            th, tmp = tempfile.mkstemp()
            os.close(th)
            tmpt = Path(tmp)
            tf.extract(tm, tmpd)
            name = tm.name
            fname = name.split('.')[0]
            if not self.model.template_is_loaded(fname):
                template = self.model.add_new_template_from_archive(
                    Path(tmpd / name))
                log.info('installing {}', name)
                template.install_to_device()
            tmpt.unlink()
        tf.close()
        rmdir(tmpd)

        return txbytes

    def save_archive(self, filepath, est_bytes=0,
                     bytes_cb=lambda x=None: (),
                     abort_func=lambda x=None: ()):
        if abort_func():
            return 0
        # Actually saves a document/collection from the device to disk.
        # Returns the total bytes of the tar transferred to disk.

        # Download tar from device
        r = self.get_manifest_strings()
        pathpfx = r[0]
        taritemstring = r[1]
        btransferred = 0

        cmd = 'tar cf - -C {} {}'.format(
            pathpfx, taritemstring)
        out, err = self.model.run_cmd(cmd, raw_noread=True)
        with open(filepath, 'wb+') as destfile:
            while True:
                if abort_func():
                    # Force reconnect to terminate tar
                    # self.model.reconnect()
                    self.model.run_cmd('killall tar')
                    break
                chunk = out.read(4096)
                if chunk:
                    destfile.write(chunk)
                    btransferred += len(chunk)
                    bytes_cb(btransferred)
                else:
                    break
            destfile.close()
            # Delete partially-transmitted file
        if abort_func():
            filepath.unlink()

        # Add templates to the tar archive
        cmd = 'cat "{}/{}.pagedata" | sort | uniq'.format(
            type(self).pathpfx, self.uuid)
        out, err = self.model.run_cmd(cmd)
        tids = set(out.splitlines())
        outtar = tarfile.open(filepath, 'a')
        for tid in tids:
            found = False
            for t in self.model.templates:
                if t.filename == tid:
                    # found it
                    found = True
                    th, tmp = tempfile.mkstemp()
                    os.close(th)
                    tmpfile = Path(tmp)
                    t.load_svg_from_device()
                    t.save_archive(tmpfile)
                    outtar.add(tmpfile,
                               arcname=Path(t.get_id_archive_name()))
                    tmpfile.unlink()
                    break
            if not found:
                log.error('Unable to add template to archive: {}'.format(tid))
        outtar.close()

        # If a transfer fails, maybe we should return the estimated
        # size as to not mess up the progress meter?
        return btransferred

    def save_rmwebui_file(self, filepath, filetype='pdf',
                          prog_cb=lambda x: (),
                          abort_func=lambda: False):
        # This is a generic accessor function used to pull files through
        # a tablet's web ui. In fw3.9, Xochitl added the option to
        # download .rmdoc archives via web ui, but it didn't actually
        # work until fw3.10.

        # filetypes are: pdf, rmdoc

        if 'rmdoc' == filetype:
            endpoint = 'rmdoc'
        else:
            # 'pdf' == filetype:
            endpoint = 'placeholder'

        unable_to_render = False

        if abort_func():
            return

        # Set up an internal interface, if it doesn't already exist,
        # so that the webui can be used over WiFi.
        hwmodeltype = type(self.model).modelnum_to_hwtype(
            self.model.device_info['model'])
        if 'RM1' == hwmodeltype:
            iface = 'usb0'
        elif 'RM2' == hwmodeltype:
            iface = 'usb1'

        # Is the interface active?
        cmd = "/sbin/ifconfig {} | grep -q '10\.11\.99\.1'; echo $?".format(iface)
        out, err = self.model.run_cmd(cmd)
        iface_active = False
        if '0' == out.strip():
            iface_active = True

        # If not active, set the iface temporarily so we can grab the
        # document.
        if not iface_active:
            cmd = "/sbin/ifconfig {} 10.11.99.1".format(iface)
            log.info(cmd)
            out, err = self.model.run_cmd(cmd)
            if len(err):
                log.error(err)

        # Download the document over SSH. Both 2.x and 3.x firmware
        # have wget, so use that. 3.x has curl, too, FYI.
        url = 'http://10.11.99.1/download/{}/{}'.format(
            self.uuid, endpoint)
        cmd = 'wget -O /dev/stdout "{}"'.format(url)
        with open(filepath, 'wb') as outfile:
            out, err = self.model.run_cmd(cmd, raw_noread=True,
                                          timeout=300)
            for chunk in iter(lambda: out.read(4096), b''):
                if abort_func():
                    break
                outfile.write(chunk)
                # Is there a way to estimate the filesize for webui
                # exports? TODO
                # bdone += len(chunk)
                # prog_cb(bdone / blength * 100)
            outfile.close()
            err = err.read().decode('utf-8').strip()
            if not "'/dev/stdout' saved" in err:
                log.error('problem getting webui document')
                log.error(err)
                try:
                    filepath.unlink()
                except:
                    pass
                unable_to_render = True

        # Set the iface back to how it was.
        if not iface_active:
            cmd = '/sbin/ifconfig {} 0.0.0.0'.format(iface)
            log.info(cmd)
            out, err = self.model.run_cmd(cmd)
            if len(err):
                log.error(err)

        if abort_func():
            filepath.unlink()
            return

        if unable_to_render:
            raise Exception(err)

        return True

    def save_rm_pdf(self, filepath, prog_cb=lambda x: (),
                    abort_func=lambda: False):
        log.info('save_rm_pdf')
        return self.save_rmwebui_file(filepath, filetype='pdf',
                                      prog_cb=prog_cb,
                                      abort_func=abort_func)

    def save_rm_rmdoc(self, filepath, prog_cb=lambda x: (),
                    abort_func=lambda: False):
        log.info('save_rm_rmdoc')
        return self.save_rmwebui_file(filepath, filetype='rmdoc',
                                      prog_cb=prog_cb,
                                      abort_func=abort_func)

    def save_original_file(self, filepath, filetype='pdf', prog_cb=lambda x: (),
                          abort_func=lambda: False):
        # Just downloads the original PDF/Epub to disk, directly from
        # the rM--no need to download the whole .rmn.
        log.info('save_original_file', filetype)

        if abort_func():
            return

        pdfpath = '{}/{}.{}'.format(type(self).pathpfx, self.uuid,
                                    filetype)

        cmd = 'wc -c "{}" | cut -d" " -f1'.format(pdfpath)
        # Needs about 10 seconds for 300 MB file. 60 seconds should be
        # enough for most users.
        out, err = self.model.run_cmd(cmd, timeout=60)
        if (err):
            log.error('could not get length for original {}', filetype)
            log.error(err)
            return
        blength = int(out)

        if abort_func():
            return

        bdone = 0
        with open(filepath, 'wb') as outfile:
            cmd = 'cat "{}"'.format(pdfpath)
            out, err = self.model.run_cmd(cmd, raw_noread=True)
            for chunk in iter(lambda: out.read(4096), b''):
                if abort_func():
                    break
                outfile.write(chunk)
                bdone += len(chunk)
                prog_cb(bdone / blength * 100)
            outfile.close()

        if abort_func():
            filepath.unlink()
            return

        return True

    def save_pdf(self, filepath, vector=None, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        # Exports the self as a PDF document to disk

        # prog_cb should emit between 0-100 (percent complete).
        # Percentages are split between three processes. Downloading the
        # archive takes the first 50%. If there is not a base PDF, the
        # RM page rasterization takes the next 50%. If there is a base
        # PDF, then the page rasterization takes 25% and the PDF
        # merging takes another 25%.

        if abort_func():
            return

        # Once the archive is saved, pass it over to the renderer.
        renderer = DocRender(self)
        if vector is not None:
            renderer.prefs.vector = vector

        # Set up a cleanup() function to run on aborts.
        def cleanup():
            self._pdf_password = None
            renderer.cleanup(incl_extract=True)
        
        # If necessary, extract() will download the RMN. This part of
        # the process will take the first 50% of progress.
        x_path = renderer.extract(prog_cb=lambda x: prog_cb(x*50),
                                  abort_func=abort_func)

        if abort_func():
            cleanup()
            return

        # Good time to refresh the doc's metadata.
        self.load_all_meta_from_extract(x_path)

        # Rendering the PDF will take the last 50% of progress.
        # TODO: fix progress in document_render.py to output 0..1.
        renderer.render_pdf(filepath,
                            prog_cb=lambda x: prog_cb(50 + x*50),
                            abort_func=abort_func)
        cleanup()

        log.info('exported pdf')
        return True

    def save_text(self, filepath, fmt='txt-md', prog_cb=lambda x:(),
                  abort_func=lambda: False):
        # Exports the self as a text file to disk.
        # prog_cb should emit between 0-100.

        if abort_func():
            return

        renderer = DocRender(self)
        prog_cb(10)

        def cleanup():
            renderer.cleanup(incl_extract=True)
        x_path = renderer.extract(prog_cb=lambda x: (),
                                  abort_func=abort_func)
        if abort_func():
            cleanup()
            return

        self.load_all_meta_from_extract(x_path)
        prog_cb(20)
        renderer.render_text_as_markdown(filepath,
                                         prog_cb=lambda x: (prog_cb(20 + (x * .6))),
                                         abort_func=abort_func)
        cleanup()
        log.info('exported text')
        return True

    def save_snaphighlights(self, filepath, fmt='txt-md', prog_cb=lambda x:(),
                  abort_func=lambda: False):
        # Exports the self as a text file to disk.
        # prog_cb should emit between 0-100.

        if abort_func():
            return

        renderer = DocRender(self)
        prog_cb(10)

        def cleanup():
            renderer.cleanup(incl_extract=True)
        x_path = renderer.extract(prog_cb=lambda x: (),
                                  abort_func=abort_func)
        if abort_func():
            cleanup()
            return

        self.load_all_meta_from_extract(x_path)
        prog_cb(20)
        renderer.render_snaphighlights_as_text(filepath,
                                               prog_cb=lambda x: (prog_cb(20 + (x * .6))),
                                               abort_func=abort_func)
        cleanup()
        log.info('exported snap highlights')
        return True

