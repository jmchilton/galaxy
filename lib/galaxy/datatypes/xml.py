"""
XML format classes
"""
import logging
import re

from . import (
    data,
    dataproviders,
    sniff
)

log = logging.getLogger(__name__)


@dataproviders.decorators.has_dataproviders
@sniff.build_sniff_from_prefix
class GenericXml(data.Text):
    """Base format class for any XML file."""
    edam_format = "format_2332"
    file_ext = "xml"

    def set_peek(self, dataset, is_multi_byte=False):
        """Set the peek and blurb text"""
        if not dataset.dataset.purged:
            dataset.peek = data.get_file_peek(dataset.file_name)
            dataset.blurb = 'XML data'
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def sniff_prefix(self, file_prefix):
        """
        Determines whether the file is XML or not

        >>> from galaxy.datatypes.sniff import get_test_fname
        >>> fname = get_test_fname( 'megablast_xml_parser_test1.blastxml' )
        >>> GenericXml().sniff( fname )
        True
        >>> fname = get_test_fname( 'interval.interval' )
        >>> GenericXml().sniff( fname )
        False
        """
        return file_prefix.contents_header.startswith('<?xml ')

    def merge(split_files, output_file):
        """Merging multiple XML files is non-trivial and must be done in subclasses."""
        if len(split_files) > 1:
            raise NotImplementedError("Merging multiple XML files is non-trivial and must be implemented for each XML type")
        # For one file only, use base class method (move/copy)
        data.Text.merge(split_files, output_file)
    merge = staticmethod(merge)

    @dataproviders.decorators.dataprovider_factory('xml', dataproviders.hierarchy.XMLDataProvider.settings)
    def xml_dataprovider(self, dataset, **settings):
        dataset_source = dataproviders.dataset.DatasetDataProvider(dataset)
        return dataproviders.hierarchy.XMLDataProvider(dataset_source, **settings)


class MEMEXml(GenericXml):
    """MEME XML Output data"""
    file_ext = "memexml"

    def set_peek(self, dataset, is_multi_byte=False):
        """Set the peek and blurb text"""
        if not dataset.dataset.purged:
            dataset.peek = data.get_file_peek(dataset.file_name)
            dataset.blurb = 'MEME XML data'
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def sniff(self, filename):
        return False


class CisML(GenericXml):
    """CisML XML data"""  # see: http://www.ncbi.nlm.nih.gov/pubmed/15001475
    file_ext = "cisml"

    def set_peek(self, dataset, is_multi_byte=False):
        """Set the peek and blurb text"""
        if not dataset.dataset.purged:
            dataset.peek = data.get_file_peek(dataset.file_name)
            dataset.blurb = 'CisML data'
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def sniff(self, filename):
        return False


class Phyloxml(GenericXml):
    """Format for defining phyloxml data http://www.phyloxml.org/"""
    edam_data = "data_0872"
    edam_format = "format_3159"
    file_ext = "phyloxml"

    def set_peek(self, dataset, is_multi_byte=False):
        """Set the peek and blurb text"""
        if not dataset.dataset.purged:
            dataset.peek = data.get_file_peek(dataset.file_name)
            dataset.blurb = 'Phyloxml data'
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def sniff_prefix(self, file_prefix):
        """"Checking for keyword - 'phyloxml' always in lowercase in the first few lines"""
        return "phyloxml" in file_prefix.contents_header

    def get_visualizations(self, dataset):
        """
        Returns a list of visualizations for datatype.
        """

        return ['phyloviz']


class Owl(GenericXml):
    """
        Web Ontology Language OWL format description
        http://www.w3.org/TR/owl-ref/
    """
    edam_format = "format_3262"
    file_ext = "owl"

    def set_peek(self, dataset, is_multi_byte=False):
        if not dataset.dataset.purged:
            dataset.peek = data.get_file_peek(dataset.file_name)
            dataset.blurb = "Web Ontology Language OWL"
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disc'

    def sniff_prefix(self, file_prefix):
        """
            Checking for keyword - '<owl' in the first 200 lines.
        """
        owl_marker = re.compile(r'\<owl:')
        return owl_marker.search(file_prefix.contents_header)
