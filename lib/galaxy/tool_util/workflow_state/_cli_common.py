"""Shared argparse helpers for workflow_state CLI scripts."""

import logging


def add_common_args(parser):
    """Add --tool-source-cache-dir and -v/--verbose to any argparse parser."""
    parser.add_argument(
        "--tool-source-cache-dir",
        help="Cache directory (default: $GALAXY_TOOL_CACHE_DIR or ~/.galaxy/tool_info_cache/)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")


def add_tool_source_arg(parser):
    """Add --tool-source to any argparse parser."""
    parser.add_argument(
        "--tool-source",
        choices=["auto", "api", "galaxy"],
        default="auto",
        help="Source for tool definitions: auto (try api then galaxy), api, or galaxy (default: auto)",
    )


def add_populate_args(parser):
    """Add --populate-cache and --tool-source to any argparse parser."""
    parser.add_argument(
        "--populate-cache",
        action="store_true",
        help="Auto-populate tool cache from workflow before proceeding",
    )
    add_tool_source_arg(parser)


def setup_logging(verbose: bool):
    """Configure logging based on --verbose flag."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)
