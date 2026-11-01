"""Complete legacy native catalog built from shared platform-neutral declarations."""
from .native_tool_declarations import CAPABILITIES, PURPOSE_CAPABILITIES, STRING, spec
from .native_tool_declarations import TOOLS as BASE_TOOLS
from .workflow import definitions as workflow_definitions

TOOLS = list(BASE_TOOLS)
TOOLS += workflow_definitions(spec)
from .mutation_tools import definitions as mutation_definitions
TOOLS += mutation_definitions(spec)


