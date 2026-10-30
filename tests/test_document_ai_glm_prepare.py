"""Bounded preparation regressions; no network, native models or real images."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import glm_prepare_worker as worker


class GlmPreparationTests(unittest.TestCase):
    def artifact(self,data=b'measured bytes'):
        return {'role':'decoder','filename':'model.gguf','url':'https://huggingface.co/owner/model/resolve/revision/model.gguf',
                'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

    def test_unselected_hosts_and_unbounded_artifacts_refused_before_network(self):
        for update in ({'url':'http://huggingface.co/model'},{'url':'https://unselected.example/model'},
                       {'filename':'../outside'},{'filename':'C:\\outside'},
                       {'bytes':worker.MAX_DOWNLOAD_BYTES+1},{'bytes':True},{'sha256':'x'*64}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                worker.validated_artifact({**self.artifact(),**update})

    def test_verified_download_records_actual_bytes_without_loading_weights(self):
        with tempfile.TemporaryDirectory() as name,patch.object(worker.urllib.request,'urlopen',return_value=io.BytesIO(b'measured bytes')):
            result=worker.download(self.artifact(),Path(name),lambda *a,**k:None)
            self.assertEqual(14,result['bytes'])
            self.assertEqual(self.artifact()['sha256'],result['file']['sha256'])
            self.assertFalse((Path(name)/'model.gguf.partial').exists())

    def test_bad_or_oversize_download_is_never_named_a_complete_model(self):
        for data in (b'wrong bytes',b'measured bytes plus'):
            with self.subTest(data=data),tempfile.TemporaryDirectory() as name,patch.object(worker.urllib.request,'urlopen',return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError):worker.download(self.artifact(),Path(name),lambda *a,**k:None)
                self.assertFalse((Path(name)/'model.gguf').exists())
                self.assertTrue((Path(name)/'model.gguf.partial').exists())

    def test_archive_traversal_is_refused_before_extraction(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);archive=folder/'backend.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside.txt','not allowed')
            with self.assertRaises(ValueError):worker.extract_backend(archive,folder/'backend')
            self.assertFalse((folder/'outside.txt').exists())

    def test_backend_bundle_is_pinned_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);archive=folder/'backend.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('bin/llama-server.exe',b'synthetic-server')
                z.writestr('bin/llama-quantize.exe',b'synthetic-quantizer')
                z.writestr('bin/ggml-cpu.dll',b'synthetic-library')
            result=worker.extract_backend(archive,folder/'backend')
            self.assertEqual(3,len(result['files']))
            self.assertEqual(hashlib.sha256(b'synthetic-server').hexdigest(),result['server']['sha256'])
            with self.assertRaises(FileExistsError):worker.extract_backend(archive,folder/'backend')

    def test_backend_case_alias_and_trailing_dot_cannot_overwrite_a_member(self):
        for duplicate in ('bin/LLAMA-SERVER.exe','bin/llama-server.exe.','bin/llama-server.exe '):
            with self.subTest(duplicate=duplicate),tempfile.TemporaryDirectory() as name:
                folder=Path(name);archive=folder/'backend.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('bin/llama-server.exe',b'first')
                    z.writestr(duplicate,b'replacement')
                with self.assertRaises(ValueError):worker.extract_backend(archive,folder/'backend')
                self.assertFalse((folder/'backend/bin/llama-server.exe').exists())


if __name__=='__main__':unittest.main()
