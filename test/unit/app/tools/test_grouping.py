import pytest

from galaxy.datatypes.registry import Registry
from galaxy.exceptions import RequestParameterInvalidException
from galaxy.tools.parameters.basic import SelectToolParameter
from galaxy.tools.parameters.grouping import (
    Conditional,
    ConditionalWhen,
    UploadDataset,
)
from galaxy.util import XML
from galaxy.util.bunch import Bunch


def test_force_composite_preserves_distinct_member_names(tmp_path):
    registry = Registry()
    registry.load_datatypes()
    trans = Bunch(app=Bunch(datatypes_registry=registry))
    upload = UploadDataset(name="files")
    names = ["sample-1.txt", "sample_1.txt", "sample 1.txt"]
    files = []
    for name in ["primary.txt", *names]:
        path = tmp_path / name
        path.write_text(f"Content for {name}\n")
        files.append(
            {
                "NAME": name,
                "file_data": {"local_filename": str(path), "filename": name},
                "file_type": "txt",
                "dbkey": "?",
                "url_paste": None,
                "ftp_files": None,
            }
        )
    context = {"files": files, "file_type": "txt", "file_count": len(files), "force_composite": True}

    (dataset,) = upload.get_uploaded_datasets(trans, context)

    assert set(dataset.composite_files) == set(names)
    for name in names:
        assert dataset.composite_files[name]["path"] == str(tmp_path / name)


def _arity_conditional():
    """A conditional mirroring dada2's batch_cond: same parameter name in both
    cases, differing arity, single-dataset case last."""
    cond = Conditional("batch_cond")
    cond.test_param = SelectToolParameter(
        None,
        XML(
            '<param name="batch_select" type="select">'
            '<option value="no">no</option><option value="yes">yes</option></param>'
        ),
    )
    for value, multiple in (("no", True), ("yes", False)):
        when = ConditionalWhen()
        when.value = value
        when.inputs = {"reads": Bunch(name="reads", multiple=multiple)}
        cond.cases.append(when)
    return cond


def test_get_current_case_inputs_resolves_valid_case():
    cond = _arity_conditional()
    assert cond.get_current_case_inputs({"batch_select": "no", "__current_case__": 0})["reads"].multiple is True
    assert cond.get_current_case_inputs({"batch_select": "yes", "__current_case__": 1})["reads"].multiple is False


@pytest.mark.parametrize("current_case", [-1, 2, None, "0"])
def test_get_current_case_inputs_rejects_unresolvable_case(current_case):
    """-1 is what get_current_case() returns for a value matching no <when>,
    and visit_input_values stores it. Indexing cases[-1] silently selected the
    last case, handing a multiple="true" value to a single-dataset parameter
    (galaxyproject/galaxy#23521)."""
    cond = _arity_conditional()
    values = {"batch_select": "Pooling", "reads": [], "__current_case__": current_case}
    with pytest.raises(RequestParameterInvalidException) as exc_info:
        cond.get_current_case_inputs(values)
    message = str(exc_info.value)
    assert "batch_cond" in message
    assert "batch_select" in message
    assert "Pooling" in message
    assert "['no', 'yes']" in message


def test_get_current_case_inputs_rejects_missing_case():
    cond = _arity_conditional()
    with pytest.raises(RequestParameterInvalidException):
        cond.get_current_case_inputs({"batch_select": "no"})
