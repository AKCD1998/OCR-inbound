"""Structured PowerShell publication: no real scheduler or network mutation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_docai_publication_under_test',ROOT/'scripts/hq_document_ai_job.py')
publication=importlib.util.module_from_spec(spec);spec.loader.exec_module(publication)

class PowerShellPublication(unittest.TestCase):
    def test_serial_validation_only_cannot_be_published_as_an_execution_job(self):
        with patch.object(publication.subprocess,'run') as remote:
            with self.assertRaisesRegex(ValueError,'explicitly execute'):
                publication.publish('serial_supervisor.py',['--config','metadata.json','--config-sha256','a'*64],'OCR_DOCAI_SYNTHETIC')
            remote.assert_not_called()

    def test_invalid_source_arguments_or_parameters_never_query_scheduler(self):
        for source,args,parameters in [('a.py',[],{'Manifest':'x'}),('a.ps1',['raw'],{'Manifest':'x'}),
          ('a.ps1',[],{'a; throw':'x'}),('a.ps1',[],{1:'x'}),('a.ps1',[],{'Manifest':object()})]:
            with self.subTest(parameters=parameters),patch.object(publication.subprocess,'run') as remote:
                with self.assertRaises(ValueError):publication.publish(source,args,'OCR_DOCAI_SYNTHETIC',powershell_parameters=parameters)
                remote.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows PowerShell binding test')
    def test_named_values_stay_literal_without_python_launcher(self):
        xml=b'''<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><URI>old</URI><Description>old</Description></RegistrationInfo><Principals><Principal><LogonType>InteractiveToken</LogonType></Principal></Principals><Settings><ExecutionTimeLimit>PT1M</ExecutionTimeLimit></Settings><Actions><Exec><Command>powershell.exe</Command><Arguments>old</Arguments><WorkingDirectory>old</WorkingDirectory></Exec></Actions></Task>'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);worker=root/'synthetic.ps1'
            worker.write_text("param([string]$Manifest,[string]$ManifestSha256)\n[pscustomobject]@{Manifest=$Manifest;Sha=$ManifestSha256}|ConvertTo-Json -Compress\nexit 0\n",encoding='utf-8')
            value="value'; $(throw 'must stay literal') #"
            def remote(args,**kwargs):return SimpleNamespace(returncode=1 if '/Query' in args else 0)
            with (patch.object(publication,'REMOTE',root/'remote'),patch.object(publication,'NATIVE',str(root/'remote')),
              patch.object(publication.subprocess,'run',side_effect=remote),patch.object(publication.subprocess,'check_output',return_value=xml)):
                result=publication.publish(worker,[],'OCR_DOCAI_SYNTHETIC',powershell_parameters={'Manifest':value,'ManifestSha256':'a'*64})
            task=root/'remote/OCR_DOCAI_SYNTHETIC';script=(task/'run.ps1').read_text(encoding='utf-8-sig')
            self.assertNotIn(publication.PYTHON,script)
            self.assertEqual(result['execution_mode'],'powershell_only_until_frozen_predecessor_ready')
            run=subprocess.run(['powershell','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-File',str(task/'run.ps1')],capture_output=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr.decode(errors='replace'))
            raw=(task/'task.log').read_bytes();text=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
            self.assertEqual(json.loads(text)['Manifest'],value)

    @unittest.skipUnless(os.name=='nt','Windows-only queue gate tests')
    def test_native_completion_gate_selftest_starts_no_python(self):
        run=subprocess.run(['powershell','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-File',str(ROOT/'experiments/document_ai/docling_post_eval_queue.ps1'),'-SelfTest'],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)
        result=json.loads(run.stdout);self.assertEqual(result['status'],'PASS')
        self.assertEqual((result['synthetic_cases'],result['Python_processes_started'],result['model_calls']),(15,0,0))

    @unittest.skipUnless(os.name=='nt','Windows PowerShell state-file replacement')
    def test_queue_state_replacement_writes_actual_terminal_state(self):
        # Exercise the real writer three times without executing the queue main,
        # Task Scheduler, Python children, locks or a model.
        code=r'''param([string]$QueueSourcePath,[string]$StateRoot)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($QueueSourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Invalid queue source' }
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-State'},$true)
Invoke-Expression ($fn.Extent.Text.Replace('$PSScriptRoot','$StateRoot'))
$script:PythonStarted=$false;$script:PostProof=$null
Write-State 'WAITING' 'first'
$script:PythonStarted=$true
Write-State 'POST_EVALUATION_STARTED' 'second'
Write-State 'FAILED' 'actual terminal state'
Get-Content -LiteralPath (Join-Path $StateRoot 'QUEUE_STATE.json') -Raw
'''
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);script=folder/'writer-test.ps1';script.write_text(code,encoding='utf-8')
            result=subprocess.run(['powershell','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-File',str(script),
              '-QueueSourcePath',str(ROOT/'experiments/document_ai/docling_post_eval_queue.ps1'),'-StateRoot',str(folder)],
              capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            state=json.loads(result.stdout)
            self.assertEqual((state['status'],state['detail'],state['Python_started']),('FAILED','actual terminal state',True))
            self.assertFalse((folder/'QUEUE_STATE.json.tmp').exists())

if __name__=='__main__':unittest.main()
