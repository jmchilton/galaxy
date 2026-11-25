"""Recording what templates read from raw objects while they render."""

import copy

from galaxy import model
from galaxy.security.object_wrapper import wrap_with_safe_string
from galaxy.security.render_recording import (
    MODEL,
    Read,
    recorded_view,
    recording,
    UNSANITIZED,
    USER,
)
from galaxy.tools.wrappers import (
    DatasetFilenameWrapper,
    RawObjectWrapper,
)
from galaxy.util.template import fill_template


class History:
    def __init__(self, name):
        self.name = name


class Tag:
    def __init__(self, value):
        self.user_value = value


class Dataset:
    def __init__(self):
        self.history = History("a';id;'")
        self.tags = [Tag("t1"), Tag("t2")]
        self.count = 3

    def label(self, prefix):
        return f"{prefix}{self.history.name}"


def render(template, **context):
    return fill_template(template, context=context, python_template_version="3")


def test_a_view_records_every_string_it_hands_out_with_its_path():
    with recording() as recorded:
        view = recorded_view(Dataset(), MODEL)
        text = render("$d.history.name #for $t in $d.tags#$t.user_value #end for#$d.count $d.label('x')", d=view)
    assert text == "a';id;' t1 t2 3 xa';id;'"
    assert recorded.reads == [
        Read(MODEL, ("history", "name"), "a';id;'"),
        Read(MODEL, ("tags", "[]", "user_value"), "t1"),
        Read(MODEL, ("tags", "[]", "user_value"), "t2"),
        Read(MODEL, ("label", "()"), "xa';id;'"),
    ]


def test_cheetah_looks_up_attributes_of_a_view_that_is_not_subscriptable():
    with recording() as recorded:
        text = render("#if $d.history.name.startswith('a')#yes#end if#", d=recorded_view(Dataset(), MODEL))
    assert text == "yes"
    assert [read.path for read in recorded.reads] == [("history", "name")]


def test_outside_a_recording_the_object_is_handed_out_as_it_is():
    dataset = Dataset()
    assert recorded_view(dataset, MODEL) is dataset


def test_the_unsanitized_value_of_a_sanitized_object_is_recorded():
    wrapped = wrap_with_safe_string(Dataset())
    assert str(wrapped.history.name) == "a__sq__XidX__sq__"
    assert isinstance(wrapped.unsanitized, Dataset)
    with recording() as recorded:
        assert render("$d.unsanitized.history.name", d=wrapped) == "a';id;'"
    assert recorded.reads == [Read(UNSANITIZED, ("history", "name"), "a';id;'")]


def test_a_sanitized_object_still_copies():
    # Through the reduce functions registered with copyreg, which read the raw value.
    copied = copy.deepcopy(wrap_with_safe_string(Dataset()))
    assert str(copied.history.name) == "a__sq__XidX__sq__"
    assert copied.unsanitized.history.name == "a';id;'"


def test_the_dataset_model_of_a_dataset_wrapper_is_recorded():
    hda = model.HistoryDatasetAssociation(name="a'b", extension="txt")
    wrapper = DatasetFilenameWrapper(hda)
    assert wrapper.unsanitized is hda
    with recording() as recorded:
        assert render("$d.unsanitized.name", d=wrapper) == "a'b"
    assert recorded.reads == [Read(MODEL, ("name",), "a'b")]


def test_the_user_object_is_recorded_unless_it_is_sanitized():
    user = model.User(email="u@example.org", username="u'")
    with recording() as recorded:
        assert render("$u.username", u=RawObjectWrapper(user, records=True)) == "u'"
        assert render("$u.username", u=RawObjectWrapper(wrap_with_safe_string(user), records=True)) == "u__sq__"
    assert recorded.reads == [Read(USER, ("username",), "u'")]
