"""Pure invented command/token cases, with no weights, invoices or servers."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import glm_backend as backend

class GLMBackendTests(unittest.TestCase):
    def test_quantizer_is_separate_finite_lossy_arm_with_bounded_buffers(self):
        command=backend.quantize_command('D:/isolated/llama-quantize.exe','D:/input/vision Q8.gguf',
            'D:/new/vision Q4.gguf',quantization='Q4_0')
        self.assertEqual(['--allow-requantize','--max-buffer-size','16'],command[1:4])
        self.assertEqual(['Q4_0','1'],command[-2:]);self.assertNotIn('--dry-run',command)
        dry=backend.quantize_command('D:/q.exe','D:/input.gguf','D:/output.gguf',dry_run=True)
        self.assertIn('--dry-run',dry)
        for src,dst,quant in [('D:/same.gguf','d:\\same.gguf','Q4_0'),
                              ('https://remote/model','D:/out.gguf','Q4_0'),
                              ('D:/in.gguf','D:/out.gguf','IQ1_S')]:
            with self.subTest(quant=quant,source=src),self.assertRaises(ValueError):
                backend.quantize_command('D:/q.exe',src,dst,quantization=quant)

    def test_cpu_server_cannot_fetch_models_or_hide_context_cache_and_parallelism(self):
        command=backend.server_command('D:/isolated/llama-server.exe','D:/weights/text.gguf','D:/weights/vision.gguf',port=18761)
        def value(flag):return command[command.index(flag)+1]
        self.assertEqual('1',value('--threads'));self.assertEqual('1',value('--threads-batch'))
        self.assertEqual('1',value('--threads-http'));self.assertEqual('1',value('--parallel'))
        self.assertEqual('0',value('--gpu-layers'));self.assertIn('--no-mmproj-offload',command)
        self.assertEqual('none',value('--load-mode'));self.assertEqual('off',value('--lazy-mode'))
        self.assertEqual('0',value('--cache-ram'));self.assertEqual('0',value('--ctx-checkpoints'))
        self.assertEqual('2048',value('--ctx-size'));self.assertEqual('1024',value('--predict'))
        self.assertEqual('64',value('--batch-size'));self.assertEqual('32',value('--ubatch-size'))
        self.assertEqual('256',value('--image-max-tokens'));self.assertIn('--no-warmup',command)
        self.assertIn('--offline',command);self.assertEqual('127.0.0.1',value('--host'))
        self.assertNotIn('-hf',command);self.assertNotIn('--rpc',command)

    def test_invalid_runtime_expansions_are_not_silently_accepted(self):
        for kwargs in ({'context_tokens':4096},{'image_max_tokens':4096},{'port':80},
                       {'max_output_tokens':2048},{'port':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                backend.server_command('D:/s.exe','D:/m.gguf','D:/p.gguf',**({'port':18761}|kwargs))
        for key,value in [('CPU_threads',2),('stop_free_RAM_bytes',1),('maximum_own_process_tree_RSS_bytes',2**31)]:
            altered={**backend.CAPS,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):backend.validate_resources(altered)
        self.assertEqual(backend.CAPS,backend.validate_resources(backend.CAPS))

    def test_weight_budget_includes_projector_kv_and_all_reservations(self):
        reserves={'vision_scratch_bytes':64*1024**2,'decoder_prefill_scratch_bytes':32*1024**2,'runtime_and_owned_parent_bytes':64*1024**2}
        q8=backend.memory_preflight(**{k+'_bytes':v for k,v in backend.OFFICIAL_Q8_BYTES.items()},context_tokens=2048,reservations=reserves)
        self.assertEqual('REJECTED_RESOURCE_BUDGET',q8['status'])
        self.assertEqual(1434837056,q8['all_weight_bytes']);self.assertEqual(17*8*128*2*2*2048,q8['KV_budget_bytes'])
        self.assertEqual(q8['all_weight_bytes']+q8['KV_budget_bytes']+sum(reserves.values()),q8['total_budget_bytes'])
        # Invented derivative sizes permit a monitored canary, not a fit claim.
        smaller=backend.memory_preflight(450131264,250000000,context_tokens=2048,reservations=reserves)
        self.assertEqual('BOUNDED_CANARY_REQUIRED',smaller['status']);self.assertFalse(smaller['runtime_fit_proven'])
        self.assertTrue(smaller['actual_RSS_measurement_required'])
        with self.assertRaises(ValueError):backend.memory_preflight(1,1,context_tokens=1024,reservations={})

    def request(self):return backend.completion_request('data:image/png;base64,QUJD',max_output_tokens=1024)
    def raw(self):return {'choices':[{'index':0,'finish_reason':'stop','message':{'content':'  Printed Thai text\n'}}],
        'usage':{'prompt_tokens':200,'completion_tokens':20,'total_tokens':220},'timings':{'prompt_ms':12.0}}

    def test_official_prompt_and_raw_text_are_preserved_without_ocr_confidence(self):
        request=self.request();self.assertEqual('Text Recognition:',request['messages'][0]['content'][0]['text'])
        self.assertEqual(0,request['temperature']);self.assertFalse(request['stream']);self.assertFalse(request['cache_prompt'])
        raw=self.raw();raw['confidence']=.999;before=deepcopy((raw,request))
        receipt=backend.completion_receipt(raw,request,context_tokens=2048)
        self.assertTrue(receipt['generation_complete']);self.assertEqual('  Printed Thai text\n',receipt['raw_text'])
        self.assertIsNone(receipt['numeric_OCR_confidence']);self.assertFalse(receipt['glyph_boxes_supplied'])
        self.assertFalse(receipt['document_coverage_verified']);self.assertEqual(before,(raw,request))
        with self.assertRaises(ValueError):backend.completion_request('https://remote/invoice.png')
        with self.assertRaises(ValueError):backend.completion_request('data:image/png;base64,QUJD',prompt='Guess the unit')

    def test_limit_missing_stop_and_explicit_truncation_remain_incomplete(self):
        for mode in ('length','limit','context','missing_finish','missing_usage','truncated','inconsistent_usage','empty','zero_output'):
            raw=self.raw()
            if mode=='length':raw['choices'][0]['finish_reason']='length'
            elif mode=='limit':raw['usage'].update(completion_tokens=1024,total_tokens=1224)
            elif mode=='context':raw['usage'].update(prompt_tokens=2028,total_tokens=2048)
            elif mode=='missing_finish':raw['choices'][0].pop('finish_reason')
            elif mode=='missing_usage':raw.pop('usage')
            elif mode=='truncated':raw['truncated']=True
            elif mode=='inconsistent_usage':raw['usage']['total_tokens']=1
            elif mode=='empty':raw['choices'][0]['message']['content']='  '
            else:raw['usage'].update(completion_tokens=0,total_tokens=200)
            with self.subTest(mode=mode):
                receipt=backend.completion_receipt(raw,self.request(),context_tokens=2048)
                self.assertFalse(receipt['generation_complete']);self.assertTrue(receipt['hold_reasons'])

    def test_explicit_backend_error_cannot_hide_behind_stale_choices_or_usage(self):
        for mode in ('top_level','choice','null_usage','malformed_usage'):
            raw=self.raw()
            if mode=='top_level':raw['error']={'message':'synthetic actual failure'}
            elif mode=='choice':raw['choices'][0]['error']='synthetic choice failure'
            elif mode=='null_usage':raw['usage']=None
            else:raw['usage']='not actual counts'
            with self.subTest(mode=mode):
                receipt=backend.completion_receipt(raw,self.request(),context_tokens=2048)
                self.assertFalse(receipt['generation_complete'])
        valid=self.raw();valid['error']=None
        self.assertTrue(backend.completion_receipt(valid,self.request(),context_tokens=2048)['generation_complete'])

if __name__=='__main__':unittest.main()
