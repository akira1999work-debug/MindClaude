# MindClaude

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that connects [EdrawMind](https://www.edrawmind.com/) with AI assistants like Claude Code. Read, search, create, and update mind maps through natural conversation.

## What it does

| Tool | Description |
|------|-------------|
| `list_mindmaps` | List all available mind maps (local files, cloud cache, autosave) |
| `read_mindmap` | Read and extract content from an .emmx mind map file |
| `search_mindmaps` | Search across all mind maps for a keyword |
| `create_mindmap` | Create a new mind map from Markdown and open it in EdrawMind |
| `add_to_mindmap` | Merge new content into an existing mind map |

## How it works

- **Reading**: `.emmx` files are ZIP archives containing a custom binary format (`page.bin`). The server extracts text nodes by scanning for valid UTF-8 sequences.
- **Writing**: The server generates Markdown files and opens them in EdrawMind, which natively imports Markdown as mind map trees. Heading levels (`# ## ###`) define the hierarchy.
- **Discovery**: Automatically finds mind maps in common locations, EdrawMind's cloud cache, autosave directory, and recent file history.

## Requirements

- Python 3.8+
- EdrawMind desktop app (for creating/opening mind maps)
- No external Python dependencies

## Setup

### Claude Code

```bash
# Add to your MCP config (~/.mcp.json or project .mcp.json)
```

```json
{
  "mcpServers": {
    "mindclaude": {
      "command": "python3",
      "args": ["/path/to/MindClaude/server.py"]
    }
  }
}
```

Then restart Claude Code. The tools will be available automatically.

### Other MCP clients

Any MCP-compatible client can use this server via stdio transport. Just run:

```bash
python3 server.py
```

## Usage examples

Once connected, you can use natural language:

- "Show me my mind maps"
- "Read the project plan mind map"
- "Search all mind maps for 'deadline'"
- "Create a mind map for our Q2 roadmap with these items..."
- "Add a new branch to the project plan with these tasks"

### Markdown format for creating mind maps

EdrawMind imports Markdown headings as tree structure:

```markdown
# Central Topic
## Branch 1
### Sub-topic 1-1
### Sub-topic 1-2
## Branch 2
### Sub-topic 2-1
#### Detail
```

## Platform support

| Platform | Read .emmx | Create/Open in EdrawMind | Cloud cache |
|----------|-----------|------------------------|-------------|
| macOS | Yes | Yes (`open -a`) | `~/Library/Edraw/EdrawMind/` |
| Windows | Yes | Yes (`os.startfile`) | `%LOCALAPPDATA%\Edraw\EdrawMind\` |
| Linux | Yes | Yes (`xdg-open`) | `~/.config/Edraw/EdrawMind/` |

## How EdrawMind cloud files work

EdrawMind caches cloud files locally when you open them in the desktop app. This server reads those cached copies. To access a cloud mind map:

1. Open it once in EdrawMind (it gets cached locally)
2. The server can then read it anytime

## License

MIT
