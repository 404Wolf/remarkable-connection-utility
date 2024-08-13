'''
collection.py
This is the model for notebook Collections.

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

import json
from .generic_notebook_type import GenericNotebookType


class Collection(GenericNotebookType):
    rm_type = 'CollectionType'
    
    def __init__(self, model):
        super(type(self), self).__init__(model)

        self._iter_pool = model.collections

        # Other metadata keys
        self.visible_name = 'Untitled Collection'

    def estimate_size(self, abort_func=lambda: ()):
        # Assume that folders don't take up any space, so recursively
        # add up the documents contained within. Have to search inside
        # the model to find children, both collections and documents.
        totalsize = 0
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                totalsize += c.estimate_size(abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                totalsize += d.estimate_size(abort_func)
        return totalsize
        
    def write_metadata_out(self):
        js = json.dumps(self.as_dict(), sort_keys=True, indent=4)
        cmd = 'cat > "{}/{}.metadata"'.format(type(self).pathpfx,
                                              self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(js)
        stdin.close()

        # TODO
        # The content_dict used to be written out here, but I moved it
        # to a separate function. This call is vestigial. Still need
        # to investigate the effect of this.
        self.write_content_out()

    def write_content_out(self):
        content_js = json.dumps(self._content_dict,
                                sort_keys=True, indent=4)
        cmd = 'cat > "{}/{}.content"'.format(type(self).pathpfx,
                                             self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(content_js)
        stdin.close()

    def get_num_child_documents(self):
        # Recursively adds the total of the number of Documents which
        # are a descendant of this node.
        total = 0
        for c in self.model.collections:
            if c.parent == self.uuid:
                total += c.get_num_child_documents()
        for d in self.model.documents:
            if d.parent == self.uuid:
                total += 1
        return total

    def save_archive(self, filepath, est_bytes,
                     bytes_cb=lambda x=None: (),
                     abort_func=lambda x=None: ()):
        # Create the directory on-disk (if it doesn't already exist).
        # Then, fill it with the actual document archives.
        
        # Todo: visible_name needs sanitation!
        filepath.mkdir(parents=True, exist_ok=True)

        btransferred = 0

        def emitthrough(bytecount):
            bytes_cb(btransferred + bytecount)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                btransferred += c.save_archive(
                    filepath / c.get_sanitized_filepath(),
                    est_bytes, emitthrough, abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                # No unique names here! Users expect to use this as a
                # way to dump their files, overwriting the previous
                # backup.
                btransferred += d.save_archive(
                    filepath / d.get_sanitized_filepath('.rmn'),
                    est_bytes, emitthrough, abort_func)

        return btransferred

    def save_pdf(self, filepath, vector=True, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_pdf(
                    filepath / c.get_sanitized_filepath(),
                    vector=vector, prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                # Needs to have unique during batch exports to prevent
                # clobbering. This is _not_ in document.py, because
                # users expect to be able to replace existing files in
                # one-offs. It used to be, in c. ~2021 versions of RCU,
                # that unique filenames were always given. Users vocally
                # wanted it _to_ clobber, because they use Ctrl+A to
                # dump their documents as a backup, and expect the old
                # backup to be overwritten.
                fp = self.get_unique_filepath(
                    filepath / d.get_sanitized_filepath('.pdf'))
                d.save_pdf(
                    fp,
                    vector=vector, prog_cb=progshim,
                    abort_func=abort_func)
                docs_done += 1

        return docs_done

    def save_original_file(self, filepath, filetype='pdf',
                           prog_cb=lambda x: (),
                           abort_func=lambda: False):
        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_original_file(
                    filepath / c.get_sanitized_filepath(),
                    filetype=filetype,
                    prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                # Needs to have unique during batch exports to prevent
                # clobbering. This is _not_ in document.py, because
                # users expect to be able to replace existing files in
                # one-offs. It used to be, in c. ~2021 versions of RCU,
                # that unique filenames were always given. Users vocally
                # wanted it _to_ clobber, because they use Ctrl+A to
                # dump their documents as a backup, and expect the old
                # backup to be overwritten.
                fp = self.get_unique_filepath(
                    filepath / d.get_sanitized_filepath('.'+filetype))
                d.save_original_file(
                    fp,
                    filetype=filetype,
                    prog_cb=progshim,
                    abort_func=abort_func)
                docs_done += 1

        return docs_done

    def save_rm_pdf(self, filepath, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        return self.save_rmwebui_file(filepath=filepath,
                                      filetype='pdf',
                                      prog_cb=prog_cb,
                                      abort_func=abort_func)

    def save_rm_rmdoc(self, filepath, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        return self.save_rmwebui_file(filepath=filepath,
                                      filetype='rmdoc',
                                      prog_cb=prog_cb,
                                      abort_func=abort_func)

    def save_rmwebui_file(self, filepath, filetype='pdf',
                        prog_cb=lambda x: (),
                        abort_func=lambda: False):
        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_rmwebui_file(
                    filepath / c.get_sanitized_filepath(),
                    filetype=filetype,
                    prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                # Needs to have unique during batch exports to prevent
                # clobbering. This is _not_ in document.py, because
                # users expect to be able to replace existing files in
                # one-offs. It used to be, in c. ~2021 versions of RCU,
                # that unique filenames were always given. Users vocally
                # wanted it _to_ clobber, because they use Ctrl+A to
                # dump their documents as a backup, and expect the old
                # backup to be overwritten.
                fp = self.get_unique_filepath(
                    filepath / d.get_sanitized_filepath('.'+filetype))
                d.save_rmwebui_file(
                    fp,
                    filetype=filetype,
                    prog_cb=progshim,
                    abort_func=abort_func)
                docs_done += 1

        return docs_done

    def save_text(self, filepath, fmt='txt-md', prog_cb=lambda x:(),
                  abort_func=lambda: False):
        if abort_func():
            return

        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)

        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_text(
                    filepath / c.get_sanitized_filepath(),
                    prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                # Needs to have unique during batch exports to prevent
                # clobbering. This is _not_ in document.py, because
                # users expect to be able to replace existing files in
                # one-offs. It used to be, in c. ~2021 versions of RCU,
                # that unique filenames were always given. Users vocally
                # wanted it _to_ clobber, because they use Ctrl+A to
                # dump their documents as a backup, and expect the old
                # backup to be overwritten.
                fp = self.get_unique_filepath(
                    filepath / d.get_sanitized_filepath('.md'))
                d.save_text(fp,
                            prog_cb=progshim,
                            abort_func=abort_func)
                docs_done += 1

        return docs_done

    def save_snaphighlights(self, filepath, fmt='txt-md', prog_cb=lambda x:(),
                            abort_func=lambda: False):
        # TODO: this is a clone of save_text. These should probably
        # be consolidated into a generic function as they share 99%
        # the same logic.

        if abort_func():
            return

        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)

        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_snaphighlights(
                    filepath / c.get_sanitized_filepath(),
                    prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                # Needs to have unique during batch exports to prevent
                # clobbering. This is _not_ in document.py, because
                # users expect to be able to replace existing files in
                # one-offs. It used to be, in c. ~2021 versions of RCU,
                # that unique filenames were always given. Users vocally
                # wanted it _to_ clobber, because they use Ctrl+A to
                # dump their documents as a backup, and expect the old
                # backup to be overwritten.
                fp = self.get_unique_filepath(
                    filepath / d.get_sanitized_filepath('.md'))
                d.save_snaphighlights(fp,
                            prog_cb=progshim,
                            abort_func=abort_func)
                docs_done += 1

        return docs_done
