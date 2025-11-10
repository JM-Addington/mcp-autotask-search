# Autotask Search MCP Server

A Model Context Protocol (MCP) server that exposes Autotask ticket search functionality to LLMs like Claude.

## Overview

This MCP server provides LLMs with the ability to search and retrieve Autotask tickets using advanced semantic search, keyword matching, and AI-powered reranking. It integrates seamlessly with Claude Desktop, Cursor, and other MCP-compatible clients.

## Features

- **Advanced Search**: Multi-method search combining BM25, semantic vectors, and fuzzy matching
- **AI Reranking**: Results are reranked using cross-encoder models for optimal relevance
- **Detailed Ticket Info**: Retrieve complete ticket details including all notes
- **LLM-Optimized**: Results formatted for easy LLM comprehension
- **Robust Error Handling**: Clear error messages with unique grep codes for debugging
- **Easy Setup**: Shell wrapper handles venv creation and dependencies

## Prerequisites

- Python 3.10 or higher
- Running Autotask Django API server (default: http://localhost:8000)
- Valid API key for the Autotask API

## Installation

### 1. Clone or Navigate to Directory

```bash
cd /path/to/autotask-data-warehouse/mcp-autotask-search
```

### 2. Create Environment File

```bash
cp .env.example .env
# Edit .env and add your API key
```

### 3. Test the Server

The `run.sh` script will automatically create a venv and install dependencies:

```bash
./run.sh
```

## Configuration

### Claude Desktop

Add to your Claude Desktop config file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "autotask-search": {
      "command": "/absolute/path/to/autotask-data-warehouse/mcp-autotask-search/run.sh",
      "env": {
        "AUTOTASK_API_KEY": "your-api-key-here",
        "AUTOTASK_API_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

**Important**: Use the absolute path to `run.sh`, not a relative path.

### Cursor IDE

Add to your Cursor settings (`.cursor/mcp.json` in your project or global settings):

```json
{
  "mcpServers": {
    "autotask-search": {
      "command": "/absolute/path/to/autotask-data-warehouse/mcp-autotask-search/run.sh",
      "env": {
        "AUTOTASK_API_KEY": "your-api-key-here",
        "AUTOTASK_API_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Environment Variables

- **`AUTOTASK_API_KEY`** (required): Your API key for authentication
- **`AUTOTASK_API_BASE_URL`** (optional): Base URL for the API (default: `http://localhost:8000`)

## Available Tools

### 1. `search_tickets`

Search Autotask tickets using advanced semantic and keyword search.

**Parameters:**
- `query` (string, required): Search query (supports partial names, keywords, typos)
- `limit` (integer, optional): Maximum results to return (default: 10, max: 100)

**Example Usage:**
```
Search for tickets about "password reset issues"
Search for "outlook email problems for ABC Company"
Search for "slow computer" with limit 5
```

**Search Capabilities:**
- Works with imperfect queries (typos, partial company names)
- Semantic understanding (finds relevant tickets even without exact keyword matches)
- Combines multiple search methods for comprehensive results
- Returns results ranked by relevance

### 2. `get_ticket_details`

Get complete details for a specific ticket including all notes.

**Parameters:**
- `task_id` (integer, required): The numeric task ID from search results

**Example Usage:**
```
Get full details for ticket 12345
Show me all notes for task_id 67890
```

**Returns:**
- Complete ticket information
- All human-created notes with timestamps
- Status and priority information

## Usage Examples

### In Claude Desktop/Cursor

Once configured, you can ask Claude:

```
"Search for tickets about email configuration issues"

"Find tickets related to password resets at ABC Company"

"Show me recent tickets about network problems"

"Get the full details for ticket 12345"
```

Claude will use the MCP tools to search the Autotask database and return formatted results.

## Testing

### 1. Test with MCP Inspector

Install the MCP Inspector:

```bash
npm install -g @modelcontextprotocol/inspector
```

Run the inspector:

```bash
cd mcp-autotask-search
npx @modelcontextprotocol/inspector ./run.sh
```

This opens a web UI where you can test the tools interactively.

### 2. Verify Django Server is Running

Before testing, ensure your Autotask Django server is running:

```bash
cd /path/to/autotask-data-warehouse
python manage.py runserver
```

### 3. Test Direct API Access

Verify the API is accessible:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:8000/api/search/double-reranked/?q=test&limit=5"
```

## Troubleshooting

### "API key not found" Error

**Symptom:** Server fails to start with error code `[MCPS-NOKEY]`

**Solution:**
- Ensure `AUTOTASK_API_KEY` is set in your Claude Desktop/Cursor config
- Check that the environment variable is being passed correctly
- Verify the API key is valid

### "Could not connect to Autotask API" Error

**Symptom:** Error code `[MCPS-CONN]`

**Solution:**
- Check that the Django server is running: `python manage.py runserver`
- Verify `AUTOTASK_API_BASE_URL` is correct (default: `http://localhost:8000`)
- Test API directly with curl

### "Authentication failed" Error

**Symptom:** Error code `[MCPS-AUTH]`

**Solution:**
- Verify API key is valid and not expired
- Check API key has proper permissions in Django admin
- Ensure key is correctly formatted in config

### "API endpoint not found" Error

**Symptom:** Error code `[MCPS-404]`

**Solution:**
- Verify Django server is running and accessible
- Check that search endpoints are properly configured
- Ensure you're using the correct base URL

### Search Returns No Results

**Possible Causes:**
- No tickets match the query
- Database is empty or not indexed
- Search index needs rebuilding

**Solution:**
```bash
cd /path/to/autotask-data-warehouse
python manage.py index_tickets
```

## Development

### Project Structure

```
mcp-autotask-search/
├── src/
│   └── autotask_search_mcp/
│       ├── __init__.py
│       └── server.py          # Main MCP server implementation
├── run.sh                     # Shell wrapper (creates venv, runs server)
├── pyproject.toml             # Python project config
├── README.md                  # This file
└── .env.example               # Example environment file
```

### Running in Development Mode

```bash
cd mcp-autotask-search
./run.sh
```

### Viewing Logs

All errors include unique grep codes (prefix: `MCPS-`) for easy log searching:

```bash
# Search logs for specific errors
grep "MCPS-CONN" logs.txt
grep "MCPS-AUTH" logs.txt
```

**Common Grep Codes:**
- `MCPS-INIT` - Server initialization
- `MCPS-START` - Server starting
- `MCPS-SEARCH` - Search request
- `MCPS-DETAIL` - Detail request
- `MCPS-NOKEY` - API key missing
- `MCPS-AUTH` - Authentication failed
- `MCPS-CONN` - Connection error
- `MCPS-404` - Endpoint not found
- `MCPS-SVR` - Server error
- `MCPS-TIMEOUT` - Request timeout
- `MCPS-ERR` - Unexpected error

## Technical Details

### Search Method

The server uses the `/api/search/double-reranked/` endpoint which combines:

1. **BM25** - Full-text search on titles, descriptions, and notes
2. **Vector Search** - Semantic search using embeddings
3. **Fuzzy Matching** - Handles typos and misspellings
4. **AI Reranking** - Cross-encoder model reranks for optimal relevance

### Response Format

Results are formatted for LLM readability:

```
Task #T20240216.0023 (ID: 12345) - Relevance: 0.95
Title: Password reset issue
Description: User cannot reset password...
Created: 2024-02-16 14:30
---
```

### Authentication

The server uses Bearer token authentication:

```
Authorization: Bearer <your-api-key>
```

## License

This is a POC/internal tool. See parent project for license information.

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review logs for grep codes
3. Verify Django server is running and accessible
4. Test API directly with curl

## Version

Current version: 0.1.0 (POC)
