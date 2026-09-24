"""Container entrypoint: `python3 -m services.mcp` (docker-compose.yml's
`mcp` service, shared root Dockerfile — same one-Dockerfile-many-commands
pattern as every other services/<x> in this repo). Runs the real MCP
server over `streamable-http` by default (spec 06: "python mcp SDK,
streamable-http or stdio") so it is reachable over the docker-compose
network without a stdin-attached process; `OO_MCP_TRANSPORT=stdio` switches
to stdio for a locally-run agent client.
"""

from __future__ import annotations

import os

from services.mcp.config import from_container_env
from services.mcp.server import build_server


def main() -> None:
    config = from_container_env()
    transport = os.environ.get("OO_MCP_TRANSPORT", "streamable-http")
    # OO_MCP_HTTP_PORT is the CONTAINER-internal port (docker-compose.yml
    # sets it); MCP_HTTP_PORT (.env) is the HOST-published port those
    # containers are mapped to — same split as every other services/<x>
    # HEALTH_PORT pair in this repo (e.g. OO_ACTION_WORKER_HEALTH_PORT vs
    # ACTION_WORKER_HEALTH_PORT).
    port = int(os.environ.get("OO_MCP_HTTP_PORT", "8000"))
    mcp = build_server(config, host="0.0.0.0", port=port)
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
