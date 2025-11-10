# ./mcp-autotask-search/src/autotask_search_mcp/server.py

"""
Autotask Search MCP Server

Exposes Autotask ticket search functionality via Model Context Protocol.
Uses FastMCP for server implementation.
"""

import os
import logging
from typing import Any
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Autotask Search")

# Configuration
API_KEY = os.getenv("AUTOTASK_API_KEY")
BASE_URL = os.getenv("AUTOTASK_API_BASE_URL", "http://localhost:8000")

# AIDEV-NOTE: config-validation; API key required for auth, base URL defaults to localhost
if not API_KEY:
    logger.error("AUTOTASK_API_KEY environment variable not set [MCPS-NOKEY]")
    raise ValueError(
        "AUTOTASK_API_KEY environment variable is required. "
        "Please set it in your .env file or Claude Desktop config. "
        "See README.md for setup instructions."
    )

logger.info(f"Autotask Search MCP Server initialized with base URL: {BASE_URL} [MCPS-INIT]")


def format_ticket_for_llm(ticket: dict) -> str:
    """
    Format a ticket result for optimal LLM readability.

    AIDEV-NOTE: llm-formatting; structured text format preferred over JSON for LLM consumption
    """
    task_number = ticket.get('task_number', 'N/A')
    task_id = ticket.get('task_id', 'N/A')
    score = ticket.get('score', 0.0)
    title = ticket.get('task_name', 'No title')
    description = ticket.get('task_description', 'No description')
    created = ticket.get('create_time', 'Unknown')

    # Format creation date if available
    if created and created != 'Unknown':
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            created = dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass

    return f"""Task #{task_number} (ID: {task_id}) - Relevance: {score:.2f}
Title: {title}
Description: {description}
Created: {created}
---"""


def format_ticket_details_for_llm(ticket: dict) -> str:
    """
    Format detailed ticket information for LLM readability.

    AIDEV-NOTE: llm-formatting; includes full ticket data with notes
    """
    task_number = ticket.get('task_number', 'N/A')
    task_id = ticket.get('task_id', 'N/A')
    title = ticket.get('task_name', 'No title')
    description = ticket.get('task_description', 'No description')
    created = ticket.get('create_time', 'Unknown')
    status = ticket.get('status', 'Unknown')
    priority = ticket.get('priority', 'Unknown')

    # Format creation date
    if created and created != 'Unknown':
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            created = dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass

    result = f"""=== Task #{task_number} (ID: {task_id}) ===
Title: {title}
Description: {description}
Status: {status}
Priority: {priority}
Created: {created}

"""

    # Add notes if available
    notes = ticket.get('human_created_notes', [])
    if notes:
        result += "Notes:\n"
        for i, note in enumerate(notes, 1):
            note_text = note.get('note_text', '')
            note_date = note.get('create_date_time', '')
            if note_date:
                try:
                    dt = datetime.fromisoformat(note_date.replace('Z', '+00:00'))
                    note_date = dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    pass
            result += f"\n[Note {i} - {note_date}]\n{note_text}\n"
    else:
        result += "Notes: None\n"

    return result


