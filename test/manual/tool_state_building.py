#!/usr/bin/env python
"""
"""
from __future__ import print_function

import functools
import os
import random
import sys

from argparse import ArgumentParser
from threading import Thread

from bioblend import galaxy
from six.moves import range

galaxy_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
sys.path[1:1] = [ os.path.join( galaxy_root, "lib" ), os.path.join( galaxy_root, "test" ) ]

from base.populators import (
    GiDatasetCollectionPopulator,
    GiDatasetPopulator,
    GiWorkflowPopulator,
)


LONG_TIMEOUT = 1000000000
DESCRIPTION = "Script to exercise tool state building API."


def main(argv=None):
    """Entry point for workflow driving."""
    arg_parser = ArgumentParser(description=DESCRIPTION)
    arg_parser.add_argument("--api_key", default="testmasterapikey")
    arg_parser.add_argument("--host", default="http://localhost:8080/")

    arg_parser.add_argument("--thread_count", type=int, default=1)
    arg_parser.add_argument("--collection_type", type=str, default="list")
    arg_parser.add_argument("--fresh_history", default=False, action="store_true")
    arg_parser.add_argument("--collection_size", type=int, default=100)
    arg_parser.add_argument("--collection_count", type=int, default=1)

    args = arg_parser.parse_args(argv)

    gi = _gi(args)

    target = functools.partial(_run, args, gi)
    threads = []
    for i in range(args.thread_count):
        t = Thread(target=target)
        t.daemon = True
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


def _run(args, gi):
    dataset_populator = GiDatasetPopulator(gi)
    dataset_collection_populator = GiDatasetCollectionPopulator(gi)

    history_id = dataset_populator.new_history()
    hide_source_items = args.fresh_history

    for i in range(args.collection_count):
        collection_type = args.collection_type
        if collection_type == "list":
            response = dataset_populator.run_tool(
                "create_input_collection",
                inputs=dict(collection_size=args.collection_size),
                history_id=history_id
            )
            job = response["jobs"][0]
            dataset_populator.wait_for_job(job["id"], timeout=50000)
            details = dataset_populator.get_history_collection_details(history_id, hid=1)
        elif collection_type == "list:paired":
            hdca = dataset_collection_populator.create_list_of_pairs_in_history( history_id, num_pairs=args.collection_size, hide_source_items=hide_source_items )

        # if args.fresh_history:
        #     create_data = dict(
        #         source='hdca',
        #         content=hdca[ "id" ],
        #     )
        #     dataset_populator._post( "histories/%s/contents" % history_id, create_data )

    for i in range(20):
        response = gi.make_get_request(gi.url + "/tools/cat/build?history_id=%s" % history_id )
        assert response.status_code == 200


def _gi(args):
    gi = galaxy.GalaxyInstance(args.host, key=args.api_key)
    name = "tbtest-user-%d" % random.randint(0, 1000000)

    user = gi.users.create_local_user(name, "%s@galaxytesting.dev" % name, "pass123")
    user_id = user["id"]
    api_key = gi.users.create_user_apikey(user_id)
    user_gi = galaxy.GalaxyInstance(args.host, api_key)
    return user_gi


if __name__ == "__main__":
    main()
