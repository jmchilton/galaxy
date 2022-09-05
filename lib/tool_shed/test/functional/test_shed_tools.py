from ..base.api import ShedApiTestCase


class ShedToolsApiTestCase(ShedApiTestCase):
    def test_tool_search(self):
        populator = self.populator
        repository = populator.setup_column_maker_repo(prefix="toolsearch")
        populator.reindex()
        response = populator.tool_search_query("Compute")
        hit_count = len(response.hits)
        assert hit_count >= 1

        tool_search_hit = response.find_search_hit(repository)
        assert tool_search_hit
        assert tool_search_hit.tool.id == "Add_a_column1"
        assert tool_search_hit.tool.name == "Compute"

        # ensure re-index doesn't modify number of hits (regression of an issue pre-Fall 2022)
        response = populator.reindex()
        response = populator.reindex()

        response = populator.tool_search_query("Compute")
        new_hit_count = len(response.hits)

        assert hit_count == new_hit_count

        tool_search_hit = response.find_search_hit(repository)
        assert tool_search_hit
