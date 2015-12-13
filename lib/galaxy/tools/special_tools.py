import logging
log = logging.getLogger( __name__ )

SPECIAL_TOOLS = {
    "history export": "galaxy/tools/imp_exp/exp_history_to_archive.xml",
    "history import": "galaxy/tools/imp_exp/imp_history_from_archive.xml",
    "collection unzip": "galaxy/tools/unzip_collection.xml",
    "collection zip": "galaxy/tools/zip_collection.xml",
    "filter failed datasets": "galaxy/tools/filter_failed_collection.xml",
    "filter datasets": "galaxy/tools/filter_collection.xml",
}


def load_lib_tools( toolbox ):
    for name, path in SPECIAL_TOOLS.items():
        tool = toolbox.load_hidden_lib_tool( path )
        log.debug( "Loaded %s tool: %s", name, tool.id )
