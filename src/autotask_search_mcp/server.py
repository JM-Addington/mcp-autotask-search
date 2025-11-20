# ./mcp-autotask-search/src/autotask_search_mcp/server.py

"""
Autotask Search MCP Server

Exposes Autotask ticket search functionality via Model Context Protocol.
Uses FastMCP for server implementation.
"""

import os
import json
import logging
import asyncio
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
    page: int = 1,
    per_page: int = 10,
    start_date: str = "",
    end_date: str = "",
    sentiment: str = "",
    min_frustration: float | None = None,
    priority_only: bool = False
) -> str:
    """
    Search Autotask tickets using advanced semantic and keyword search with sentiment filtering and pagination.

    This tool uses a sophisticated multi-method search combining:
    - BM25 full-text search
    - Semantic vector search
    - Fuzzy matching for typos
    - AI-powered reranking for relevance
    - Sentiment analysis filtering
    - Redis caching for fast pagination

    Args:
        query: Search query (supports partial company names, keywords, descriptions).
               Works well with imperfect queries including typos and vague descriptions.
        page: Page number to retrieve (default: 1, starts at 1)
        per_page: Results per page (default: 10, max: 100)
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
        Formatted search results with task numbers, titles, descriptions, relevance scores, sentiment data,
        and pagination information. Results are ranked by relevance with the most relevant tickets first.

    Examples:
        - "password reset issues"
        - "outlook email problems for ABC Company" page=2
        - "network connectivity" with sentiment="negative" per_page=25
        - "support tickets" with min_frustration=0.7
        - "customer issues" with priority_only=True
    """
    logger.info(f"Searching tickets with query: '{query}' (page: {page}, per_page: {per_page}, dates: {start_date} to {end_date}, sentiment: {sentiment}, frustration: {min_frustration}, priority: {priority_only}) [MCPS-SEARCH]")

    # Validate pagination parameters
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 10
    if per_page > 100:
        per_page = 100

    try:
        # Make API request using Bearer token auth
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            params = {"q": query, "page": page, "per_page": per_page}

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

            # Handle async task response (202 Accepted)
            if response.status_code == 202:
                data = response.json()
                task_id = data.get('task_id')
                logger.info(f"Search is processing asynchronously, task_id: {task_id} [MCPS-ASYNC]")

                # Poll for task completion
                status_url = f"{BASE_URL}/api/search/status/{task_id}/"
                max_polls = 20  # Poll for up to 60 seconds (3s * 20)

                for poll_attempt in range(max_polls):
                    await asyncio.sleep(3)  # Wait 3 seconds between polls
                    status_response = await client.get(status_url, headers=headers)
                    status_data = status_response.json()

                    if status_data.get('status') == 'SUCCESS':
                        logger.info(f"Async search completed [MCPS-ASYNC-OK]")
                        # Retry the original search request now that results are cached
                        response = await client.get(url, headers=headers, params=params)
                        break
                    elif status_data.get('status') == 'FAILURE':
                        logger.error(f"Async search failed [MCPS-ASYNC-FAIL]")
                        return json.dumps({
                            "error": "Search task failed",
                            "details": status_data.get('error', 'Unknown error')
                        }, indent=2)

                    logger.info(f"Polling attempt {poll_attempt + 1}/{max_polls} [MCPS-POLL]")

                # If we exhausted polls, return status
                if response.status_code == 202:
                    return json.dumps({
                        "status": "processing",
                        "message": "Search is still processing. Please try again in a few moments.",
                        "task_id": task_id
                    }, indent=2)

            response.raise_for_status()
            data = response.json()

            # Extract results and pagination
            results = data.get('results', [])
            pagination = data.get('pagination', {})

            if not results:
                logger.info(f"No results found for query: '{query}' [MCPS-NORES]")
                return json.dumps({
                    "query": query,
                    "count": 0,
                    "pagination": pagination,
                    "results": []
                }, indent=2)

            # Return structured JSON response with pagination
            response_data = {
                "query": query,
                "count": len(results),
                "pagination": pagination,
                "filters": data.get('filters', {}),
                "cache_hit": data.get('cache_hit', False),
                "results": results
            }

            logger.info(f"Returned {len(results)} results (page {pagination.get('current_page', page)} of {pagination.get('total_pages', '?')}) [MCPS-OK]")
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
async def get_tickets_details(task_ids: list[int]) -> str:
    """
    Get complete details for multiple tickets including all notes and time entries.

    This tool fetches full ticket information for multiple tickets in a single request.
    More efficient than calling get_ticket_details multiple times when you need
    details for several tickets.

    Args:
        task_ids: List of task IDs to retrieve (max 50)

    Returns:
        JSON object with array of complete ticket details including title,
        description, notes, time entries, sentiment, and related tickets.

    Example:
        get_tickets_details([12345, 67890, 11111])
    """
    logger.info(f"Getting details for {len(task_ids)} tickets [MCPS-DETAILS-BATCH]")

    # Validate input
    if not task_ids:
        return "Error: task_ids cannot be empty"

    if len(task_ids) > 50:
        return f"Error: Maximum 50 tickets allowed. You requested {len(task_ids)}."

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
            url = f"{BASE_URL}/api/tickets/details/"

            logger.info(f"Making POST request to: {url} [MCPS-REQ]")

            response = await client.post(url, headers=headers, json={"task_ids": task_ids})

            # Check for errors
            if response.status_code == 401:
                logger.error(f"Authentication failed [MCPS-AUTH]")
                return (
                    "Error: Authentication failed. Please check your AUTOTASK_API_KEY."
                )

            if response.status_code == 400:
                logger.error(f"Bad request: {response.text} [MCPS-BADREQ]")
                try:
                    error_data = response.json()
                    return f"Error: {error_data.get('error', 'Invalid request')}"
                except Exception:
                    return f"Error: Bad request - {response.text}"

            if response.status_code == 404:
                logger.error(f"API endpoint not found [MCPS-404]")
                return (
                    f"Error: API endpoint not found at {BASE_URL}. "
                    "Please check that the Autotask Django server is running and up to date."
                )

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask service may be experiencing issues."
                )

            response.raise_for_status()
            data = response.json()

            # Return structured JSON response
            logger.info(f"Retrieved details for {data.get('total_found', 0)} of {data.get('total_requested', 0)} tickets [MCPS-OK]")
            return json.dumps(data, indent=2)

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
        logger.error(f"Unexpected error getting batch ticket details: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool()
async def get_related_tickets(
    task_id: int,
    page: int = 1,
    per_page: int = 10
) -> str:
    """
    Find tickets semantically related to a given ticket using vector similarity and AI re-ranking.

    This tool finds tickets that are similar in content, topic, or issue type by:
    1. Using vector embeddings to find semantically similar tickets
    2. Re-ranking results with an AI model for optimal relevance
    3. Returning the most related tickets with relevance scores

    This is useful for:
    - Finding similar issues or tickets
    - Discovering patterns across related tickets
    - Finding tickets that might share the same root cause
    - Research and analysis of ticket trends

    Args:
        task_id: The numeric task ID of the ticket to find related tickets for
        page: Page number (default: 1). Note: Currently only page 1 is supported.
        per_page: Results per page (default: 10, max: 30)

    Returns:
        List of related tickets with task numbers, titles, and relevance scores.
        Results are ranked by relevance with the most related tickets first.

    Example:
        get_related_tickets(12345, per_page=10)
    """
    logger.info(f"Finding related tickets for task_id: {task_id} (page: {page}, per_page: {per_page}) [MCPS-RELATED]")

    # Validate pagination parameters
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 10
    if per_page > 30:
        per_page = 30

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            # API endpoint uses 'limit' parameter (pagination not yet supported in API)
            params = {"limit": per_page}
            url = f"{BASE_URL}/api/ticket/{task_id}/related/"

            logger.info(f"Making request to: {url} [MCPS-REQ]")

            response = await client.get(url, headers=headers, params=params)

            # Check for errors
            if response.status_code == 401:
                logger.error(f"Authentication failed [MCPS-AUTH]")
                return (
                    "Error: Authentication failed. Please check your AUTOTASK_API_KEY."
                )

            if response.status_code == 404:
                logger.error(f"Ticket not found or endpoint not available: {task_id} [MCPS-NOTFOUND]")
                return f"Error: Ticket with ID {task_id} not found or related tickets endpoint not available."

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask service may be experiencing issues."
                )

            response.raise_for_status()
            data = response.json()

            # Return structured JSON response
            logger.info(f"Retrieved {len(data.get('related_tickets', []))} related tickets for task_id: {task_id} [MCPS-OK]")
            return json.dumps(data, indent=2)

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
        logger.error(f"Unexpected error getting related tickets: {str(e)} [MCPS-ERR]")
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


