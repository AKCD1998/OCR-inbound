"""No SDK/models/images: the diagnostic observer preserves loader semantics."""
import importlib.util
from pathlib import Path
import sys
import unittest

MODULES=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(MODULES))
import import_io_diagnostic as diagnostic


class IOObservation(unittest.TestCase):
    def test_raw_and_guard_observers_preserve_exact_buffer(self):
        trace=diagnostic.IOTrace();data=b'actual Python bytecode'
        loader=type('Loader',(),{'path':'actual.py'})()
        raw=trace.wrap(lambda owner,path:data)
        guard=trace.wrap(raw,guarded=True)
        self.assertIs(guard(loader,'actual.pyc'),data)
        self.assertEqual(trace.state['PYC_bytes'],len(data))
        self.assertEqual(trace.state['raw_calls'],1);self.assertEqual(trace.state['guard_calls'],1)
        self.assertIsNone(trace.state['current_raw']);self.assertIsNone(trace.state['current_guard'])

    def test_exception_identity_survives_both_observers(self):
        trace=diagnostic.IOTrace();error=OSError('expected missing cache')
        def fail(owner,path):raise error
        wrapped=trace.wrap(trace.wrap(fail),guarded=True)
        try:wrapped(object(),'missing.pyc')
        except OSError as observed:self.assertIs(observed,error)
        else:self.fail('Expected original exception')
        self.assertEqual(trace.state['read_errors'],1);self.assertEqual(trace.state['guard_errors'],1)
        self.assertEqual(trace.snapshot('test')['model_calls'],0)


if __name__=='__main__':unittest.main()
