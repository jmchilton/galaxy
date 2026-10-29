from tool_shed.webapp.config import ToolShedAppConfiguration


def test_citation_cache_url():
    config = ToolShedAppConfiguration(
        citation_cache_url="postgresql:///citations", citation_cache_lock_dir="/tmp/locks", override_tempdir=False
    )
    assert config.citation_cache_url == "postgresql:///citations"
