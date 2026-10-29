"""Read-only PYC delivery blob; every code load still verifies live source bytes.

No SDK import, image, weights, compilation or model operation belongs here.
The finder avoids repeated Python-file discovery for unambiguous approved code.
Native extensions and package resources retain their original physical paths.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import keyword
import marshal
import mmap
import os
from pathlib import Path
import sys
import types
from component_common import checked,pin,read,save,sha,verify_admission

CONTRACT='document-ai-PYC-delivery-blob.v1'
MODE='PYC_blob_with_live_source_SHA_on_every_load'


def key(path):return os.path.normcase(os.path.abspath(os.fsdecode(path)))


def inside(path,root):
    try:return os.path.commonpath([key(path),key(root)])==key(root)
    except ValueError:return False


def extension_suffix(path):
    value=os.path.normcase(str(path))
    return next((s for s in importlib.machinery.EXTENSION_SUFFIXES if value.endswith(os.path.normcase(s))),None)


def decode_pyc(data,source):
    if len(data)<16 or data[:4]!=importlib.util.MAGIC_NUMBER:raise ImportError('Invalid approved PYC header/magic')
    if int.from_bytes(data[4:8],'little') not in (0,1,3):raise ImportError('Unsupported PYC header flags')
    stream=io.BytesIO(data[16:])
    try:code=marshal.load(stream)
    except (EOFError,ValueError,TypeError) as error:raise ImportError('Invalid approved PYC payload') from error
    if not isinstance(code,types.CodeType) or stream.read(1):raise ImportError('Approved PYC must contain exactly one code object')
    pending=[code]
    while pending:
        part=pending.pop()
        if key(part.co_filename)!=key(source):raise ImportError('PYC original co_filename differs from approved source')
        pending.extend(x for x in part.co_consts if isinstance(x,types.CodeType))
    return code


def module_mapping(sources,roots,native_paths=()):
    """Pure lexical module map, including approved uncached sources for ambiguity."""
    candidates={};unmapped=[]
    ordered=sorted({key(x):os.path.abspath(str(x)) for x in roots}.values(),key=len,reverse=True)
    for record in sources:
        source=record['source'];path=source['path'];root=next((r for r in ordered if inside(path,r)),None)
        if root is None:unmapped.append(source);continue
        relative=os.path.relpath(os.path.abspath(path),root);parts=Path(relative).parts
        if not parts or not os.path.normcase(parts[-1]).endswith('.py'):unmapped.append(source);continue
        package=os.path.normcase(parts[-1])=='__init__.py'
        names=list(parts[:-1]) if package else [*parts[:-1],parts[-1][:-3]]
        if not names or not all(n.isidentifier() and not keyword.iskeyword(n) for n in names):unmapped.append(source);continue
        fullname='.'.join(names);parent=str(Path(path).parent.parent if package else Path(path).parent)
        entry={'fullname':fullname,'source':source,'is_package':package,'search_root':root,
               'parent_path':parent if '.' in fullname else root}
        candidates.setdefault(fullname,{})[key(path)]=entry
    ambiguous={name:sorted(items) for name,items in candidates.items() if len(items)!=1}
    selected={name:next(iter(items.values())) for name,items in candidates.items() if len(items)==1}
    excluded={}
    for path in native_paths:
        root=next((r for r in ordered if inside(path,r)),None)
        suffix=extension_suffix(path)
        if root is None or suffix is None:continue
        parts=list(Path(os.path.relpath(os.path.abspath(path),root)).parts);stem=parts[-1][:-len(suffix)]
        native_package=os.path.normcase(stem)=='__init__';names=parts[:-1] if native_package else [*parts[:-1],stem]
        fullname='.'.join(names);entry=selected.get(fullname)
        if entry is None:continue
        # FileFinder checks a package directory before a same-root module.pyd.
        if entry['is_package'] and not native_package and key(entry['search_root'])==key(root):continue
        excluded.setdefault(fullname,[]).append(str(path))
    for name in excluded:selected.pop(name,None)
    return selected,ambiguous,unmapped,excluded


def native_inventory(source_index):
    """Read accepted RECORD metadata plus stdlib DLL directory once, no SDK."""
    paths=set()
    for origin in source_index['distribution_RECORD_origins']:
        record=checked(origin['RECORD']);site=record.parent.parent
        for relative,*rest in csv.reader(record.read_text(encoding='utf-8-sig').splitlines()):
            if extension_suffix(relative) is not None:paths.add(os.path.abspath(str(site/relative)))
    dll_root=Path(sys.base_prefix)/'DLLs'
    if dll_root.is_dir():
        for path in dll_root.iterdir():
            if extension_suffix(path) is not None:paths.add(str(path))
    return sorted(paths)


def create_blob(manifest,source_index,root,roots,expected_records=None,expected_bytes=None,native_paths=()):
    from python_cache import cache_identity,SOURCE_INDEX
    cache_identity(manifest)
    if source_index.get('contract')!=SOURCE_INDEX or source_index.get('python')!=manifest['python']:raise ValueError('Source index/interpreter differs')
    approved={key(x['source']['path']):x['source']['sha256'] for x in source_index['sources']}
    modules,ambiguous,unmapped,excluded=module_mapping(source_index['sources'],roots,native_paths)
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    entries=[];source_keys=set();cache_keys=set();offset=0;blob=root/'PYC_BYTES.blob'
    with blob.open('xb') as output:
        for record in manifest['cached_modules']:
            source,cache=record['source'],record['cache'];source_key=key(source['path']);cache_key=key(cache['path'])
            if source_key in source_keys or cache_key in cache_keys or not inside(cache['path'],manifest['cache_root']):raise ValueError('Duplicate or escaped PYC binding')
            if approved.get(source_key)!=source['sha256'] or record.get('compile_source_bytes_sha256')!=source['sha256']:raise ValueError('Original source/compile/approval pins differ')
            checked(source)  # LIVE installed source at production; no source payload is stored.
            data=Path(cache['path']).read_bytes()  # Exactly one PYC read, hash these returned bytes.
            if hashlib.sha256(data).hexdigest()!=cache['sha256']:raise ValueError('Original returned PYC bytes differ')
            decode_pyc(data,source['path'])
            output.write(data);entries.append({'source':source,'cache':cache,'offset':offset,'length':len(data),
                 'compile_source_bytes_sha256':record['compile_source_bytes_sha256']})
            offset+=len(data);source_keys.add(source_key);cache_keys.add(cache_key)
        output.flush();os.fsync(output.fileno())
    if len(entries)!=manifest['cached_module_count'] or expected_records is not None and len(entries)!=expected_records:raise ValueError('Actual PYC record count differs')
    if offset!=manifest['cache_bytes'] or expected_bytes is not None and offset!=expected_bytes:raise ValueError('Actual PYC-only payload bytes differ')
    index={'contract':CONTRACT,'python':manifest['python'],'cache_tag':manifest['cache_tag'],'bytecode_magic':manifest['bytecode_magic'],
           'blob':pin(blob),'blob_bytes':offset,'entries':entries,'record_count':len(entries),'source_payload_bytes':0,
           'module_roots':list(roots),'modules':modules,'ambiguous_module_names':ambiguous,'unmapped_source_count':len(unmapped),
           'native_extension_paths':list(native_paths),'native_precedence_abstentions':excluded,
           'live_source_SHA_verified_on_every_cached_load':True,'source_or_code_substitutions':False,
           'new_model_calls':0,'source_image_decodes':0,'optimizer_updates':0}
    path=root/'BLOB_INDEX.json';save(path,index);return path


class BlobActivation:
    def __init__(self,manifest,source_index,index,loader_type=importlib.machinery.SourceFileLoader):
        self.manifest=manifest;self.loader_type=loader_type;self.original_data=loader_type.get_data;self.original_code=loader_type.get_code
        self.old_prefix=sys.pycache_prefix;self.finder=None;self.stream=None;self.mapping=None;self.closed=False;self.executing=set()
        self.entries={};self.sources={};self.observed=None
        try:
            self.validate_index(index,source_index)
            self.stream=open(index['blob']['path'],'rb');self.mapping=mmap.mmap(self.stream.fileno(),0,access=mmap.ACCESS_READ)
            if len(self.mapping)!=index['blob_bytes']:raise ValueError('Pinned PYC blob length differs')
            def supplied(loader,path):
                record=self.entries.get(key(path))
                if record is None:return self.original_data(loader,path)
                return self.mapping[record['offset']:record['offset']+record['length']]
            loader_type.get_data=supplied
            from python_cache import install_lazy_checks
            self.observed=install_lazy_checks(manifest,source_index,loader_type)
            self.observed.update(PYC_blob_delivery=True,live_installed_source_on_every_code_load=True,cached_get_code_shortcuts=0,
                                 module_finder_hits=0,ambiguous_module_names_abstained=len(index['ambiguous_module_names']))
            def get_code(loader,fullname):
                if loader.name!=fullname:raise ImportError('Source loader name differs from requested fullname')
                record=self.sources.get(key(loader.path));entry=self.modules.get(fullname)
                if record is None or entry is None:return self.original_code(loader,fullname)
                if key(entry['source']['path'])!=key(loader.path) or not self.paths_match(entry,self.parent_paths(fullname)):
                    return self.original_code(loader,fullname)
                # Mandatory guarded get_data: actual returned PYC SHA + paired LIVE source SHA.
                data=loader.get_data(record['cache']['path'])
                code=decode_pyc(data,record['source']['path']);self.observed['cached_get_code_shortcuts']+=1
                return code
            loader_type.get_code=get_code
            self.finder=ApprovedFinder(self)
            position=next(i for i,finder in enumerate(sys.meta_path) if finder is importlib.machinery.PathFinder)
            sys.meta_path.insert(position,self.finder)
            sys.pycache_prefix=manifest['cache_root']
        except BaseException:
            self.close();raise

    def validate_index(self,index,source_index):
        if index.get('contract')!=CONTRACT or index.get('python')!=self.manifest['python'] or index.get('cache_tag')!=sys.implementation.cache_tag or index.get('bytecode_magic')!=importlib.util.MAGIC_NUMBER.hex():raise ValueError('PYC blob interpreter identity differs')
        if index.get('source_payload_bytes')!=0 or index.get('live_source_SHA_verified_on_every_cached_load') is not True:raise ValueError('Only PYC delivery with live source verification is selected')
        checked(index['blob'])
        expected={key(x['cache']['path']):x for x in self.manifest['cached_modules']};offset=0
        for item in index['entries']:
            cache_key=key(item['cache']['path']);old=expected.get(cache_key);source_key=key(item['source']['path'])
            if old is None or any(item.get(k)!=old.get(k) for k in ('source','cache','compile_source_bytes_sha256')):raise ValueError('PYC blob lineage differs')
            if cache_key in self.entries or source_key in self.sources or type(item['offset']) is not int or type(item['length']) is not int or item['offset']!=offset or item['length']<16:raise ValueError('Invalid PYC blob ranges/duplicates')
            self.entries[cache_key]=item;self.sources[source_key]=item;offset+=item['length']
        if set(self.entries)!=set(expected) or offset!=index['blob_bytes'] or len(expected)!=index['record_count']:raise ValueError('Exact PYC blob inventory required')
        modules,ambiguous,unmapped,excluded=module_mapping(source_index['sources'],index['module_roots'],index['native_extension_paths'])
        if modules!=index['modules'] or ambiguous!=index['ambiguous_module_names'] or excluded!=index['native_precedence_abstentions']:raise ValueError('Module map differs from approved source index')
        self.modules=modules

    def parent_paths(self,fullname):
        if '.' not in fullname:return sys.path
        parent=sys.modules.get(fullname.rpartition('.')[0]);return getattr(parent,'__path__',None)

    def paths_match(self,entry,paths):
        wanted=key(entry['parent_path'])
        if paths is None:return False
        actual={key(x) for x in paths}
        if '.' in entry['fullname']:
            return actual=={wanted}
        return wanted in actual

    def close(self):
        if self.closed:return
        self.closed=True
        if self.finder is not None and self.finder in sys.meta_path:sys.meta_path.remove(self.finder)
        self.loader_type.get_data=self.original_data;self.loader_type.get_code=self.original_code;sys.pycache_prefix=self.old_prefix
        if self.mapping is not None:self.mapping.close()
        if self.stream is not None:self.stream.close()


class ApprovedLoader(importlib.machinery.SourceFileLoader):
    def __init__(self,name,path,activation):super().__init__(name,path);self.activation=activation
    def exec_module(self,module):
        self.activation.executing.add(self.name)
        try:return super().exec_module(module)
        finally:self.activation.executing.remove(self.name)


class ApprovedFinder(importlib.abc.MetaPathFinder):
    def __init__(self,activation):self.activation=activation
    def find_spec(self,fullname,path=None,target=None):
        active=self.activation
        # A registered package may temporarily reimport its native extension
        # under the same name (OpenCV does this). Keep normal native discovery.
        if fullname in active.executing:return None
        # Top-level sys.path precedence may include arbitrary earlier directories
        # or archives. Let ordinary discovery resolve these ~few root packages;
        # get_code can still shortcut the exact selected approved source.
        if '.' not in fullname:return None
        entry=active.modules.get(fullname)
        if entry is None or key(entry['source']['path']) not in active.sources:return None
        if not active.paths_match(entry,path):return None
        loader=ApprovedLoader(fullname,entry['source']['path'],active)
        active.observed['module_finder_hits']+=1
        return importlib.util.spec_from_file_location(fullname,entry['source']['path'],loader=loader,
                  submodule_search_locations=[str(Path(entry['source']['path']).parent)] if entry['is_package'] else None)


def activate_bundle(manifest,source_index,index):return BlobActivation(manifest,source_index,index)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous-cache-manifest',type=Path,required=True)
    p.add_argument('--previous-cache-manifest-sha256',required=True);p.add_argument('--bundle-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True)
    a=p.parse_args();verify_admission(a.admission,a.admission_sha256,__file__,'docling-bytecode-bundle')
    from python_cache import owned_cache,cache_identity
    previous_pin={'path':str(a.previous_cache_manifest.resolve()),'sha256':a.previous_cache_manifest_sha256}
    previous=read(checked(previous_pin));cache_identity(previous);source_index=read(checked(previous['approved_source_index']))
    root=owned_cache(a.bundle_root,new=True)
    roots=[str(Path(sys.prefix)/'Lib'/'site-packages'),str(Path(sys.base_prefix)/'Lib'),str(Path(sys.base_prefix)/'DLLs')]
    if key(source_index['stdlib_source_root'])!=key(roots[1]):raise ValueError('Actual stdlib source root differs')
    index_path=create_blob(previous,source_index,root,roots,expected_records=2390,expected_bytes=57123778,native_paths=native_inventory(source_index))
    selected=dict(previous,verification_mode=MODE,bytecode_blob_index=pin(index_path),bundle_helper=pin(__file__),
                  previous_delivery_manifest=previous_pin,cache_helper=pin(Path(__file__).with_name('python_cache.py')))
    manifest_path=root/'CACHE_MANIFEST.json';save(manifest_path,selected)
    save(a.output,{'contract':'document-ai-PYC-blob-build-result.v1','status':'COMPLETE','cache_manifest':pin(manifest_path),
         'blob_index':pin(index_path),'PYC_payload_bytes':57123778,'source_payload_bytes':0,'records':2390,
         'model_calls':0,'model_constructs':0,'model_weight_loads':0,'source_image_decodes':0,'optimizer_updates':0,
         'no_bytecode_recompiled':True,'frozen_runtime_modified':False})


if __name__=='__main__':main()
