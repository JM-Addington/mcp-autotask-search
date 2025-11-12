# ./mcp-autotask-search/src/autotask_search_mcp/server.py

"""
Autotask Search MCP Server

Exposes Autotask ticket search functionality via Model Context Protocol.
Uses FastMCP for server implementation.
"""

import os
import json
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

# NOTE: Removed text formatting functions - now returning structured JSON directly
# to allow MCP clients to display data in their preferred format


@mcp.tool()
async def search_tickets(
    query: str,
    limit: int = 10,
    start_date: str = "",
    end_date: str = "",
    sentiment: str = "",
    min_frustration: float | None = None,
    priority_only: bool = False
) -> str:
    """
    Search Autotask tickets using advanced semantic and keyword search with sentiment filtering.

    This tool uses a sophisticated multi-method search combining:
    - BM25 full-text search
    - Semantic vector search
    - Fuzzy matching for typos
    - AI-powered reranking for relevance
    - Sentiment analysis filtering

    Args:
        query: Search query (supports partial company names, keywords, descriptions).
               Works well with imperfect queries including typos and vague descriptions.
        limit: Maximum number of results to return (default: 10, max: 100)
        start_date: Optional start date filter in YYYY-MM-DD format (e.g., "2024-01-01").
                   Only tickets created on or after this date will be returned.
        end_date: Optional end date filter in YYYY-MM-DD format (e.g., "2024-12-31").
                 Only tickets created on or before this date will be returned.
        sentiment: Optional sentiment filter. Valid values: "negative", "neutral", "positive".
                  Only tickets with the specified sentiment will be returned.
        min_frustration: Optional minimum frustration score filter (0.0 to 1.0).
                        Only tickets with frustration scores >= this value will be returned.
        priority_only: If True, only return tickets flagged as priority (high negative sentiment + high frustration).

    Returns:
        Formatted search results with task numbers, titles, descriptions, relevance scores, and sentiment data.
        Results are ranked by relevance with the most relevant tickets first.

    Examples:
        - "password reset issues"
        - "outlook email problems for ABC Company"
        - "network connectivity" with sentiment="negative"
        - "support tickets" with min_frustration=0.7
        - "customer issues" with priority_only=True
    """
    logger.info(f"Searching tickets with query: '{query}' (limit: {limit}, dates: {start_date} to {end_date}, sentiment: {sentiment}, frustration: {min_frustration}, priority: {priority_only}) [MCPS-SEARCH]")

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

            # Add date filters if provided
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            # Add sentiment filters if provided
            if sentiment:
                params["sentiment"] = sentiment
            if min_frustration is not None:
                params["min_frustration"] = str(min_frustration)
            if priority_only:
                params["priority_only"] = "true"

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
                return json.dumps({
                    "query": query,
                    "count": 0,
                    "results": []
                }, indent=2)

            # Return structured JSON response
            response_data = {
                "query": query,
                "count": len(results),
                "filters": data.get('filters', {}),
                "results": results
            }

            logger.info(f"Returned {len(results)} results [MCPS-OK]")
            return json.dumps(response_data, indent=2)

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

            # Return structured JSON response
            logger.info(f"Retrieved details for task_id: {task_id} [MCPS-OK]")
            return json.dumps(ticket, indent=2)

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


@mcp.tool()
async def get_tickets_notes(task_ids: list[int] = None, task_numbers: list[str] = None) -> str:
    """
    Get notes for multiple tickets in bulk.

    Retrieve all human-created notes for specified tickets. You can provide either
    task IDs, ticket numbers, or both. This is more efficient than calling
    get_ticket_details multiple times when you only need the notes.

    Args:
        task_ids: Optional list of task IDs (integers). Example: [12345, 67890]
        task_numbers: Optional list of ticket numbers (strings). Example: ["T20240101.0001", "T20240102.0005"]

    Returns:
        All notes for the specified tickets, grouped by ticket and sorted chronologically.
        Each note includes timestamp, optional title, and full content.

    Notes:
        - At least one parameter (task_ids or task_numbers) must be provided
        - Maximum of 50 tickets can be requested at once
        - Only returns human-created notes (system-generated notes are excluded)

    Examples:
        - get_tickets_notes(task_ids=[12345, 67890])
        - get_tickets_notes(task_numbers=["T20240101.0001", "T20240102.0005"])
        - get_tickets_notes(task_ids=[12345], task_numbers=["T20240101.0001"])
    """
    # AIDEV-NOTE: bulk-notes-retrieval; supports both task_id and task_number lookups
    logger.info(f"Getting notes for task_ids: {task_ids}, task_numbers: {task_numbers} [MCPS-NOTES-REQ]")

    # Validate parameters
    if not task_ids and not task_numbers:
        logger.error("No task_ids or task_numbers provided [MCPS-NOTES-NOPARAM]")
        return "Error: At least one of task_ids or task_numbers must be provided."

    # Convert None to empty lists for easier handling
    task_ids = task_ids or []
    task_numbers = task_numbers or []

    # Validate total count
    total_requested = len(task_ids) + len(task_numbers)
    if total_requested > 50:
        logger.error(f"Too many tickets requested: {total_requested} [MCPS-NOTES-LIMIT]")
        return f"Error: Cannot request more than 50 tickets at once. You requested {total_requested}."

    if total_requested == 0:
        logger.error("Empty lists provided [MCPS-NOTES-EMPTY]")
        return "Error: task_ids and task_numbers cannot both be empty lists."

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
            url = f"{BASE_URL}/api/tickets/notes/"

            # Build request body
            body = {}
            if task_ids:
                body["task_ids"] = task_ids
            if task_numbers:
                body["task_numbers"] = task_numbers

            logger.info(f"Making POST request to: {url} [MCPS-NOTES-POST]")

            response = await client.post(url, headers=headers, json=body)

            # Check for errors
            if response.status_code == 401:
                logger.error("Authentication failed [MCPS-NOTES-AUTH]")
                return (
                    "Error: Authentication failed. Please check your AUTOTASK_API_KEY."
                )

            if response.status_code == 400:
                logger.error(f"Bad request: {response.text} [MCPS-NOTES-BADREQ]")
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', 'Invalid request parameters')
                    return f"Error: {error_msg}"
                except Exception:
                    return f"Error: Bad request - {response.text}"

            if response.status_code == 404:
                logger.error("API endpoint not found [MCPS-NOTES-404]")
                return (
                    f"Error: API endpoint not found at {BASE_URL}. "
                    "Please check that the Autotask Django server is running and up to date."
                )

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-NOTES-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask service may be experiencing issues."
                )

            response.raise_for_status()
            data = response.json()

            # Return structured JSON response
            logger.info(f"Retrieved notes for {data.get('total_tickets', 0)} tickets [MCPS-NOTES-OK]")
            return json.dumps(data, indent=2)

    except httpx.ConnectError:
        logger.error(f"Connection failed to {BASE_URL} [MCPS-NOTES-CONN]")
        return (
            f"Error: Could not connect to Autotask API at {BASE_URL}. "
            "Please check that the Django server is running."
        )
    except httpx.TimeoutException:
        logger.error("Request timeout [MCPS-NOTES-TIMEOUT]")
        return "Error: Request timed out. Please try again."
    except Exception as e:
        logger.error(f"Unexpected error getting bulk notes: {str(e)} [MCPS-NOTES-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


def main():
    """Main entry point for the MCP server."""
    logger.info("Starting Autotask Search MCP Server [MCPS-START]")
    mcp.run()


if __name__ == "__main__":
    main()
