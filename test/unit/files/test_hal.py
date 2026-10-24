import pytest
import responses

from galaxy.exceptions import (
    MessageException,
    ObjectNotFound,
)
from galaxy.files.sources import DEFAULT_PAGE_LIMIT
from ._util import (
    assert_realizes_as,
    configured_file_sources,
    user_context_fixture,
)

pytestmark = pytest.mark.usefixtures("fake_public_dns")

API = "https://api.hal.science/search/"
FILE_URL = "https://hal.science/hal-01479142v2/file"
RECORD = {
    "halId_s": "hal-01479142",
    "version_i": 2,
    "title_s": ["Bovine SVs"],
    "files_s": ["https://hal.science/hal-01479142/file/main.pdf"],
    "fileAnnexes_s": [
        "https://hal.science/hal-01479142/file/a%20b.xlsx",
        "https://evil.example/hal-01479142/file/x.txt",
        "http://hal.science/hal-01479142/file/plain.txt",
        "https://hal.science/hal-01479142/file/..",
        "https://hal.science/hal-01479142/file/a%2Fb.txt",
        "https://hal.science/hal-99999999/file/other.txt",
        "https://hal.science/hal-01479142/extra/file/deep.txt",
    ],
}


def _sources():
    return configured_file_sources([{"type": "hal", "id": "hal"}])


def _src():
    return _sources().get_file_source_path("gxfiles://hal").file_source


def _list(path, **kwd):
    return _src().list(path, user_context=user_context_fixture(), **kwd)


def _search(docs, num_found=None):
    num_found = len(docs) if num_found is None else num_found
    responses.add(responses.GET, API, json={"response": {"docs": docs, "numFound": num_found}})


def _size(name, length, **headers):
    responses.add(responses.HEAD, f"{FILE_URL}/{name}", headers={"Content-Length": length, **headers})


@responses.activate
def test_root_lists_versioned_deposits_with_total():
    _search([RECORD], num_found=40)
    entries, total = _list("/", limit=1, offset=3, query="title_t:RNA")
    assert [(e.name, e.path) for e in entries] == [("Bovine SVs (hal-01479142v2)", "/hal-01479142v2")]
    assert total == 40
    params = responses.calls[0].request.params
    assert params["q"] == "title_t:RNA"
    assert params["rows"] == "1"
    assert params["start"] == "3"


@responses.activate
def test_deposit_lists_only_hal_https_files_with_pinned_head_sizes():
    _search([RECORD])
    _size("a%20b.xlsx", "555786")
    responses.add(responses.HEAD, f"{FILE_URL}/main.pdf", status=500)
    entries, total = _list("/hal-01479142v2")
    assert [(e.name, e.path, e.size) for e in entries] == [
        ("a b.xlsx", "/hal-01479142v2/a%20b.xlsx", 555786),
        ("main.pdf", "/hal-01479142v2/main.pdf", 0),
    ]
    assert total == 2


@responses.activate
def test_size_is_zero_for_encoded_or_invalid_length():
    _search([RECORD])
    _size("a%20b.xlsx", "100", **{"Content-Encoding": "gzip"})
    _size("main.pdf", "12abc")
    entries, _ = _list("/hal-01479142v2")
    assert [e.size for e in entries] == [0, 0]


@responses.activate
def test_unpaginated_listing_probes_first_page_only():
    names = [f"f{i:02}.txt" for i in range(DEFAULT_PAGE_LIMIT + 5)]
    _search([{**RECORD, "files_s": [], "fileAnnexes_s": [f"https://hal.science/hal-01479142/file/{n}" for n in names]}])
    for name in names:
        _size(name, "1")
    entries, total = _list("/hal-01479142v2")
    assert total == len(entries) == len(names)
    assert [e.size for e in entries] == [1] * DEFAULT_PAGE_LIMIT + [0] * 5
    assert len([c for c in responses.calls if c.request.method == "HEAD"]) == DEFAULT_PAGE_LIMIT


@responses.activate
def test_sizes_probed_only_for_visible_page():
    _search([RECORD])
    _size("main.pdf", "7")
    entries, total = _list("/hal-01479142v2", limit=1, offset=1)
    assert [(e.name, e.size) for e in entries] == [("main.pdf", 7)]
    assert total == 2
    assert [c.request.method for c in responses.calls] == ["GET", "HEAD"]


