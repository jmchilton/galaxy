import sys

# The security review needs Python 3.9 or later (galaxy.tool_util.security.review_tool_source).
collect_ignore_glob = ["test_*.py"] if sys.version_info < (3, 9) else []
