"""Captured original checkpoint observation; zero HTTP/model/history mutations."""
import argparse,copy,hashlib,json
from pathlib import Path
from lax_connector.automatic_refill_history import verify,recovered_installed
p=argparse.ArgumentParser();p.add_argument("--journal",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
assert not a.output.exists()
b=a.journal.read_bytes();j=json.loads(b);history=Path(j["originalHistory"]["path"]);before=hashlib.sha256(history.read_bytes()).hexdigest()
installed=recovered_installed(j["originalHistory"],j["request"]["operationId"])
verify(j["originalHistory"],j["request"],j["response"],installed)
broken=copy.deepcopy(j["response"]);broken["items"].reverse()
try:verify(j["originalHistory"],j["request"],broken,installed)
except RuntimeError:pass
else:raise AssertionError("Changed original canonical tail was accepted")
wrong=copy.deepcopy(installed);wrong["contextId"]="another-context"
try:verify(j["originalHistory"],j["request"],j["response"],wrong)
except RuntimeError:pass
else:raise AssertionError("Wrong context installation was accepted")
assert before==hashlib.sha256(history.read_bytes()).hexdigest() and a.journal.read_bytes()==b
a.output.write_text(json.dumps({"journalSha256":hashlib.sha256(b).hexdigest(),"nativeHistorySha256":before,"originalOperation":j["request"]["operationId"],"installed":installed,"originalCheckpointVerified":True,"changedCanonicalTailAndContextRejected":True,"originalBytesUnchanged":True,"modelsStarted":0,"httpRequests":0},indent=2)+"\n")
print("Original actual native Reader checkpoint verified; changed tail/context refused; history/journal unchanged")