@responses.activate
def test_deposit_query_filters_filenames():
    _search([RECORD])
    _size("main.pdf", "7")
    entries, total = _list("/hal-01479142v2", query="MAIN")
    assert [e.name for e in entries] == ["main.pdf"]
    assert total == 1


@responses.activate
def test_realize_uses_version_pinned_url():
    _search([RECORD])
    responses.add(responses.GET, f"{FILE_URL}/main.pdf", body="pdf!")
    assert_realizes_as(_sources(), "gxfiles://hal/hal-01479142v2/main.pdf", "pdf!")


@responses.activate
def test_realize_rejects_file_not_in_deposit():
    _search([RECORD])
    with pytest.raises(ObjectNotFound):
        assert_realizes_as(_sources(), "gxfiles://hal/hal-01479142v2/x.txt", "")


@responses.activate
def test_stale_version_refused():
    _search([RECORD])
    with pytest.raises(MessageException, match="different deposit version"):
        _list("/hal-01479142v1")


@responses.activate
def test_ambiguous_attachments_refused():
    record = {**RECORD, "fileAnnexes_s": ["https://hal.inrae.fr/hal-01479142/file/main.pdf"]}
    _search([record])
    with pytest.raises(MessageException, match="ambiguous"):
        _list("/hal-01479142v2")


@responses.activate
@pytest.mark.parametrize(
    "status,error,match",
    [(401, MessageException, "embargo"), (403, MessageException, "embargo"), (404, ObjectNotFound, "not found")],
)
def test_realize_http_errors(status, error, match):
    _search([RECORD])
    responses.add(responses.GET, f"{FILE_URL}/main.pdf", status=status)
    with pytest.raises(error, match=match):
        assert_realizes_as(_sources(), "gxfiles://hal/hal-01479142v2/main.pdf", "")


@responses.activate
def test_realize_rejects_html_page():
    _search([RECORD])
    responses.add(responses.GET, f"{FILE_URL}/main.pdf", body="<html/>", content_type="text/html")
    with pytest.raises(MessageException, match="HTML page"):
        assert_realizes_as(_sources(), "gxfiles://hal/hal-01479142v2/main.pdf", "")


@responses.activate
def test_redirect_to_private_address_not_requested():
    _search([RECORD])
    responses.add(responses.GET, f"{FILE_URL}/main.pdf", status=302, headers={"Location": "http://169.254.169.254/x"})
    responses.add(responses.GET, "http://169.254.169.254/x", body="secret")
    with pytest.raises(Exception) as e:
        assert_realizes_as(_sources(), "gxfiles://hal/hal-01479142v2/main.pdf", "secret")
    assert "secret" not in str(e.value)
    assert [c.request.url for c in responses.calls][-1] == f"{FILE_URL}/main.pdf"


@responses.activate
def test_redirect_loop_capped():
    _search([RECORD])
    responses.add(responses.GET, f"{FILE_URL}/main.pdf", status=302, headers={"Location": f"{FILE_URL}/main.pdf"})
    with pytest.raises(MessageException, match="Too many redirects"):
        assert_realizes_as(_sources(), "gxfiles://hal/hal-01479142v2/main.pdf", "")
    assert len(responses.calls) == 7


def test_writable_rejected():
    with pytest.raises(ValueError, match="read-only"):
        configured_file_sources([{"type": "hal", "id": "hal", "writable": True}])


@pytest.mark.parametrize("path", ["/not-a-record", "/hal-01479142v0", "/hal-01479142v2/a/b"])
def test_invalid_path(path):
    with pytest.raises(ObjectNotFound):
        _list(path)


@responses.activate
def test_hal_subdomain_attachments_listed():
    record = {**RECORD, "files_s": [], "fileAnnexes_s": ["https://hal.archives-ouvertes.fr/hal-01479142/file/s.txt"]}
    _search([record])
    responses.add(responses.HEAD, "https://hal.archives-ouvertes.fr/hal-01479142v2/file/s.txt", status=500)
    entries, _ = _list("/hal-01479142v2")
    assert [e.name for e in entries] == ["s.txt"]
