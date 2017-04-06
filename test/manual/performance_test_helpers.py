import random

from argparse import ArgumentParser

from bioblend import galaxy


def init_arg_parser(description):
    arg_parser = ArgumentParser(description=description)
    arg_parser.add_argument("--api_key", default="testmasterapikey")
    arg_parser.add_argument("--host", default="http://localhost:8080/")
    return arg_parser


def gi_from_args(args, user_pattern="perftest-user-%d"):
    gi = galaxy.GalaxyInstance(args.host, key=args.api_key)
    name = user_pattern % random.randint(0, 1000000)

    user = gi.users.create_local_user(name, "%s@galaxytesting.dev" % name, "pass123")
    user_id = user["id"]
    api_key = gi.users.create_user_apikey(user_id)
    user_gi = galaxy.GalaxyInstance(args.host, api_key)
    return user_gi
