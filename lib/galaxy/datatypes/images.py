"""
Image classes
"""
import logging
import zipfile

from galaxy.datatypes.text import Html as HtmlFromText
from galaxy.util import nice_size
from galaxy.util.image_util import check_image_type
from . import data

log = logging.getLogger(__name__)

# TODO: Uploading image files of various types is supported in Galaxy, but on
# the main public instance, the display_in_upload is not set for these data
# types in datatypes_conf.xml because we do not allow image files to be uploaded
# there.  There is currently no API feature that allows uploading files outside
# of a data library ( where it requires either the upload_paths or upload_directory
# option to be enabled, which is not the case on the main public instance ).  Because
# of this, we're currently safe, but when the api is enhanced to allow other uploads,
# we need to ensure that the implementation is such that image files cannot be uploaded
# to our main public instance.


class Image(data.Data):
    """Class describing an image"""
    edam_data = 'data_2968'
    edam_format = "format_3547"
    file_ext = ''

    def __init__(self, **kwd):
        super(Image, self).__init__(**kwd)
        self.image_formats = [self.file_ext.upper()]

    def set_peek(self, dataset, is_multi_byte=False):
        if not dataset.dataset.purged:
            dataset.peek = 'Image in %s format' % dataset.extension
            dataset.blurb = nice_size(dataset.get_size())
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def sniff(self, filename):
        """Determine if the file is in this format"""
        return check_image_type(filename, self.image_formats)


class Jpg(Image):
    edam_format = "format_3579"
    file_ext = "jpg"

    def __init__(self, **kwd):
        super(Jpg, self).__init__(**kwd)
        self.image_formats = ['JPEG']


class Png(Image):
    edam_format = "format_3603"
    file_ext = "png"


class Tiff(Image):
    edam_format = "format_3591"
    file_ext = "tiff"


class Hamamatsu(Image):
    file_ext = "vms"


class Mirax(Image):
    file_ext = "mrxs"


class Sakura(Image):
    file_ext = "svslide"


class Nrrd(Image):
    file_ext = "nrrd"


class Bmp(Image):
    edam_format = "format_3592"
    file_ext = "bmp"


class Gif(Image):
    edam_format = "format_3467"
    file_ext = "gif"


class Im(Image):
    edam_format = "format_3593"
    file_ext = "im"


class Pcd(Image):
    edam_format = "format_3594"
    file_ext = "pcd"


class Pcx(Image):
    edam_format = "format_3595"
    file_ext = "pcx"


class Ppm(Image):
    edam_format = "format_3596"
    file_ext = "ppm"


class Psd(Image):
    edam_format = "format_3597"
    file_ext = "psd"


class Xbm(Image):
    edam_format = "format_3598"
    file_ext = "xbm"


class Xpm(Image):
    edam_format = "format_3599"
    file_ext = "xpm"


class Rgb(Image):
    edam_format = "format_3600"
    file_ext = "rgb"


class Pbm(Image):
    edam_format = "format_3601"
    file_ext = "pbm"


class Pgm(Image):
    edam_format = "format_3602"
    file_ext = "pgm"


class Eps(Image):
    edam_format = "format_3466"
    file_ext = "eps"


class Rast(Image):
    edam_format = "format_3605"
    file_ext = "rast"


class Pdf(Image):
    edam_format = "format_3508"
    file_ext = "pdf"

    def sniff(self, filename):
        """Determine if the file is in pdf format."""
        with open(filename, 'rb') as fh:
            return fh.read(4) == b"%PDF"


class Gmaj(data.Data):
    """Class describing a GMAJ Applet"""
    edam_format = "format_3547"
    file_ext = "gmaj.zip"

    def set_peek(self, dataset, is_multi_byte=False):
        if not dataset.dataset.purged:
            dataset.peek = 'GMAJ Multiple Alignment - applet launch functionality no longer available in Galaxy.'
            dataset.blurb = 'GMAJ Multiple Alignment'
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def display_peek(self, dataset):
        try:
            return dataset.peek
        except Exception:
            return "peek unavailable"

    def get_mime(self):
        """Returns the mime type of the datatype"""
        return 'application/zip'

    def sniff(self, filename):
        """
        NOTE: the sniff.convert_newlines() call in the upload utility will keep Gmaj data types from being
        correctly sniffed, but the files can be uploaded (they'll be sniffed as 'txt').  This sniff function
        is here to provide an example of a sniffer for a zip file.
        """
        if not zipfile.is_zipfile(filename):
            return False
        contains_gmaj_file = False
        with zipfile.ZipFile(filename, "r") as zip_file:
            for name in zip_file.namelist():
                if name.split(".")[1].strip().lower() == 'gmaj':
                    contains_gmaj_file = True
                    break
        if not contains_gmaj_file:
            return False
        return True


class Html(HtmlFromText):
    """Deprecated class. This class should not be used anymore, but the galaxy.datatypes.text:Html one.
    This is for backwards compatibilities only."""


class Laj(data.Text):
    """Class describing a LAJ Applet"""
    file_ext = "laj"

    def set_peek(self, dataset, is_multi_byte=False):
        if not dataset.dataset.purged:
            dataset.peek = 'LAJ Multiple Alignment - applet launch functionality no longer available in Galaxy.'
            dataset.blurb = 'LAJ Multiple Alignment'
        else:
            dataset.peek = 'file does not exist'
            dataset.blurb = 'file purged from disk'

    def display_peek(self, dataset):
        try:
            return dataset.peek
        except Exception:
            return "peek unavailable"
