import fs from 'node:fs';
import {loadHollywood,HollywoodClient,hollywoodRequest} from '/home/aosp/.local/share/nextcomp-backend/releases/20261017-native-core-alpha110-r03/server/hollywood.mjs';
const root='/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267/actual-user-journey';
const label=process.argv[2];if(!['request','answer'].includes(label))throw Error('exact journey stage required');
const record=JSON.parse(fs.readFileSync(root+'/'+label+'.json','utf8'));
const binding=loadHollywood('/home/aosp/.local/share/nextcomp-backend/data');const cfg=binding.devices.get('owner')||binding.defaultBinding;
if(!cfg||cfg.authorityId!=='e488f19b-0f60-46ca-bd48-4fe544f06757'||cfg.principalId!=='301c8b83-8cdb-5b9a-9d7f-3b2fa6f0b3f6')throw Error('actual owner binding differs');
const client=new HollywoodClient(cfg);await client.verify();
const route=hollywoodRequest('POST',record.path,{},record.body);
const intent=root+'/'+label+'-send-intent.json';if(fs.existsSync(intent))throw Error('original send exists; inspect receipt, do not replay');
fs.writeFileSync(intent,JSON.stringify({at:Date.now(),path:route.path,body:record.body,postCount:1}),{flag:'wx',mode:0o600});
let accepted;try{accepted=await client.call(route.path,route);}catch(error){
 fs.writeFileSync(root+'/'+label+'-send-gap.json',JSON.stringify({at:Date.now(),error:error.code||error.name,recovery:'GET original only'}),{mode:0o600});
 accepted=await (new HollywoodClient(cfg)).call(record.lookup,{});
}
fs.writeFileSync(root+'/'+label+'-receipt.json',JSON.stringify({at:Date.now(),accepted,postCount:1},null,2),{flag:'wx',mode:0o600});
console.log(JSON.stringify({label,accepted,postCount:1}));