@mcp.tool()
async def search_companies(
    query: str = "",
    page: int = 1,
    per_page: int = 25,
    active_only: bool = True,
    match_type: str = "fuzzy"
) -> str:
    """
    Search for companies (accounts) in Autotask.

    This tool searches the Autotask companies/accounts database using various
    matching strategies. It's useful for finding company information, looking up
    account IDs for filtering other searches, or exploring the customer base.

    Args:
        query: Search query (optional, returns all if not provided). Searches company names.
        page: Page number (default: 1, starts at 1)
        per_page: Results per page (default: 25, max: 100)
        active_only: Filter for active companies only (default: true)
        match_type: Search match type (default: "fuzzy")
                   - "fuzzy": Handles typos and partial matches (recommended)
                   - "exact": Exact match only
                   - "wildcard": SQL wildcard matching (% and _)

    Returns:
        List of companies with account IDs, names, active status, and pagination info.

    Examples:
        - search_companies(query="Acme Corp")
        - search_companies(query="tech", active_only=True, per_page=50)
        - search_companies(match_type="exact", query="ABC Company")
    """
    logger.info(f"Searching companies with query: '{query}' (page: {page}, per_page: {per_page}, active_only: {active_only}, match_type: {match_type}) [MCPS-SEARCH-COMPANIES]")

    # Validate pagination parameters
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 25
    if per_page > 100:
        per_page = 100

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            params = {
                'page': page,
                'per_page': per_page,
                'active_only': 'true' if active_only else 'false',
                'match_type': match_type
            }

            if query:
                params['q'] = query

            url = f"{BASE_URL}/api/companies/search/"
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

            if not data.get('success'):
                logger.error(f"API returned error: {data.get('error', 'Unknown error')} [MCPS-ERR]")
                return json.dumps({
                    'error': data.get('error', 'Unknown error occurred'),
                    'companies': [],
                    'pagination': {},
                    'filters': {}
                }, indent=2)

            companies = data.get('companies', [])
            pagination = data.get('pagination', {})

            response_data = {
                'query': query,
                'count': len(companies),
                'pagination': pagination,
                'filters': data.get('filters', {}),
                'companies': companies
            }

            logger.info(f"Returned {len(companies)} companies (page {pagination.get('current_page', page)} of {pagination.get('total_pages', '?')}) [MCPS-OK]")
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
            "Error: Request timed out. Please try again."
        )
    except Exception as e:
        logger.error(f"Unexpected error during company search: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool()
async def search_contacts(
    query: str = "",
    page: int = 1,
    per_page: int = 25,
    active_only: bool = True,
    match_type: str = "fuzzy",
    company_id: int = None
) -> str:
    """
    Search for contacts (account contacts) in Autotask.

    This tool searches the Autotask contacts database. It's useful for finding
    contact information, looking up contact IDs for filtering ticket searches,
    or exploring contacts associated with a specific company.

    Args:
        query: Search query (optional, returns all if not provided). Searches contact names.
        page: Page number (default: 1, starts at 1)
        per_page: Results per page (default: 25, max: 100)
        active_only: Filter for active contacts only (default: true)
        match_type: Search match type (default: "fuzzy")
                   - "fuzzy": Handles typos and partial matches (recommended)
                   - "exact": Exact match only
                   - "wildcard": SQL wildcard matching (% and _)
        company_id: Optional filter by company/account ID (from search_companies)

    Returns:
        List of contacts with contact IDs, names, company info, active status, and pagination info.

    Examples:
        - search_contacts(query="John Smith")
        - search_contacts(company_id=12345, active_only=True)
        - search_contacts(query="support", match_type="fuzzy", per_page=50)
    """
    logger.info(f"Searching contacts with query: '{query}' (page: {page}, per_page: {per_page}, active_only: {active_only}, match_type: {match_type}, company_id: {company_id}) [MCPS-SEARCH-CONTACTS]")

    # Validate pagination parameters
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 25
    if per_page > 100:
        per_page = 100

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            params = {
                'page': page,
                'per_page': per_page,
                'active_only': 'true' if active_only else 'false',
                'match_type': match_type
            }

            if query:
                params['q'] = query

            if company_id is not None:
                params['company_id'] = company_id

            url = f"{BASE_URL}/api/contacts/search/"
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

            if not data.get('success'):
                logger.error(f"API returned error: {data.get('error', 'Unknown error')} [MCPS-ERR]")
                return json.dumps({
                    'error': data.get('error', 'Unknown error occurred'),
                    'contacts': [],
                    'pagination': {},
                    'filters': {}
                }, indent=2)

            contacts = data.get('contacts', [])
            pagination = data.get('pagination', {})

            response_data = {
                'query': query,
                'count': len(contacts),
                'pagination': pagination,
                'filters': data.get('filters', {}),
                'contacts': contacts
            }

            logger.info(f"Returned {len(contacts)} contacts (page {pagination.get('current_page', page)} of {pagination.get('total_pages', '?')}) [MCPS-OK]")
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
            "Error: Request timed out. Please try again."
        )
    except Exception as e:
        logger.error(f"Unexpected error during contact search: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool()
async def get_tickets_company(company_ids: list[int]) -> str:
    """
    Get all tickets assigned to one or more companies.

    This tool retrieves tickets that are formally assigned to the specified companies
    in the Autotask system. Use this after finding companies with search_companies.

    Args:
        company_ids: List of company/account IDs (max 50)

    Returns:
        JSON with tickets assigned to these companies, including sentiment,
        summaries, and hours data. Returns up to 1000 most recent tickets.

    Example:
        get_tickets_company([12345, 67890])
    """
    logger.info(f"Getting tickets for {len(company_ids)} companies [MCPS-TICKETS-COMPANY]")

    # Validate input
    if not company_ids:
        return "Error: company_ids cannot be empty"

    if len(company_ids) > 50:
        return f"Error: Maximum 50 companies allowed. You requested {len(company_ids)}."

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
            url = f"{BASE_URL}/api/tickets/by-company/"

            logger.info(f"Making POST request to: {url} [MCPS-REQ]")

            response = await client.post(url, headers=headers, json={"company_ids": company_ids})

            # Check for errors
            if response.status_code == 401:
                logger.error(f"Authentication failed [MCPS-AUTH]")
                return "Error: Authentication failed. Please check your AUTOTASK_API_KEY."

            if response.status_code == 400:
                logger.error(f"Bad request: {response.text} [MCPS-BADREQ]")
                try:
                    error_data = response.json()
                    return f"Error: {error_data.get('error', 'Invalid request')}"
                except Exception:
                    return f"Error: Bad request - {response.text}"

            if response.status_code == 404:
                logger.error(f"API endpoint not found [MCPS-404]")
                return (
                    f"Error: API endpoint not found at {BASE_URL}. "
                    "Please check that the Autotask Django server is running and up to date."
                )

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask service may be experiencing issues."
                )

            response.raise_for_status()
            data = response.json()

            logger.info(f"Retrieved {data.get('total_tickets', 0)} tickets for {data.get('total_companies', 0)} companies [MCPS-OK]")
            return json.dumps(data, indent=2)

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
        logger.error(f"Unexpected error getting company tickets: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool()
async def get_tickets_contact(contact_ids: list[int]) -> str:
    """
    Get all tickets assigned to one or more contacts.

    This tool retrieves tickets that are formally assigned to the specified contacts
    in the Autotask system. Use this after finding contacts with search_contacts.

    Args:
        contact_ids: List of contact IDs (max 50)

    Returns:
        JSON with tickets assigned to these contacts, including sentiment,
        summaries, and hours data. Returns up to 1000 most recent tickets.

    Example:
        get_tickets_contact([12345, 67890])
    """
    logger.info(f"Getting tickets for {len(contact_ids)} contacts [MCPS-TICKETS-CONTACT]")

    # Validate input
    if not contact_ids:
        return "Error: contact_ids cannot be empty"

    if len(contact_ids) > 50:
        return f"Error: Maximum 50 contacts allowed. You requested {len(contact_ids)}."

    try:
        # Make API request
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
            url = f"{BASE_URL}/api/tickets/by-contact/"

            logger.info(f"Making POST request to: {url} [MCPS-REQ]")

            response = await client.post(url, headers=headers, json={"contact_ids": contact_ids})

            # Check for errors
            if response.status_code == 401:
                logger.error(f"Authentication failed [MCPS-AUTH]")
                return "Error: Authentication failed. Please check your AUTOTASK_API_KEY."

            if response.status_code == 400:
                logger.error(f"Bad request: {response.text} [MCPS-BADREQ]")
                try:
                    error_data = response.json()
                    return f"Error: {error_data.get('error', 'Invalid request')}"
                except Exception:
                    return f"Error: Bad request - {response.text}"

            if response.status_code == 404:
                logger.error(f"API endpoint not found [MCPS-404]")
                return (
                    f"Error: API endpoint not found at {BASE_URL}. "
                    "Please check that the Autotask Django server is running and up to date."
                )

            if response.status_code >= 500:
                logger.error(f"Server error: {response.status_code} [MCPS-SVR]")
                return (
                    f"Error: Server error ({response.status_code}). "
                    "The Autotask service may be experiencing issues."
                )

            response.raise_for_status()
            data = response.json()

            logger.info(f"Retrieved {data.get('total_tickets', 0)} tickets for {data.get('total_contacts', 0)} contacts [MCPS-OK]")
            return json.dumps(data, indent=2)

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
        logger.error(f"Unexpected error getting contact tickets: {str(e)} [MCPS-ERR]")
        return f"Error: An unexpected error occurred: {str(e)}"


def main():
    """Main entry point for the MCP server."""
    logger.info("Starting Autotask Search MCP Server [MCPS-START]")
    mcp.run()


if __name__ == "__main__":
    main()
