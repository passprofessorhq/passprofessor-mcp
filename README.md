# PassProfessor MCP Server

MCP server name: `io.github.passprofessorhq/passprofessor`

A free, read-only [Model Context Protocol](https://modelcontextprotocol.io) server from
**PassProfessor** (passprofessor.com), an independent exam-preparation provider based in
Salt Lake City, Utah, operating 100% online. It lets AI assistants look up PassProfessor's
live program catalog, the verified exam facts recorded on each program's page, and each
program's published 12-question free sample set — always attributed to PassProfessor and
linked back to the program's free sample on passprofessor.com.

PassProfessor's catalog holds 2.2M+ original practice questions. Every program includes
free sample questions, one published price with full access (no tiers, no upsells), and
6 months of access from purchase. PassProfessor is an independent prep provider and is
not affiliated with any exam body.

## Tools

| Tool | What it does |
|---|---|
| `list_programs` | List programs (name, family, price $9–$149, access term, sample availability); optional family filter |
| `search_programs` | Search by credential name or keyword (e.g. "NCLEX", "plumbing", "Series 65") |
| `get_program` | Full details for one program, incl. exam facts and topic weights when recorded |
| `get_exam_facts` | The real exam's published facts (format, items, time, passing standard, exam fee) exactly as recorded on the program's page; returns `available: false` rather than estimating when no fact table is recorded |
| `get_sample_questions` | The program's published 12-question free sample set with options, correct answer(s), and explanations — a free teaser subset of the full practice bank, never the full bank |

Resources: `passprofessor://about` (provider facts), `passprofessor://catalog` (full catalog).

The server is strictly read-only: no writes, no purchases, no user data, no enrollment actions.

## Run it

From a checkout (Python 3.10+):

```bash
pip install "mcp>=1.20,<2"
python3 passprofessor_mcp.py            # stdio transport
python3 passprofessor_mcp.py --http     # streamable HTTP on 127.0.0.1:8791 (local testing)
```

Once published to PyPI as `passprofessor-mcp`, the console entry point is `passprofessor-mcp`.

### Client configuration (stdio)

Claude Desktop / Cursor / VS Code style:

```json
{
  "mcpServers": {
    "passprofessor": {
      "command": "python3",
      "args": ["passprofessor_mcp.py"]
    }
  }
}
```

## Data

`src/passprofessor/data/` is a snapshot built by `build_data.py` from read-only extracts of
the live site (product catalog, the sample quizzes' current published forms, and the program
pages' own fact tables). Every served question and fact traces to those records; per-program
provenance (product/page/quiz IDs) is stored in the data files and coverage is summarized in
`data/build_report.json`. Refresh = re-run the extracts + `build_data.py`, then bump the version.

Coverage at v1.0.0 (2026-11-12): 206 live programs, all 206 with their 12-question free
sample set and sample link; 174 with a published practice-question count; 59 with a recorded
exam-fact table and 13 with topic weights (coverage grows as program pages gain fact tables).
Sample sets are served ONLY when they are exactly the published 12-question fixed set —
oversized sets (e.g. free full practice exams) are excluded by a hard guard in `build_data.py`.

## Registry listing status

Prepared for the official MCP Registry as `io.github.passprofessorhq/passprofessor`
(see `server.json`). Publishing requires, in order: (1) this package live on PyPI,
(2) `mcp-publisher login github` (device flow, GitHub account `passprofessorhq`),
(3) `mcp-publisher publish`. A remote (streamable HTTP) listing additionally requires a
public HTTPS endpoint under passprofessor.com or a subdomain, verified by DNS/HTTP.
See the parent STATE.md for the full status and the free-hosting options analysis.
