"""Private qualification endpoint only; existing schema, no migration/default change."""
import json
from pathlib import Path
from aiohttp import web
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
store=Store(json.loads(Path('/var/lib/lax-role-decision-owner-20261020-r251/database.json').read_text()))
try:
 web.run_app(application(store),host='127.0.0.1',port=18785,access_log=None)
finally:store.close()
