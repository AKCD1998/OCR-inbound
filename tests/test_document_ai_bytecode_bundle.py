"""Synthetic Python packages only; no SDK, models, business data or HQ jobs."""
from contextlib import contextmanager
import copy
import hashlib
import importlib
import importlib.machinery
import importlib.resources
import importlib.resources.readers
import importlib.readers
import importlib.util
import json
import marshal
import os
from pathlib import Path
import py_compile
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULES=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(MODULES))
import bytecode_bundle as bundle
import python_cache as cache
import component_common as common


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder).resolve();site=root/'site';pkg=site/'bbundle_test_pkg';pkg.mkdir(parents=True)
        sources=[pkg/'__init__.py',pkg/'child.py',pkg/'late.py']
        sources[0].write_text('from .child import answer\n');sources[1].write_text('answer=42\n');sources[2].write_text('answer=99\n')
        (pkg/'sample.txt').write_bytes(b'original resource')
        pycs=root/'cache';pycs.mkdir();records=[]
        for n,path in enumerate(sources[:2]):
            pyc=pycs/(str(n)+'.pyc');py_compile.compile(str(path),cfile=str(pyc),doraise=True)
            records.append({'source':common.pin(path),'cache':common.pin(pyc),'compile_source_bytes_sha256':common.sha(path)})
        manifest={'contract':cache.CONTRACT,'status':'COMPLETE','python':common.pin(sys.executable),
             'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
             'cache_root':str(pycs),'cached_modules':records,'cached_module_count':len(records),
             'cache_bytes':sum(Path(r['cache']['path']).stat().st_size for r in records)}
        index={'contract':cache.SOURCE_INDEX,'python':manifest['python'],'sources':[{'source':common.pin(p)} for p in sources]}
        indexfile=bundle.create_blob(manifest,index,root/'bundle',[str(site)])
        value=SimpleNamespace(root=root,site=site,pkg=pkg,manifest=manifest,index=index,blobindex=common.read(indexfile),sources=sources)
        before=(importlib.machinery.SourceFileLoader.get_data,importlib.machinery.SourceFileLoader.get_code,sys.pycache_prefix,list(sys.meta_path))
        old_write=sys.dont_write_bytecode;sys.dont_write_bytecode=True
        sys.path.insert(0,str(site));activation=None
        try:
            value.activate=lambda:bundle.BlobActivation(manifest,index,value.blobindex)
            yield value
        finally:
            # Tests always close their own activation; this verifies no hidden hook leak.
            for name in list(sys.modules):
                if name=='bbundle_test_pkg' or name.startswith('bbundle_test_pkg.'):sys.modules.pop(name,None)
            sys.path.remove(str(site))
            sys.dont_write_bytecode=old_write
            assert importlib.machinery.SourceFileLoader.get_data is before[0]
            assert importlib.machinery.SourceFileLoader.get_code is before[1]
            assert sys.pycache_prefix==before[2] and sys.meta_path==before[3]


