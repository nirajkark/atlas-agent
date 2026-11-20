# MCP servers for ATLAS online services

Research and code for letting an AI assistant query ATLAS TDAQ operational data via MCP.

| Path | Contents |
|---|---|
| `daq1/` | DAQ-1: read-only MCP server + agent for current IS data via Webis — see [daq1/README.md](daq1/README.md) |
| `ref/` | Reference material: Run Status page (`ATLAS.html`, `ATLAS.js`), project instructions |
| `docs/wp1/` | WP1 studies: Information Service, Run Control, ERS |
| `docs/wp2/` | WP2: agentic-architecture literature review and DAQ agent architecture |
| `docs/latex/` | LaTeX sources |

## DAQ-1 quick start

Webis runs on the dev VM (`webis_server -p 8080 -a 127.0.0.1`, read-only). From a laptop on eduVPN:

```bash
ssh -N -L 8080:127.0.0.1:8080 <user>@vm-onlsw-ai-pbeast.cern.ch   # tunnel
cd daq1 && uv run pytest                                           # offline tests
uv run python agent.py                                             # chat (needs AIGW_API_KEY in daq1/.env)
uv run python agent.py -v -q "Is mytest running?"                  # one question, show tool calls
```

Set `WEBIS_URL` to point the client elsewhere (default `http://127.0.0.1:8080`).
