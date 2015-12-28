""" Provides an abstraction for safely managing a single
toolbox configuration file in JSON format.
"""

import os
import hashlib
import json


CONCURRENT_WRITE_MESSAGE = "Managed toolbox configuration has been modified, cannot save."


class ConcurrentWriteException(Exception):

    def __init__(self):
        super(ConcurrentWriteException, self).__init__(
            CONCURRENT_WRITE_MESSAGE
        )

FORCE_WRITE = object()


class ManagedConfView(object):
    """ Adapt a ManagedConf object with a RESTful-like web pattern
    ready to be integrated by the Galaxy web framework or something
    lighter weight and standalone.
    """

    def __init__(self, managed_conf):
        self.managed_conf = managed_conf

    def get(self):
        hash, contents = self.managed_conf.read()
        return {"hash": hash, "contents": contents}

    def update(self, payload):
        if "hash" in payload and "contents" in payload:
            previous_hash = payload["hash"]
            contents = payload["contents"]
            self.managed_conf.update(contents, previous_hash)
        elif "actions" in payload:
            actions = payload["actions"]
            self.managed_conf.handle_actions(actions)


# TODO: Even more concurrency protection with file locks.
# TODO: Atomic actions that can be retried.
class ManagedConf(object):

    def __init__(self, path):
        self.path = path

    def read(self):
        contents = self._contents
        return (self._hash(contents), json.loads(contents))

    def update(self, as_dict, previous_hash=FORCE_WRITE):
        if previous_hash != FORCE_WRITE:
            contents = self._contents
            current_hash = self._hash(contents)
            if previous_hash != current_hash:
                raise ConcurrentWriteException()
        with open(self.path, "w") as f:
            json.dump(as_dict, f)

    def ensure_exists(self):
        if not os.path.exists(self.path):
            with open(self.path, "w") as f:
                f.write("{}")

    @property
    def _contents(self):
        with open(self.path, "r") as f:
            return f.read()

    def _hash(self, contents):
        m = hashlib.md5()
        m.update(contents)
        return m.hexdigest()

    def handle_actions(self, actions):
        """ Attempt to apply actions atomically.
        """
        self.ensure_exists()
        attempt_write = True
        while attempt_write:
            try:
                previous_hash, as_dict = self.read()
                for action in actions:
                    self._handle_action(as_dict, action)
                self.update(as_dict, previous_hash)
            except ConcurrentWriteException:
                continue
            attempt_write = False

    def _handle_action(self, as_dict, action_dict):
        action = action_dict.pop("action")
        assert action in [
            "add_item",
            "create_group",
            "disable",
            "create_section"
        ]
        method = getattr(self, "_%s" % action)
        method(as_dict, **action_dict)

    def _disable(self, as_dict, target):
        if "group" in target:
            group_dict = self._target_to_group(as_dict, target)
            group_dict["enabled"] = False
        else:
            raise self._unknown_target_exception(target)

    def _create_group(self, as_dict, id):
        groups = self._ensure_has_list(as_dict, "groups")
        groups.append({"id": id, "items": []})

    def _create_section(self, as_dict, id, name):
        items = self._ensure_has_items(as_dict)
        items.append({"type": "section", "name": name, "id": id, "items": []})

    def _add_item(self, as_dict, item, target=None):
        if target is None:
            items = self._ensure_has_items(as_dict)
            items.append(item)
        elif "group" in target:
            group_dict = self._target_to_group(as_dict, target)
            group_items = self._ensure_has_items(group_dict)
            group_items.append(item)
        elif "section" in target:
            section_dict = self._target_to_section(as_dict, target)
            section_items = self._ensure_has_items(section_dict)
            section_items.append(item)
        else:
            raise self._unknown_target_exception(target)

    def _unknown_target_exception(self, target):
        return Exception("Unknown target type [%s]." % target)

    def _target_to_section(self, as_dict, target):
        items = as_dict["items"]
        section_id = target["section"]
        section_dict = self._find_with_id(items, section_id)
        return section_dict

    def _target_to_group(self, as_dict, target):
        groups = as_dict["groups"]
        group = target["group"]
        group_dict = self._find_with_id(groups, group)
        return group_dict

    def _find_with_id(self, items, id):
        for item in items:
            if item["id"] == id:
                return item
        return None

    def _ensure_has_items(self, as_dict):
        return self._ensure_has_list(as_dict, "items")

    def _ensure_has_list(self, as_dict, key):
        if key not in as_dict:
            as_dict[key] = []
        return as_dict[key]