class BundleContracts(unittest.TestCase):
    def test_package_relative_import_filenames_resources_and_live_reload(self):
        with fixture() as f:
            active=f.activate()
            try:
                module=importlib.import_module('bbundle_test_pkg')
                child=sys.modules['bbundle_test_pkg.child']
                self.assertEqual(module.answer,42)
                self.assertEqual(Path(module.__file__),f.sources[0]);self.assertEqual(list(module.__path__),[str(f.pkg)])
                self.assertEqual(module.__spec__.origin,str(f.sources[0]))
                self.assertEqual(child.__loader__.get_code(child.__name__).co_filename,str(f.sources[1]))
                self.assertEqual(importlib.resources.files(module).joinpath('sample.txt').read_bytes(),b'original resource')
                self.assertGreaterEqual(active.observed['source_checks'],3)
                # Timestamp/length tricks cannot bypass a fresh LIVE source hash.
                f.sources[1].write_text('answer=43\n')
                with self.assertRaises(ImportError):child.__loader__.get_code(child.__name__)
            finally:active.close()

    def test_actual_returned_blob_bytes_tamper_is_rejected_before_marshal(self):
        with fixture() as f:
            original=f.blobindex['blob']['path']
            active=f.activate()
            original_mapping=active.mapping
            try:
                # Simulates a changed delivery buffer after the file precheck.
                active.mapping=b'x'*f.blobindex['blob_bytes']
                loader=bundle.ApprovedLoader('bbundle_test_pkg',str(f.sources[0]),active)
                with self.assertRaises(ImportError):loader.get_code('bbundle_test_pkg')
            finally:
                # Restore mmap handle for deterministic close; never alter original blob.
                active.mapping=original_mapping;active.close()
            self.assertEqual(common.sha(original),f.blobindex['blob']['sha256'])

    def test_uncached_approved_source_fallback_and_unknown_existing_pyc(self):
        with fixture() as f:
            active=f.activate()
            try:
                self.assertIsNone(active.finder.find_spec('not_registered_optional_module'))
                self.assertIsNone(active.finder.find_spec('bbundle_test_pkg.late',[str(f.pkg)]))
                parent=importlib.import_module('bbundle_test_pkg');late=importlib.import_module('bbundle_test_pkg.late')
                self.assertEqual(late.answer,99)
                loader=importlib.machinery.SourceFileLoader('bbundle_test_pkg.late',str(f.sources[2]))
                unknown=Path(f.manifest['cache_root'])/'foreign.pyc';unknown.write_bytes(Path(f.manifest['cached_modules'][0]['cache']['path']).read_bytes())
                with self.assertRaises(ImportError):loader.get_data(str(unknown))
                with self.assertRaises(OSError):loader.get_data(str(unknown.with_name('missing.pyc')))
            finally:active.close()

    def test_parent_path_mismatch_and_bootstrap_reentry_abstain(self):
        with fixture() as f:
            active=f.activate()
            try:
                self.assertIsNone(active.finder.find_spec('bbundle_test_pkg.child',[str(f.root/'foreign')]))
                self.assertIsNone(active.finder.find_spec('bbundle_test_pkg.child',[str(f.pkg),str(f.root/'namespace')]))
                active.executing.add('bbundle_test_pkg')
                self.assertIsNone(active.finder.find_spec('bbundle_test_pkg'))
                active.executing.clear()
            finally:active.close()

    def test_loader_name_check_and_top_level_priority_are_preserved(self):
        with fixture() as f:
            earlier=f.root/'earlier';earlier.mkdir();(earlier/'bbundle_test_pkg.py').write_text('foreign=True\n')
            sys.path.insert(0,str(earlier));active=f.activate()
            try:
                self.assertIsNone(active.finder.find_spec('bbundle_test_pkg'))
                normal=importlib.machinery.PathFinder.find_spec('bbundle_test_pkg')
                self.assertEqual(Path(normal.origin),earlier/'bbundle_test_pkg.py')
                loader=bundle.ApprovedLoader('correct_name',str(f.sources[0]),active)
                with self.assertRaises(ImportError):loader.get_code('wrong_name')
            finally:active.close();sys.path.remove(str(earlier))

    def test_earlier_custom_finder_redirect_keeps_original_guarded_semantics(self):
        with fixture() as f:
            class Redirect(importlib.abc.MetaPathFinder):
                def find_spec(self,fullname,path=None,target=None):
                    if fullname!='bbundle_test_pkg':return None
                    loader=importlib.machinery.SourceFileLoader(fullname,str(f.sources[1]))
                    return importlib.util.spec_from_file_location(fullname,str(f.sources[1]),loader=loader)
            redirect=Redirect();sys.meta_path.insert(0,redirect);active=f.activate()
            try:
                self.assertLess(sys.meta_path.index(redirect),sys.meta_path.index(active.finder))
                self.assertLess(sys.meta_path.index(importlib.machinery.FrozenImporter),sys.meta_path.index(active.finder))
                module=importlib.import_module('bbundle_test_pkg')
                self.assertEqual(module.answer,42);self.assertEqual(Path(module.__file__),f.sources[1])
                self.assertEqual(module.__loader__.get_code(module.__name__).co_filename,str(f.sources[1]))
                f.sources[1].write_text('answer=43\n')
                with self.assertRaises(ImportError):module.__loader__.get_code(module.__name__)
            finally:active.close();sys.meta_path.remove(redirect)

    def test_module_map_ambiguity_and_native_module_precedence_abstain(self):
        with fixture() as f:
            suffix=importlib.machinery.EXTENSION_SUFFIXES[0]
            plain=f.site/'same.py';plain.write_text('answer=1\n')
            records=[{'source':common.pin(plain)},*f.index['sources']]
            modules,ambiguous,_,excluded=bundle.module_mapping(records,[str(f.site)],[str(f.site/('same'+suffix)),str(f.site/('bbundle_test_pkg'+suffix))])
            self.assertNotIn('same',modules);self.assertIn('same',excluded)
            self.assertIn('bbundle_test_pkg',modules)  # package directory wins same-root module.pyd
            other=f.root/'other';other.mkdir();alias=other/'same.py';alias.write_text('answer=2\n')
            modules,ambiguous,_,_=bundle.module_mapping(records+[{'source':common.pin(alias)}],[str(f.site),str(other)])
            self.assertNotIn('same',modules);self.assertIn('same',ambiguous)

    def test_registered_child_abstains_to_normal_native_extension_finder(self):
        with fixture() as f:
            native=str(f.pkg/('child'+importlib.machinery.EXTENSION_SUFFIXES[0]))
            modules,ambiguous,_,excluded=bundle.module_mapping(f.index['sources'],[str(f.site)],[native])
            f.blobindex.update(modules=modules,ambiguous_module_names=ambiguous,native_extension_paths=[native],native_precedence_abstentions=excluded)
            class NativeLoader(importlib.abc.Loader):
                def create_module(self,spec):return None
                def exec_module(self,module):module.answer=7
            class NativeFallback(importlib.abc.MetaPathFinder):
                def find_spec(self,fullname,path=None,target=None):
                    if fullname=='bbundle_test_pkg.child':return importlib.machinery.ModuleSpec(fullname,NativeLoader(),origin=native)
            fallback=NativeFallback();active=f.activate()
            sys.meta_path.insert(sys.meta_path.index(importlib.machinery.PathFinder),fallback)
            try:
                self.assertIsNone(active.finder.find_spec('bbundle_test_pkg.child',[str(f.pkg)]))
                module=importlib.import_module('bbundle_test_pkg')
                self.assertEqual(module.answer,7)
                self.assertEqual(sys.modules['bbundle_test_pkg.child'].__spec__.origin,native)
            finally:sys.meta_path.remove(fallback);active.close()

    @unittest.skipUnless(os.name=='nt','Windows extension suffix normalization')
    def test_uppercase_windows_PYD_keeps_native_precedence(self):
        with fixture() as f:
            suffix=importlib.machinery.EXTENSION_SUFFIXES[-1]
            native=f.pkg/('child'+suffix.upper());native.touch()
            modules,_,_,excluded=bundle.module_mapping(f.index['sources'],[str(f.site)],[str(native)])
            self.assertNotIn('bbundle_test_pkg.child',modules)
            self.assertIn('bbundle_test_pkg.child',excluded)
            normal=importlib.machinery.PathFinder.find_spec('bbundle_test_pkg.child',[str(f.pkg)])
            self.assertIsInstance(normal.loader,importlib.machinery.ExtensionFileLoader)

    def test_invalid_pyc_headers_payload_type_and_filename_rejected(self):
        with fixture() as f:
            raw=Path(f.manifest['cached_modules'][0]['cache']['path']).read_bytes()
            self.assertEqual(bundle.decode_pyc(raw,str(f.sources[0])).co_filename,str(f.sources[0]))
            for value in (b'bad',b'bad!'+raw[4:],raw[:4]+(4).to_bytes(4,'little')+raw[8:],raw[:16]+marshal.dumps(123),raw+b'trailing'):
                with self.assertRaises(ImportError):bundle.decode_pyc(value,str(f.sources[0]))
            with self.assertRaises(ImportError):bundle.decode_pyc(raw,str(f.sources[1]))

    def test_partial_activation_failure_restores_all_hooks_and_prefix(self):
        with fixture() as f:
            before=(importlib.machinery.SourceFileLoader.get_data,importlib.machinery.SourceFileLoader.get_code,sys.pycache_prefix,list(sys.meta_path))
            with patch.object(cache,'install_lazy_checks',side_effect=ValueError('forced after mmap and supplier install')):
                with self.assertRaises(ValueError):f.activate()
            self.assertEqual((importlib.machinery.SourceFileLoader.get_data,importlib.machinery.SourceFileLoader.get_code,sys.pycache_prefix,list(sys.meta_path)),before)

    def test_producer_rejects_source_mutation_and_compile_lineage(self):
        with fixture() as f:
            changed=copy.deepcopy(f.manifest);changed['cached_modules'][0]['compile_source_bytes_sha256']='0'*64
            with self.assertRaises(ValueError):bundle.create_blob(changed,f.index,f.root/'wrong-compile',[str(f.site)])
            f.sources[0].write_text('changed source\n')
            with self.assertRaises(ValueError):bundle.create_blob(f.manifest,f.index,f.root/'wrong-live-source',[str(f.site)])


if __name__=='__main__':unittest.main()
