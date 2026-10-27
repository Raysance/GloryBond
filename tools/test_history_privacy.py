"""Historical privacy rules use synthetic identities and rotating credentials."""
import subprocess
import tempfile
from pathlib import Path
import unittest

from sanitize_repository_history import Inventory, private_path, sample_path, empty_sample


class HistoryPrivacyTests(unittest.TestCase):
    def test_private_runtime_symlinks_and_custom_inputs_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'repo';root.mkdir()
            outside=Path(temporary)/'runtime';outside.mkdir()
            subprocess.run(['git','init','-b','main'],cwd=root,check=True,capture_output=True)
            (root/'.gitignore').write_bytes((Path(__file__).resolve().parents[1]/'.gitignore').read_bytes())
            for name in ('log','file_transfer'):
                (root/name).symlink_to(outside,target_is_directory=True)
            paths=['log','file_transfer','resources/wzry_images/custom_wzry_E1/private-input.jpg','.ruff_cache/state']
            for name in paths:
                self.assertEqual(subprocess.run(['git','check-ignore','--quiet',name],cwd=root).returncode,0,name)

    def test_legacy_sample_directories_preserve_schema_without_user_values(self):
        self.assertTrue(sample_path('src/plugins/qbot/wzry_data_format_original/profile.json'))
        self.assertTrue(sample_path('src/plugins/qbot/tools/example.json'))
        value={'data': [{'nickname':'synthetic participant','id':123,'enabled':True}]}
        self.assertEqual(empty_sample(value),{'data':[{'nickname':'','id':0,'enabled':False}]})

    def test_runtime_configuration_and_private_implementations_are_excluded(self):
        for name in ['.env','config.yaml','src/plugins/qbot/variables_static.json','history/2020-01-01.json','src/plugins/qbot/tools/dump.rdb','agent_runtime/core/loop.py','vendor/react-agent-runtime/src/agent_runtime/api.py']:
            self.assertTrue(private_path(name),name)
        for name in ['deployment/scripts/deploy_project.sh','README.md','AGENTS.md','hok/zfunc.py','agent_runtime','vendor/react-agent-runtime']:
            self.assertFalse(private_path(name),name)

    def test_inventory_covers_rotated_credentials_and_keeps_language_symbols(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def git(*args):
                return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL)
            git('init','-b','main')
            git('config','user.name','Synthetic Author');git('config','user.email','author@example.invalid')
            first='sk-'+'FirstSyntheticCredential'*2
            second='sk-'+'SecondSyntheticCredential'*2
            for secret in (first,second):
                (root/'.env').write_text('API_KEY='+secret+'\n')
                (root/'config.yaml').write_text('StaticVariables:\n  qid: {private_user: 123456789}\n  namenick: {private_user: 私有测试名}\n  nameref: {private_user: [touch]}\n')
                (root/'example.py').write_text('token = '+repr(secret)+'\ndef touch():\n    return "touch-action"\n')
                git('add','.');git('commit','-m','Keep original message')
            git('branch','web-history')
            inventory=Inventory(root)
            public=inventory.sanitize(first+' '+second+' 123456789 私有测试名 private_user')
            inventory.check(public,'synthetic')
            for original in (first,second,'123456789','私有测试名','private_user'):
                self.assertNotIn(original,public)
            code='def touch():\n    return "touch-action"\n'
            self.assertEqual(inventory.sanitize(code),code)
