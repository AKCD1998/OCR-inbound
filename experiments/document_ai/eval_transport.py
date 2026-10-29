"""Explicit read-only path transport; logical native pins stay unchanged."""
from pathlib import Path,PureWindowsPath
from component_common import sha

class ReadTransport:
    def __init__(self,mappings=()):
        self.mappings=[]
        for native,physical in mappings:
            root=PureWindowsPath(native)
            if not root.is_absolute() or '..' in root.parts:raise ValueError('Absolute native read root required')
            self.mappings.append((root,Path(physical).resolve()))
        self.mappings.sort(key=lambda item:len(item[0].parts),reverse=True)
    def physical(self,path):
        candidate=PureWindowsPath(str(path))
        if '..' in candidate.parts:raise ValueError('Parent traversal is not a read transport')
        for native,root in self.mappings:
            if candidate.is_relative_to(native):
                result=root.joinpath(*candidate.relative_to(native).parts).resolve()
                if not result.is_relative_to(root):raise ValueError('Read transport escaped its physical root')
                return result
        return Path(path)
    def checked(self,record):
        path=self.physical(record['path'])
        if sha(path)!=record['sha256']:raise ValueError('Transported bytes differ from native pin')
        return path
    def pin(self,path):
        return {'path':str(path),'sha256':sha(self.physical(path))}

def parse_mappings(values):
    pairs=[]
    for value in values or ():
        if '=' not in value:raise ValueError('Use NATIVE_ROOT=PHYSICAL_READ_ROOT')
        pairs.append(value.split('=',1))
    return pairs
