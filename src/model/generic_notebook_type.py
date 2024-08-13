'''
generic_notebook_type.py
This is the base class for Documents and Collections.

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

import log
from datetime import datetime
import uuid
import re
from pathlib import Path
import time


class GenericNotebookType:
    pathpfx = '$HOME/.local/share/remarkable/xochitl'

    # Child class should override this with either NotebookType
    # or CollectionType
    rm_type = ''

    @classmethod
    def get_sanitized_name(cls, name):
        sanitized = re.sub('[\/\\\!\@\#\$\%\^\&\*\~\|\:\;\?\`\’\“\'\"]',
                           '_',
                           name)
        return sanitized

    @classmethod
    def get_unique_filepath(cls, filepath):
        if filepath.exists():
            n = 2
            while True:
                newname = '{} ({}){}'.format(filepath.stem,
                                             n,
                                             filepath.suffix)
                new_filepath = Path(filepath.parent / newname)
                if not new_filepath.exists():
                    filepath = new_filepath
                    break
                n += 1
        return filepath

    def __init__(self, model, format_version=1):
        self.model = model
        self._iter_pool = None  # set by child class

        # These two properties, which are direct dicts from the
        # .content and .metadata backing files, are to remain internal!
        # RCU's code is being refactored to keep these original files
        # as close to stock as possible. It is not acceptable to "lint"
        # or otherwise modify them, because the manufacturer can add
        # additional properties at any time, which RCU should not
        # interfere with.
        self._content_dict = {}
        self._metadata_dict = {}

        
        ## TODO
        ## These ALL have to go!!!
        self.uuid = str(uuid.uuid4())
        self.deleted = False
        self.last_modified = str(round(time.time() * 1000))
        self.metadatamodified = True
        self.modified = True
        self.parent = None
        self.pinned = False
        self.synced = False
        self.version = 1
        self.visible_name = 'Untitled'

    def __str__(self):
        return '{}\t{}\t{}'.format(self.uuid,
                                   self.visible_name,
                                   self.last_modified)

    def from_dict(self, adict):
        def getprop(propname):
            return adict[propname] if propname in adict else None
        
        if 'id' in adict:
            self.uuid = adict['id']
        self.deleted = getprop('deleted')
        self.last_modified = getprop('lastModified')
        self.metadatamodified = getprop('metadatamodified')
        self.modified = getprop('modified')
        self.parent = getprop('parent')
        self.pinned = getprop('pinned')
        self.synced = getprop('synced')
        self.version = getprop('version') or 1
        self.visible_name = getprop('visibleName')
        if type(self).rm_type == 'DocumentType' and 'filetype' in adict:
            # Document-specific function...be careful with this. It gets
            # picked up from rcu.py, and is needed for loading document
            # type icons before the content dict is read. TODO - would
            # be better to instantiate not from just metadatadict, but
            # ALSO from contentdict!
            self.set_filetype(adict['filetype'])
        return self

    def as_dict(self):
        return {
            'deleted': self.deleted,
            'lastModified': self.last_modified,
            'metadatamodified': self.metadatamodified,
            'modified': self.modified,
            'parent': self.parent,
            'pinned': self.pinned,
            'synced': self.synced,
            'type': type(self).rm_type,
            'version': self.version,
            'visibleName': self.visible_name
            }

    def get_pin(self):
        return self.pinned

    def get_pretty_name(self):
        return self.visible_name

    def get_last_modified_date(self):
        # There is a bug in Windows that a user hit. Windows cannot cast
        # datetimes which are negative.
        try:
            date = datetime.fromtimestamp(int(self.last_modified) / 1000)
            return date
        except Exception:
            # Negative timestamps are set from the reMarkable Send From
            # Chrome browser plugin. Silently fail.
            return None

    def get_sanitized_filepath(self, ext=''):
        # ext should include a period, e.g. '.rmn'
        name = self.get_pretty_name()
        # If adjacent to another GenericType with the same pretty name,
        # this wil use the ID as part of the sanitized name (no
        # preference).
        for g in self._iter_pool:
            if g.parent == self.parent \
               and g.uuid != self.uuid \
               and g.get_pretty_name() == self.get_pretty_name():
                name += '-' + self.uuid[:8]
                break
        sanitized = self.get_sanitized_name(name)
        return Path(sanitized + ext)

    def delete(self, force=False):
        # Deletes self
        # In order to accomodate cloud users, we only can set the
        # deleted flag and let reMarkable's software take it the rest of
        # the way.
        if self.model.device_info['cloud_user'] and not force:
            # fw.3 gets a tombstone file--not self.deleted.
            self.deleted = True
            self.version += 1
            self.write_metadata_out()
            self.model.documents.discard(self)
        else:
            # Purge files immediately
            if not self.uuid or not len(self.uuid):
                log.error('warning: uuid is not set! aborting delete!')
                return
            cmd = 'rm -rf {}/{}*'.format(type(self).pathpfx, self.uuid)
            out, err = self.model.run_cmd(cmd)
            if len(err):
                log.error('problem deleting item', type(self).rm_type)
                log.error('problem command: {}'.format(cmd))
                log.error(err)
                return
            self.model.documents.discard(self)

    def pin(self):
        self.pinned = True
        self.write_metadata_out()

    def unpin(self):
        self.pinned = False
        self.write_metadata_out()

    def rename(self, newname=None):
        if not newname or '' == newname:
            return False
        self.visible_name = newname
        self.version += 1
        self.write_metadata_out()
        return True

    def move_to_parent(self, parent_collection=None):
        # Moves this item into a parent collection
        # Todo...some type checking
        if not parent_collection:
            parent_id = ''
        else:
            parent_id = parent_collection.uuid

        # If the parent doesn't change, abort
        if self.parent == parent_id:
            return False

        self.parent = parent_id
        self.version += 1
        self.write_metadata_out()
        return True

    def estimate_size(self, abort_func=lambda: ()):
        # Child class must override!
        assert('estimate_size not implemented!')

    def save_archive(self, filepath, est_bytes,
                     bytes_cb=lambda x=None: (),
                     abort_func=lambda x=None: ()):
        # Child class must override!
        assert('save_archive not implemented!')

    def save_original_file(self, filepath, filetype='pdf',
                           prog_cb=lambda x: (),
                           abort_func=lambda: False):
        # Child class must override!
        assert('save_original_file not implemented!')

    def save_pdf(self, filepath, vector=None, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        # Child class must override!
        assert('save_pdf not implemented!')

    def save_rm_pdf(self, filepath, prog_cb=lambda x: (),
                    abort_func=lambda: False):
        # Child class must override!
        assert('save_rm_pdf not implemented!')

    #### TODO #####
    # write_metadata_out()
    # write_content_out()
    ###############
