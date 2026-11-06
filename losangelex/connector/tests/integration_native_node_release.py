"""Actual protected-file release binding; canonical HTTP is explicitly synthetic."""
import base64,hashlib,json,os,tempfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from lax_connector import native_node_release as n,native_image_upgrade as image,service_observer as owner

def main():
 if os.geteuid()!=0:raise PermissionError('This operator filesystem journey requires root-owned fixtures')
 with tempfile.TemporaryDirectory(dir=os.environ["LAX_OPERATOR_QA_DIR"])as tmp:
  home=Path(tmp);host=home/'host';root=host/'services'/'agent';root.mkdir(parents=True,mode=0o700)
  manifest=home/'native-manifest.json';manifest.write_text('{"fixture":"no native process"}\n');manifest.chmod(0o600)
  authority,host_id,agent=[str(uuid4())for _ in range(3)]
  c={'authorityId':authority,'hostId':host_id,'agentId':agent,'runtimeMode':'room-conversation','nativeServer':{'manifest':str(manifest)},'hollywoodUrl':'http://127.0.0.1:1','token':'synthetic-no-credential'}
  wire=base64.b64encode(json.dumps(c).encode()).decode();plan={'oldBinary':'/same/native','newBinary':'/same/native','retainedNative':{'fixture':True},'transportAdoption':{'historicalUnknown':None},'targets':[{'before':wire,'after':wire}]}
  node={'schema':'lax-native-node-enrollment/v1','authorityId':authority,'hostId':host_id,'machineIdentity':image.machine_identity(),'nativeManifest':str(manifest),'nativeManifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'scope':'Synthetic root-owned operator fixture'}
  file=host/'native-node.json';file.write_text(json.dumps(node));file.chmod(0o600)
  pin=n.prepare(root,c,plan);assert pin and 'nativeManifestSha256'in pin;plan['nativeNodeRegistration']=pin
  fd=image._open_directory(host)
  try:
   assert n.load(fd,c,plan)==node
   calls=[]
   def synthetic(url,token,method,path):
    calls.append((method,path));return {'id':agent,'authority':authority,'kind':'agent','active':True,'home_node':host_id}
   with patch.object(n,'request',side_effect=synthetic):n.canonical(c,node,host_id,agent)
   assert calls==[('GET','principals/'+agent)]
   manifest.write_text('{"fixture":"changed"}\n')
   try:n.load(fd,c,plan)
   except ValueError:pass
   else:raise AssertionError('Changed original native manifest accepted')
   manifest.write_text('{"fixture":"no native process"}\n')
   ctrl=host/'controller.json';ctrl.write_text(json.dumps({'fixture':'legacy'}));ctrl.chmod(0o600)
   try:n.load(fd,c,plan)
   except ValueError:pass
   else:raise AssertionError('Changed control-plane kind accepted')
   assert n.prepare(root,c,plan)is None
   assert n.load(fd,c,{})=={'fixture':'legacy'}
   ctrl.unlink()
   for changed in [{**plan,'newBinary':'/other/native'},{**plan,'transportAdoption':{'historicalUnknown':{'state':'unknown'}}},{**plan,'targets':[{'before':wire,'after':base64.b64encode(json.dumps({**c,'token':'changed'}).encode()).decode()}]}]:
    try:n.load(fd,c,changed)
    except ValueError:pass
    else:raise AssertionError('Non-SDK-only change accepted')
   file.write_text(json.dumps({**node,'hostId':str(uuid4())}))
   try:n.load(fd,c,plan)
   except ValueError:pass
   else:raise AssertionError('Different physical host registration accepted')
  finally:os.close(fd)
 print(json.dumps({'passed':True,'actualRootOwnedFilesystemChecks':True,'originalManifestPin':True,'controlPlaneKindPinned':True,'changedCredentialsAndImageRejected':True,'legacyPathPreserved':True,'canonicalHTTPRequestSynthetic':True,'noLegacyExecutorQueries':True,'nativeModels':0,'productionChanged':False}))
if __name__=='__main__':main()