@mcp.tool()
async def search_tickets(query: str, limit: int = 10) -> str:
    """
    Search Autotask tickets using advanced semantic and keyword search.

    This tool uses a sophisticated multi-method search combining:
    - BM25 full-text search
    - Semantic vector search
    - Fuzzy matching for typos
    - AI-powered reranking for relevance

    Args:
        query: Search query (supports partial company names, keywords, descriptions).
               Works well with imperfect queries including typos and vague descriptions.
        limit: Maximum number of results to return (default: 10, max: 100)

    Returns:
        Formatted search results with task numbers, titles, descriptions, and relevance scores.
        Results are ranked by relevance with the most relevant tickets first.

    Examples:
        - "password reset issues"
        - "outlook email problems for ABC Company"
        - "network connectivity"
        - "slow computer performance"
    """
    logger.info(f"Searching tickets with query: '{query}' (limit: {limit}) [MCPS-SEARCH]")

    # Validate limit
    if limit < 1:
        limit = 10
    if limit > 100:
        limit = 100

    try:
        # Make API request using Bearer token auth
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            params = {"q": query, "limit": limit}

            url = f"{BASE_URL}/api/search/double-reranked/"
            logger.info(f"Making request to: {url} [MCPS-REQ]")

            response = await client.get(url, headers=headers, params=params)

            # Check for errors
            if response.status_code == 401:
                logger.error(f"Authentication failed [MCPS-AUTH]")
                return (
                    "Error: Authentication failed. Please check your AUTOTASK_API_KEY. "
                    "The API key may be invalid or expired."
                )

            if response.status_code == 404:
                logger.error(f"API endpoint not found [MCPS-404]")
                return (
                    f"Error: API endpoint not found at {BASE_URL}. "
                    "Please check that the Autotask Django server is running and "
                    "AUTOTASK_API_BASE_URL is set correctly."
                )

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask search service may be experiencing issues."
                )

            response.raise_for_status()
            data = response.json()

            # Extract results
            results = data.get('results', [])

            if not results:
                logger.info(f"No results found for query: '{query}' [MCPS-NORES]")
                return f"No tickets found matching query: '{query}'"

            # Format results for LLM
            formatted_results = []
            formatted_results.append(f"Found {len(results)} tickets matching '{query}':\n")

            for ticket in results:
                formatted_results.append(format_ticket_for_llm(ticket))

            result_text = "\n".join(formatted_results)
            logger.info(f"Returned {len(results)} results [MCPS-OK]")
            return result_text

    except httpx.ConnectError:
        logger.error(f"Connection failed to {BASE_URL} [MCPS-CONN]")
        return (
            f"Error: Could not connect to Autotask API at {BASE_URL}. "
            "Please check that the Django server is running with: "
            "python manage.py runserver"
        )
    except httpx.TimeoutException:
        logger.error(f"Request timeout [MCPS-TIMEOUT]")
        return (
            "Error: Request timed out. The search may be taking too long. "
            "Try a more specific query or check server performance."
        )
    except Exception as e:
        logger.error(f"Unexpected error during search: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool()
async def get_ticket_details(task_id: int) -> str:
    """
    Get complete details for a specific ticket including all notes.

    Use this tool when you need full information about a specific ticket,
    including the complete description and all human-created notes.
    This provides more context than search results alone.

    Args:
        task_id: The numeric task ID (from search results)

    Returns:
        Complete ticket information including title, description, status,
        priority, creation date, and all notes with timestamps.

    Example:
        get_ticket_details(12345)
    """
    logger.info(f"Getting details for task_id: {task_id} [MCPS-DETAIL]")

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            url = f"{BASE_URL}/api/ticket/{task_id}/"

            logger.info(f"Making request to: {url} [MCPS-REQ]")

            response = await client.get(url, headers=headers)

            # Check for errors
            if response.status_code == 401:
                logger.error(f"Authentication failed [MCPS-AUTH]")
                return (
                    "Error: Authentication failed. Please check your AUTOTASK_API_KEY."
                )

            if response.status_code == 404:
                logger.error(f"Ticket not found: {task_id} [MCPS-NOTFOUND]")
                return f"Error: Ticket with ID {task_id} not found."

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask service may be experiencing issues."
                )

            response.raise_for_status()
            ticket = response.json()

            # Format ticket details for LLM
            result = format_ticket_details_for_llm(ticket)
            logger.info(f"Retrieved details for task_id: {task_id} [MCPS-OK]")
            return result

    except httpx.ConnectError:
        logger.error(f"Connection failed to {BASE_URL} [MCPS-CONN]")
        return (
            f"Error: Could not connect to Autotask API at {BASE_URL}. "
            "Please check that the Django server is running."
        )
    except httpx.TimeoutException:
        logger.error(f"Request timeout [MCPS-TIMEOUT]")
        return "Error: Request timed out. Please try again."
    except Exception as e:
        logger.error(f"Unexpected error getting ticket details: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


def main():
    """Main entry point for the MCP server."""
    logger.info("Starting Autotask Search MCP Server [MCPS-START]")
    mcp.run()


if __name__ == "__main__":
    main()
