"""Attached connector release metadata uses the existing guarded transition.

No real service, account, native process or provider is accessed by this fixture.
"""
import base64,hashlib,json,os,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from lax_connector import shared_account as shared,host_native,native_release as release
from lax_connector import native_release_transition as transition,service_observer as observer,host as host_api
from lax_connector.journal import saved
import test_native_release as legacy


@unittest.skipUnless(os.geteuid()==0,'Root-owned metadata fixture required')
class AttachedReleaseTests(unittest.TestCase):
    get=legacy.ReleaseTests.get
    prepare=legacy.ReleaseTests.prepare
    approve=legacy.ReleaseTests.approve

    def probe_release(self,*args,service_home=None):
        self.assertEqual(service_home,self.service_home)
        return legacy.ReleaseTests.probe_release(self,*args)

    def setUp(self):
        legacy.ReleaseTests.setUp(self)
        def pending(origin,token,method,path):
            self.assertEqual((origin,token,method,path),('http://fixture.invalid','fixture-only','GET','connector/pending?hostId='+self.host))
            return {'busy':None}
        self.enterContext(patch.object(host_api,'request',side_effect=pending))
        self.service_home=self.root/'original-account';self.service_home.mkdir(mode=0o700)
        for name in ('codex-home','work'):(self.service_home/name).mkdir(mode=0o700)
        auth=self.service_home/'codex-home/auth.json';auth.write_text('SYNTHETIC');auth.chmod(0o600)
        native=self.root/'native-host';native.mkdir(mode=0o755);(native/'state').mkdir(mode=0o700)
        self.enterContext(patch.object(host_native,'location',return_value=native))
        self.enterContext(patch.object(shared,'owner_scope'))
        self.enterContext(patch.object(shared,'worker_home',return_value=self.home))
        account=SimpleNamespace(pw_uid=0,pw_gid=0,pw_name='fixture',pw_dir=str(self.service_home))
        self.enterContext(patch.object(shared.pwd,'getpwnam',return_value=account))
        self.enterContext(patch.object(shared.pwd,'getpwuid',return_value=account))
        owner=str(uuid4())
        value=host_native.manifest({'authorityId':self.authority,'hostId':self.host,'agentId':owner,'binary':str(self.binary)},self.service_home,'fixture')
        saved(native/'manifest.json',value)
        self.spec.update(authorityId=self.authority,agentId=self.agent,runtimeMode='room-conversation',nativeHostServer=True,
                         approvedModelAuthFile=str(auth),nativeHostAttachment={'ownerAgentId':owner,'trustBoundary':shared.TRUST,
                         'manifestSha256':hashlib.sha256((native/'manifest.json').read_bytes()).hexdigest()})
        bound=shared.attachment(self.spec,self.home);saved(self.home.parent/'shared-native-account.json',bound['receipt'])
        self.config.update(runtimeMode='room-conversation',authorityId=self.authority,nativeThreadId='original-logical-thread',
                           nativeServer={'manifest':str(native/'manifest.json')},codexHome=str(self.service_home/'codex-home'))
        saved(self.home/'connector.json',self.config)
        self.request_spec['expectedConfigurationSha256']=hashlib.sha256((self.home/'connector.json').read_bytes()).hexdigest()
        # A connector release changes interpreter/closure, not the daemon image.
        self.new_binary.unlink();os.link(self.binary,self.new_binary)
        self.transport=self.enterContext(patch.object(release,'transport_inspect',return_value={
            'nativeThreadId':'original-logical-thread','status':'idle','nativeState':value['state'],'modelCalls':0,'otherLoadedThreadsPreserved':1}))

    def test_review_and_finish_keep_original_profile_thread_and_other_client(self):
        self.prepare()
        plan=json.loads((self.prepared/'release-plan.json').read_text())
        after=json.loads(base64.b64decode(plan['targets'][0]['after']))
        self.assertEqual(after,{**self.config,'binary':str(self.new_binary)})
        self.assertEqual(plan['sharedAgentIdentity']['serviceHome'],str(self.service_home))
        self.assertEqual(self.transport.call_args.kwargs,{'shared_client':True})
        self.approve()
        active=release.active_spec(self.spec,self.authority,self.host,self.agent)
        self.assertEqual(active['nativeHostAttachment'],self.spec['nativeHostAttachment'])
        self.assertIsNone(active['nativeStateAdoption'])
        self.assertEqual(shared.attachment(active,self.home,require_receipt=True)['identity'],plan['sharedAgentIdentity'])
        self.assertEqual(json.loads((self.home/'connector.json').read_text())['nativeThreadId'],'original-logical-thread')
        self.assertTrue((self.registry/release.CURRENT).exists())

    def test_attached_client_cannot_request_owner_engine_upgrade(self):
        self.request_spec['sharedNativeUpgrade']={}
        with self.assertRaisesRegex(PermissionError,'original host owner'):self.prepare()
        self.assertFalse(self.prepared.exists())


    def test_connector_only_closure_keeps_original_external_native_without_links(self):
        import shutil
        from lax_connector import native_dependency as dependency
        from lax_connector.service_restart import file_identity
        # Remove the copied native package entirely: the new SDK is independent.
        python_bytes=self.new_python.read_bytes()
        shutil.rmtree(self.new_root/'native')
        self.new_python=self.new_root/'venv/bin/python'
        self.new_python.parent.mkdir(parents=True)
        self.new_python.write_bytes(python_bytes);self.new_python.chmod(0o755)
        self.request_spec.update(retainNativeImage=True,newBinary=str(self.binary),newInterpreter=str(self.new_python))
        before=file_identity(self.binary)
        retained={'schema':'lax-retained-native/v1','binary':str(self.binary),
                  'imageSha256':hashlib.sha256(self.binary.read_bytes()).hexdigest()}
        self.enterContext(patch.object(dependency,'capture',return_value=retained))
        self.enterContext(patch.object(dependency,'pin_package',side_effect=lambda r,p:r))
        verify=self.enterContext(patch.object(dependency,'verify'))
        self.prepare()
        plan=json.loads((self.prepared/'release-plan.json').read_text())
        self.assertEqual(plan['retainedNative'],retained)
        self.assertEqual(plan['newBinary'],str(self.binary))
        self.assertFalse((self.new_root/'native').exists())
        self.assertFalse(any(x['path'].startswith('native/') for x in plan['closure']['entries']))
        self.approve()
        self.assertTrue(verify.called)
        self.assertEqual(file_identity(self.binary),before)
        self.assertEqual(json.loads((self.home/'connector.json').read_text())['binary'],str(self.binary))

    def test_retained_dependency_rejects_even_a_same_inode_binary_alias(self):
        self.request_spec['retainNativeImage']=True
        self.assertTrue(os.path.samefile(self.binary,self.new_binary))
        with self.assertRaisesRegex(ValueError,'retain the exact shared image'):
            self.prepare()
        self.assertFalse(self.prepared.exists())


if __name__=='__main__':unittest.main()
