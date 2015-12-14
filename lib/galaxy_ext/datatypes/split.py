import os
import sys

from optparse import OptionParser

# insert *this* galaxy before all others on sys.path
sys.path.insert( 1, os.path.abspath( os.path.join( os.path.dirname( __file__ ), os.pardir, os.pardir ) ) )

import galaxy.scripts


def main(argv=sys.argv):
    log = galaxy.scripts.get_and_setup_log(__name__)
    galaxy.scripts.setup_mapping()

    parser = OptionParser()
    parser.add_option("--integrated_tool_conf")
    parser.add_option("--datatype_extension")
    parser.add_option("--parameters")

    (options, args) = parser.parse_args()

    datatypes_registry = galaxy.scripts.get_datatypes_registry(options.integrated_tool_conf)
    datatype = datatypes_registry.get_datatype_by_extension(options.datatype_extension)
    pass


if __name__ == '__main__':
    main()
