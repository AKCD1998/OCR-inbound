"""No SDK/images: actual read buffers, hashes, ordering and errors are observed."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import source_read_diagnostic as diagnostic


class ReadProbe(unittest.TestCase):
    def test_both_actual_methods_return_identical_verified_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'not_executed.py';data=b'raise RuntimeError("never execute")\n';path.write_bytes(data)
            source={'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}
            rows=diagnostic.run_pairs([{'source':source,'group':'synthetic'}])
            self.assertEqual(len(rows),4);self.assertEqual([r['order'] for r in rows],['AB','AB','BA','BA'])
            self.assertTrue(all(r['SHA_matches'] and r['bytes']==len(data) for r in rows))

    def test_changed_bytes_and_reader_exceptions_are_not_hidden(self):
        source={'path':'source.py','sha256':hashlib.sha256(b'approved').hexdigest()}
        with self.assertRaises(ValueError):diagnostic.measure(source,'ordinary_binary_read',lambda path:b'changed')
        error=OSError('expected')
        def fail(path):raise error
        try:diagnostic.measure(source,'ordinary_binary_read',fail)
        except OSError as observed:self.assertIs(observed,error)
        else:self.fail('Original error required')

    def test_exact32_source_selection_covers_eight_groups(self):
        records=[]
        for group in diagnostic.GROUPS:
            for n in range(5):
                path=('C:/Python/Lib/' if group=='CPython_stdlib' else 'D:/venv/Lib/site-packages/'+group+'/')+str(n)+'.py'
                records.append({'source':{'path':path,'sha256':'f'*64},'compile_source_bytes_sha256':'f'*64})
        selected=diagnostic.select_sources({'cached_modules':records})
        self.assertEqual(len(selected),32);self.assertEqual(set(x['group'] for x in selected),set(diagnostic.GROUPS))


if __name__=='__main__':unittest.main()
