import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
const root='/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267/actual-user-journey';
const label=process.argv[2];if(!['request','answer'].includes(label))throw Error('exact journey stage required');
const record=JSON.parse(fs.readFileSync(root+'/'+label+'.json','utf8'));
const child=`import fs from 'node:fs';
import {loadHollywood,HollywoodClient,hollywoodRequest} from '/home/aosp/.local/share/nextcomp-backend/releases/20261017-native-core-alpha110-r03/server/hollywood.mjs';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const binding=loadHollywood('/home/aosp/.local/share/nextcomp-backend/data');const cfg=binding?.devices?.get('owner')||binding?.defaultBinding;
if(!cfg||cfg.authorityId!=='e488f19b-0f60-46ca-bd48-4fe544f06757'||cfg.principalId!=='301c8b83-8cdb-5b9a-9d7f-3b2fa6f0b3f6')throw Error('actual owner binding differs');
const c=new HollywoodClient(cfg);await c.verify();
if(input.mode==='verify'){console.log(JSON.stringify(c.envelope()));}
else if(input.mode==='post'){const route=hollywoodRequest('POST',input.path,{},input.body);console.log(JSON.stringify(await c.call(route.path,route)));}
else {console.log(JSON.stringify(await c.call(input.lookup,{})));}`;
function invoke(mode){const p=spawnSync('/usr/sbin/runuser',['-u','aosp','--','/usr/bin/node','--input-type=module','-e',child],{input:JSON.stringify({...record,mode}),encoding:'utf8',timeout:30000});if(p.status!==0)throw Error('Actual gateway-identity client failed ('+mode+'): '+p.stderr.slice(-700));return JSON.parse(p.stdout);}
const identity=invoke('verify');
const intent=root+'/'+label+'-send-intent.json';if(fs.existsSync(intent))throw Error('original send exists; inspect receipt, do not replay');
fs.writeFileSync(intent,JSON.stringify({at:Date.now(),path:record.path,body:record.body,identity,postCount:1}),{flag:'wx',mode:0o600});
let accepted;try{accepted=invoke('post');}catch(error){
 fs.writeFileSync(root+'/'+label+'-send-gap.json',JSON.stringify({at:Date.now(),error:error.message,recovery:'GET original only'}),{mode:0o600});
 accepted=invoke('get');
}
fs.writeFileSync(root+'/'+label+'-receipt.json',JSON.stringify({at:Date.now(),accepted,postCount:1},null,2),{flag:'wx',mode:0o600});
console.log(JSON.stringify({label,accepted,postCount:1}));
