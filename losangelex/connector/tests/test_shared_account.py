"""Protected account/layout journey; service/OS provisioning calls are synthetic."""
import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from lax_connector import shared_account as shared,host_native,linux_worker as worker
from lax_connector import service_observer as observer,service_memory,native_release as release,purpose_observer
from lax_connector.journal import saved


@unittest.skipUnless(os.geteuid()==0,'Root-owned metadata fixture required')
class SharedAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='lax-shared-account-',dir='/var/lib');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.harness=self.root/'harness';self.harness.mkdir(mode=0o755)
        self.authority,self.host,self.owner=[str(uuid4()) for _ in range(3)]
        self.base=self.harness/self.authority;self.base.mkdir(mode=0o755);(self.base/'workers').mkdir(mode=0o755)
        self.native=self.root/'native-host';self.native.mkdir(mode=0o755);(self.native/'state').mkdir(mode=0o700)
        self.home=self.root/'original-profile';self.home.mkdir(mode=0o700)
        (self.home/'work').mkdir();(self.home/'codex-home').mkdir(mode=0o700)
        self.auth=self.home/'codex-home/auth.json';self.auth.write_text('SYNTHETIC-NOT-A-CREDENTIAL');self.auth.chmod(0o600)
        self.binary=self.root/'native-program';self.binary.write_bytes(b'fixture; never executed');self.binary.chmod(0o755)
        self.account=SimpleNamespace(pw_name='synthetic-native',pw_uid=0,pw_gid=0,pw_dir=str(self.home))
        self.owner_scope_check=shared.owner_scope
        self.enterContext(patch.object(shared,'owner_scope'))
        self.enterContext(patch.object(shared,'HARNESS',self.harness))
        self.enterContext(patch.object(host_native,'location',return_value=self.native))
        self.enterContext(patch.object(shared.pwd,'getpwnam',return_value=self.account))
        self.enterContext(patch.object(shared.pwd,'getpwuid',return_value=self.account))
        value=host_native.manifest({'authorityId':self.authority,'hostId':self.host,'agentId':self.owner,'binary':str(self.binary)},self.home,self.account.pw_name)
        saved(self.native/'manifest.json',value);(self.native/'manifest.json').chmod(0o644)
        saved(self.native/'installation.json',{'schema':'lax-native-host-installation/v1','manifest':value,'serviceStarted':True})
        self.spec={'runtimeMode':'room-conversation','authorityId':self.authority,'hostId':self.host,'agentId':str(uuid4()),
            'nativeHostServer':True,'executionProfile':'unrestricted','approvedModelAuthFile':str(self.auth),
            'nativeHostAttachment':{'ownerAgentId':self.owner,'manifestSha256':hashlib.sha256((self.native/'manifest.json').read_bytes()).hexdigest(),'trustBoundary':shared.TRUST},
            'binary':str(self.binary),'interpreter':'/synthetic/python','model':'synthetic-model','effort':'low',
            'hollywoodUrl':'http://127.0.0.1:1','credential':'SYNTHETIC-ONLY','nativeName':'additional','purpose':'fixture','rooms':[{'roomId':str(uuid4()),'after':0}]}
        self.calls=[]
        shared.authorize(self.authority,self.host,self.spec['nativeHostAttachment']['manifestSha256'])
        (self.root/'etc').mkdir();(self.root/'etc/machine-id').write_bytes(b'synthetic-machine')
        self.spec['machineIdentity']=hashlib.sha256(b'synthetic-machine').hexdigest()

    def bind(self,spec):
        home=shared.worker_home(spec);home.parent.mkdir(mode=0o711,exist_ok=True)
        bound=shared.attachment(spec,home);saved(home.parent/'shared-native-account.json',bound['receipt'])
        for p in (home,home/'work',home/'state'):p.mkdir(mode=0o700)
        return home,bound

    def test_explicit_trust_cas_account_and_legacy_guards(self):
        config={'authorityId':self.authority,'hostId':self.host,'binary':str(self.binary),
            'codexHome':str(self.home/'codex-home'),'sandbox':'danger-full-access','nativeServer':{'manifest':str(self.native/'manifest.json')}}
        self.assertEqual(shared.request(config),self.spec['nativeHostAttachment'])
        policy=self.native/'shared-account-policy.json';policy.rename(policy.with_suffix('.held'))
        with self.assertRaisesRegex(PermissionError,'root-approved'):shared.request(config)
        shared.authorize(self.authority,self.host,self.spec['nativeHostAttachment']['manifestSha256'])
        with self.assertRaisesRegex(ValueError,'CAS'):
            shared.authorize(self.authority,self.host,'0'*64)
        pending=self.root/'pending-owner';pending.mkdir(mode=0o700)
        saved(pending/'image-held-intent.json',{'schema':'lax-native-release-upgrade/v1','state':'intent'})
        with patch.object(observer,'directory',return_value=pending),self.assertRaisesRegex(ValueError,'explicit reconciliation'):
            shared.attachment(self.spec,shared.worker_home(self.spec))
        for change in ({'executionProfile':'restricted'},{'nativeHostServer':False},{'nativeHostAttachment':None}):
            with self.subTest(change=change),self.assertRaises((PermissionError,ValueError)):
                shared.attachment({**self.spec,**change},shared.worker_home(self.spec))
        wrong=copy.deepcopy(self.spec);wrong['nativeHostAttachment']['manifestSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'CAS'):shared.attachment(wrong,shared.worker_home(wrong))
        foreign=self.root/'equivalent-auth';foreign.write_bytes(self.auth.read_bytes());foreign.chmod(0o600)
        with self.assertRaisesRegex(PermissionError,'original private'):
            shared.attachment({**self.spec,'approvedModelAuthFile':str(foreign)},shared.worker_home(self.spec))
        self.assertIsNone(shared.attachment({'nativeHostServer':False},self.root))
        with self.assertRaisesRegex(ValueError,'NSS'):release.physical(self.root,0)

    def test_original_owner_unrestricted_scope_must_be_proven(self):
        receipt={'authorityId':self.authority,'agentId':self.owner,'uid':0,'linuxUser':self.account.pw_name,
                 'workspace':str(self.home/'work'),'executionProfile':'restricted'}
        with patch.object(service_memory,'approved_spec',return_value=({},receipt,False)):
            with self.assertRaisesRegex(PermissionError,'approved unrestricted'):
                self.owner_scope_check(self.authority,self.owner,self.account)
        receipt.update(home=str(self.home),sudoVerifiedUid=0)
        with patch.object(service_memory,'approved_spec',return_value=({},receipt,True)):
            self.owner_scope_check(self.authority,self.owner,self.account)
        receipt.update(executionProfile='unrestricted',administrator=True)
        with patch.object(service_memory,'approved_spec',return_value=({},receipt,False)):
            self.owner_scope_check(self.authority,self.owner,self.account)

    def test_two_layouts_observer_release_and_stopped_host_agree(self):
        configs=[];before=(self.native/'manifest.json').read_bytes();auth=self.auth.read_bytes()
        for number in range(2):
            spec={**self.spec,'agentId':str(uuid4()),'nativeName':'logical-'+str(number)}
            home,bound=self.bind(spec)
            config=worker.expected_configuration(spec,self.authority,spec['agentId'],home)
            context={'state':'ready','nativeThreadId':str(uuid4()),'binding':{'authorityId':self.authority,'agentId':spec['agentId'],'codexHome':str(self.home/'codex-home'),'nativeState':str(self.native/'state')}}
            config=worker.expected_configuration(spec,self.authority,spec['agentId'],home,native_context=context);configs.append(config)
            with patch.object(purpose_observer,'installation',return_value=None),patch.object(service_memory,'approved_spec',return_value=(spec,{'linuxUser':self.account.pw_name,'uid':0},False)):
                self.assertEqual(observer.expected_owner(self.authority,spec['agentId']),(0,home,str(self.binary)))
                plan={'scope':[self.authority,self.host,spec['agentId']],'home':str(home),'uid':0,'originalSpecDigest':observer.digest(spec),'sharedAgentIdentity':bound['identity']}
                physical_args,probe_args=release.identity_arguments(plan)
                paths=release.physical(home,0,**physical_args)
                self.assertIn(str(self.home/'codex-home'),paths);self.assertIn(str(home/'state'),paths)
                self.assertEqual(probe_args,{'service_home':self.home})
            with patch.object(host_native,'run',return_value=SimpleNamespace(stdout='inactive\n')) as run:
                result=host_native.ensure(spec,self.account,home)
                self.assertEqual((result['serviceStarted'],result['serviceActiveState']),(False,'inactive'))
                self.assertEqual(run.call_args.args[:2],('systemctl','show'))
            self.assertNotIn('Wants=',worker.expected_unit(spec,spec['agentId'],self.account.pw_name,home))
            self.assertFalse((home/'codex-home').exists())
        self.assertEqual(configs[0]['codexHome'],configs[1]['codexHome'])
        for key in ('agentId','nativeThreadId','state','workspace'):self.assertNotEqual(configs[0][key],configs[1][key])
        self.assertEqual((self.native/'manifest.json').read_bytes(),before);self.assertEqual(self.auth.read_bytes(),auth)
        saved(home.parent/'provision-receipt.json',{'specDigest':'synthetic-original'})
        saved(home.parent/'execution-policy-upgrade-receipt.json',{'executionProfile':'restricted','originalSpecDigest':'synthetic-original'})
        with self.assertRaisesRegex(PermissionError,'restricted isolation'):
            shared.attachment(spec,home,require_receipt=True)
        from lax_connector.shared_native_release import prepare
        with self.assertRaisesRegex(ValueError,'coordinated multi-client'):
            prepare({'authorityId':self.authority,'hostId':self.host},{},'unused','unused')

    def test_actual_provision_sequence_has_no_new_user_profile_or_host_start(self):
        # Rewrite only fixture path roots; never invoke a real OS/service helper.
        def path(value='.',*parts):
            p=Path(value,*parts)
            if p.is_relative_to('/var/lib/harness'):return self.harness/p.relative_to('/var/lib/harness')
            if p.is_relative_to('/etc'):return self.root/'etc'/p.relative_to('/etc')
            return p
        (self.root/'etc/systemd/system').mkdir(parents=True)
        def command(*args):
            self.calls.append(args)
            if args[:2]==('systemctl','show'):return SimpleNamespace(stdout='inactive\n')
            if args[:2]==('runuser','-u'):return SimpleNamespace(stdout='')
            if args[:2]==('systemctl','enable'):return SimpleNamespace(stdout='')
            raise AssertionError('Unexpected OS mutation: '+repr(args))
        def process(args,**kw):
            if 'lax_connector.room_bootstrap' in args:
                config=json.loads(Path(args[-1]).read_text())
                context={'state':'ready','nativeThreadId':str(uuid4()),'binding':{'authorityId':self.authority,'agentId':self.spec['agentId'],'codexHome':config['codexHome'],'nativeState':str(self.native/'state')}}
                return SimpleNamespace(returncode=0,stdout=json.dumps(context),stderr='')
            self.assertIn('sudo',args)
            return SimpleNamespace(returncode=0,stdout=b'0',stderr=b'')
        with patch.object(worker,'Path',side_effect=path),patch.object(worker,'run',side_effect=command),\
             patch.object(host_native,'run',return_value=SimpleNamespace(stdout='active\n')) as host_run,\
             patch.object(worker.subprocess,'run',side_effect=process),\
             patch.object(worker,'preflight_as_owner',return_value={'modelsStarted':0}) as probe,\
             patch.object(observer,'register',return_value={'registered':True}),\
             patch.object(worker,'service_readiness',return_value={'ready':True}):
            receipt=worker.provision(self.spec)
            home=shared.worker_home(self.spec)
            self.assertEqual((receipt['linuxUser'],receipt['uid']),(self.account.pw_name,0))
            self.assertEqual(probe.call_args.args[-1],self.home)
            self.assertEqual(probe.call_args.kwargs['workspace'],home/'work')
            self.assertFalse((home/'codex-home').exists())
            self.assertEqual(host_run.call_count,1)
            inspected=worker.inspect_completed(self.spec)
            self.assertTrue(inspected['inspection']['configurationMatched'])
            self.assertEqual(inspected['linuxUser'],self.account.pw_name)
            self.calls.clear()
            with patch.object(worker,'service_readiness',return_value={'ready':False}):
                again=worker.provision(self.spec)
            self.assertFalse(again['modelOrServiceRestarted']);self.assertEqual(again['serviceActiveState'],'inactive')
            self.assertEqual(host_run.call_count,1)
            self.assertTrue(all(c[:2]==('systemctl','show') for c in self.calls))


if __name__=='__main__':unittest.main()
