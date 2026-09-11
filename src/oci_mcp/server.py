"""FastMCP server entrypoint.

Tools are registered conditionally from the capability flags, so a disabled
capability is absent from the catalog rather than present-and-refusing. A tool
the model cannot see is a tool it cannot be talked into calling.
"""

from __future__ import annotations

from fastmcp import FastMCP

from . import __version__
from .config import settings
from .tools import read

INSTRUCTIONS = """\
Operate Oracle Cloud Infrastructure: Identity, Compute, Block Volume, \
Networking (VCN), Object Storage and OKE.

Call `oci_whoami` first in a session to establish the active tenancy, region and \
which compartments this server is permitted to modify. Destructive tools are \
two-phase: call them without a confirm_token to get a preview plus a token, then \
repeat the call with that token to execute.\
"""


def build_server() -> FastMCP:
    s = settings()
    mcp = FastMCP(name="oci", version=__version__, instructions=INSTRUCTIONS)

    read.register(mcp)

    # Phase 2+ registers write and delete tools here, gated on
    # s.allow_write / s.allow_delete.
    _ = s

    return mcp


mcp = build_server()


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
