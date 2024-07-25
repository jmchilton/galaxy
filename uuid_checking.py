"""
Manual testing for database migration making uuid's unique in the database.

Start with database at eee9229a9765
% python uuid_checking.py -c config/galaxy.yml galaxy setup_fixtures
% sh manage_db.sh upgrade
% python uuid_checking.py -c config/galaxy.yml galaxy check_upgrade
% sh manage_db.sh downgrade eee9229a9765
% python uuid_checking.py -c config/galaxy.yml galaxy check_downgrade
"""

import sys

from scripts.db_shell import *
from sqlalchemy.sql import text

from galaxy.model.base import transaction

uuid1 = "035ca8c0dc314b7abb22bb3a89d65d46"
uuid2 = "035ca8c0dc314b7abb22bb3a89d65d47"
uuid3 = "035ca8c0dc314b7abb22bb3a89d65d48"
uuid4 = "035ca8c0dc314b7abb22bb3a89d65d49"

uuid_control_1 = "025ca8c0dc314b7abb22bb3a89d65d46"
uuid_control_2 = "025ca8c0dc314b7abb22bb3a89d65d47"

uuid_purged_1 = "035ca8c0dc314b7abb22bb3a89d65d41"
uuid_purged_2 = "035ca8c0dc314b7abb22bb3a89d65d42"
uuid_purged_control_1 = "025ca8c0dc314b7abb22bb3a89d65d41"
uuid_purged_control_2 = "025ca8c0dc314b7abb22bb3a89d65d42"

test_uuids = [
    uuid1,
    uuid2,
    uuid3,
    uuid4,
    uuid_control_1,
    uuid_control_2,
    uuid_purged_1,
    uuid_purged_2,
    uuid_purged_control_1,
    uuid_purged_control_2,
]


def add_dataset(name, uuid, purged=False):
    dataset = Dataset()
    dataset.uuid = uuid
    hda = HistoryDatasetAssociation()
    hda.name = name
    hda.dataset = dataset
    sa_session.add(dataset)
    sa_session.add(hda)
    if purged:
        dataset.purged = True
    return hda


def setup_fixtures():
    for uuid in test_uuids:
        sa_session.execute(
            text(
                f"delete from history_dataset_association where id in (select hda.id from history_dataset_association as hda join dataset as d on hda.dataset_id = d.id where d.uuid = '{uuid}')"
            )
        )
        sa_session.execute(text(f"delete from dataset where uuid = '{uuid}'"))

    with transaction(sa_session):
        add_dataset("dataset1", uuid1)
        add_dataset("dataset2", uuid2)
        add_dataset("dataset3", uuid3)
        add_dataset("dataset4", uuid4)

        add_dataset("dataset_purged_1", uuid_purged_1, purged=True)
        add_dataset("dataset_purged_1 duplicate 1", uuid_purged_1, purged=True)
        add_dataset("dataset_purged_1 duplicate 2", uuid_purged_1, purged=True)
        add_dataset("dataset_purged_2", uuid_purged_2, purged=True)
        add_dataset("dataset_purged_2 duplicate", uuid_purged_2, purged=True)

        add_dataset("dataset control 1", uuid_control_1)
        add_dataset("dataset control 2", uuid_control_2)

        add_dataset("dataset control purged 1", uuid_purged_control_1)
        add_dataset("dataset control purged 2", uuid_purged_control_2)

        add_dataset("dataset4-2 copy", uuid4)
        add_dataset("dataset1 copy", uuid1)
        add_dataset("dataset2 copy", uuid2)
        add_dataset("dataset3 copy", uuid3)
        add_dataset("dataset4 copy", uuid4)

        sa_session.commit()

    print(sa_session.execute(text(f"select * from dataset where uuid = '{uuid1}'")).all())
    count = sa_session.execute(text(f"select count(*) from dataset where uuid = '{uuid1}'")).all()[0][0]
    assert count == 2, count

    print(sa_session.execute(text(f"select count(*) from dataset")).all())

    names = sa_session.execute(
        text(
            f"select hda.name, hda.id, hda.dataset_id, dataset.uuid from history_dataset_association as hda join dataset on dataset.id = hda.dataset_id where dataset.uuid = '{uuid1}'"
        )
    ).all()
    assert len(names) == 2, names


def check_upgrade():
    _check_controls()
    _check_hdas_still_point_at_relevant_uuids()

    print(sa_session.execute(text(f"select * from dataset where uuid = '{uuid1}'")).all())
    count = sa_session.execute(text(f"select count(*) from dataset where uuid = '{uuid1}'")).all()[0][0]
    assert count == 1, count

    # still two hdas mapped to this...
    names = sa_session.execute(
        text(
            f"select name from history_dataset_association as hda inner join dataset on dataset.id = hda.dataset_id where uuid = '{uuid1}'"
        )
    ).all()
    assert len(names) == 2

    # The unique constraint handles this but lets just add it.
    for uuid in [uuid1, uuid2, uuid3, uuid4]:
        assert 1 == _get_count(text(f"select count(*) from dataset as d where d.uuid = '{uuid}'"))


def check_downgrade():
    _check_controls()
    _check_hdas_still_point_at_relevant_uuids()

    # check that datasets are re-duplicated
    for uuid in [uuid1, uuid2, uuid3]:
        assert 2 == _get_count(text(f"select count(*) from dataset as d where d.uuid = '{uuid}'"))

    # this one had 3 duplicates
    assert 3 == _get_count(text(f"select count(*) from dataset as d where d.uuid = '{uuid4}'"))


def _check_hdas_still_point_at_relevant_uuids():
    for uuid in [uuid1, uuid2, uuid3]:
        # still two hdas mapped to this HDA
        names = sa_session.execute(
            text(
                f"select * from history_dataset_association as hda inner join dataset on dataset.id = hda.dataset_id where uuid = '{uuid}'"
            )
        ).all()
        assert len(names) == 2

    # uuid4 had three copies...
    names = sa_session.execute(
        text(
            f"select * from history_dataset_association as hda inner join dataset on dataset.id = hda.dataset_id where uuid = '{uuid4}'"
        )
    ).all()
    assert len(names) == 3


def _check_controls():
    # datsets that shouldn't be touched...
    assert _uuid_for_dataset_name("dataset control 1") == uuid_control_1
    assert _uuid_for_dataset_name("dataset control 2") == uuid_control_2
    assert _uuid_for_dataset_name("dataset control purged 1") == uuid_purged_control_1
    assert _uuid_for_dataset_name("dataset control purged 2") == uuid_purged_control_2


def _uuid_for_dataset_name(name):
    list_res = _uuids_for_dataset_name(name)
    assert len(list_res) == 1
    return list_res[0]


def _uuids_for_dataset_name(name):
    return list(
        map(
            lambda x: x[0],
            sa_session.execute(
                text(
                    f"select dataset.uuid from history_dataset_association as hda inner join dataset on dataset.id = hda.dataset_id where name = '{name}'"
                )
            ).all(),
        )
    )


def _get_count(query):
    return sa_session.execute(query).all()[0][0]


def main():
    if sys.argv[2] == "setup_fixtures":
        setup_fixtures()
    elif sys.argv[2] == "check_upgrade":
        check_upgrade()
    elif sys.argv[2] == "check_downgrade":
        check_downgrade()


if __name__ == "__main__":
    main()
