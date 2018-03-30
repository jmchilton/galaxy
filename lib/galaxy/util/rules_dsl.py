

class AddColumnMetadataRuleDefinition(object):
    rule_type = "add_column_metadata"

    def apply(self, rule, data, sources):
        rule_value = rule["value"]
        identifier_index = int(rule_value[len("identifier"):])

        new_rows = []
        for index, row in enumerate(data):
            new_rows.append(row + [sources[index]["identifiers"][identifier_index]])

        return new_rows, sources


class RuleSet(object):

    def __init__(self, rule_set_as_dict):
        self.raw_rules = rule_set_as_dict["rules"]
        self.raw_mapping = rule_set_as_dict["mapping"]

    @property
    def rules(self):
        return self.raw_rules

    def _rules_with_definitions(self):
        for rule in self.raw_rules:
            yield (rule, RULES_DEFINITIONS[rule["type"]])

    def apply(self, data, sources):
        for rule, rule_definition in self._rules_with_definitions():
            data, sources = rule_definition.apply(rule, data, sources)

        return data, sources

    @property
    def mapping_as_dict(self):
        as_dict = {}
        for mapping in self.raw_mapping:
            as_dict[mapping["type"]] = mapping

        return as_dict

    # Rest of this is generic, things here are Galaxy collection specific, think about about
    # subclass of RuleSet for collection creation.
    @property
    def identifier_columns(self):
        mapping_as_dict = self.mapping_as_dict
        identifier_columns = []
        if "list_identifiers" in mapping_as_dict:
            identifier_columns.extend(mapping_as_dict["list_identifiers"]["columns"])
        if "paired_identifier" in mapping_as_dict:
            identifier_columns.append(mapping_as_dict["paired_identifier"]["columns"][0])

        return identifier_columns

    @property
    def collection_type(self):
        mapping_as_dict = self.mapping_as_dict
        list_columns = mapping_as_dict.get("list_identifiers", {"columns": []})["columns"]
        collection_type = ":".join(map(lambda c: "list", list_columns))
        if "paired_identifier" in mapping_as_dict:
            if collection_type:
                collection_type += ":paired"
            else:
                collection_type = "paired"
        return collection_type


RULES_DEFINITIONS = {}
for rule_class in [AddColumnMetadataRuleDefinition]:
    RULES_DEFINITIONS[rule_class.rule_type] = rule_class()
