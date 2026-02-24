import json

from .framework import (
    retry_assertion_during_transitions,
    retry_during_transitions,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
)


class TestWorkflowEditorInputs(SeleniumTestCase, RunsWorkflows):
    ensure_registered = True

    def _add_input_and_get_workflow_id(self, item_name):
        name = self.workflow_create_new()
        self.workflow_editor_add_input(item_name=item_name)
        workflow_id = self.current_url.split("id=")[1]
        return name, workflow_id

    @retry_assertion_during_transitions
    def _assert_save_button_enabled_and_click(self):
        save_button = self.components.workflow_editor.save_button
        save_button.wait_for_visible()
        assert not save_button.has_class("disabled"), "Save button should be enabled (has changes)"
        save_button.wait_for_and_click()

    @retry_assertion_during_transitions
    def _assert_save_button_disabled(self):
        self.components.workflow_editor.save_button.assert_disabled()

    def _save_and_download(self, workflow_id):
        self._assert_save_button_enabled_and_click()
        self._assert_save_button_disabled()
        workflow = self.workflow_populator.download_workflow(workflow_id)
        return workflow

    def _get_tool_state(self, workflow):
        return json.loads(workflow["steps"]["0"]["tool_state"])

    def _save_and_verify_source(self, workflow_id, expected_tool_state):
        workflow = self._save_and_download(workflow_id)
        tool_state = self._get_tool_state(workflow)
        for key, expected_value in expected_tool_state.items():
            actual_value = tool_state.get(key)
            assert (
                actual_value == expected_value
            ), f"tool_state['{key}'] expected {expected_value!r} but got {actual_value!r}"
        return tool_state

    @retry_during_transitions
    def _leave_and_reopen(self, workflow_name, node_label):
        self.workflow_index_open_with_name(workflow_name)
        editor = self.components.workflow_editor
        editor.canvas_body.wait_for_visible()
        node = editor.node._(label=node_label)
        node.title.wait_for_and_click()
        editor.node_inspector.wait_for_visible()

    def _fill_text_field(self, component, value):
        """Set field value atomically via Playwright fill() — single change event.

        Avoids character-by-character typing that races with build_module form rebuilds.
        """
        elem = component.wait_for_visible()
        elem._element.fill(value)

    def _wait_for_build_module(self, node_label):
        """Wait for all build_module round-trips to settle by observing the node loading spinner.

        Typing into FormDisplay-backed fields triggers build_module on every keystroke,
        so we loop until no new spinner appears after a brief quiet period.
        """
        node = self.components.workflow_editor.node._(label=node_label)
        max_cycles = 10
        for _ in range(max_cycles):
            try:
                if not node.loading.is_absent:
                    node.loading.wait_for_absent_or_hidden()
                    continue  # spinner cleared — check if another starts
            except Exception:
                # Element detached mid-check — spinner appeared and disappeared fast
                continue
            # No spinner visible — wait briefly and check once more
            self.sleep_for(self.wait_types.UX_RENDER)
            try:
                if not node.loading.is_absent:
                    node.loading.wait_for_absent_or_hidden()
                    continue  # another cycle started, keep looping
            except Exception:
                continue
            break  # no spinner after quiet period — settled

    def _click_toggle(self, component, node_label):
        component.wait_for_and_click()
        self._wait_for_build_module(node_label)

    # Multiselect search matches by label, not value — map values to labels
    PARAMETER_TYPE_LABELS = {
        "text": "Text",
        "integer": "Integer",
        "float": "Float",
        "boolean": "Boolean",
        "color": "Color",
        "directory_uri": "Directory",
    }
    RESTRICTIONS_HOW_LABELS = {
        "none": "not specify",
        "onConnections": "based on connections",
        "staticRestrictions": "all possible",
        "staticSuggestions": "suggested",
    }

    def _select_parameter_type(self, param_type, node_label):
        """Switch the parameter_type conditional select."""
        form = self.components.workflow_editor.parameter_input_form
        label = self.PARAMETER_TYPE_LABELS[param_type]
        self.select_set_value(form.parameter_type, label)
        self._wait_for_build_module(node_label)

    def _select_restrictions_how(self, how_value, node_label):
        """Switch the restrictions conditional select."""
        form = self.components.workflow_editor.parameter_input_form
        label = self.RESTRICTIONS_HOW_LABELS[how_value]
        self.select_set_value(form.restrictions_how, label)
        self._wait_for_build_module(node_label)

    @selenium_test
    def test_data_input_parameters(self):
        editor = self.components.workflow_editor
        form = editor.data_input_form
        name, workflow_id = self._add_input_and_get_workflow_id("data_input")
        node_label = "Input dataset"

        # Iteration 1: defaults
        self._save_and_verify_source(
            workflow_id,
            {
                "optional": False,
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 2: optional=true, format=fastq
        self._click_toggle(form.optional, node_label)
        self._fill_text_field(form.format, "fastq")
        self._wait_for_build_module(node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "optional": True,
                "format": ["fastq"],
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 3: optional=true, format=bed,bam, tag=filter_tag
        self._fill_text_field(form.format, "bed,bam")
        self._wait_for_build_module(node_label)
        self._fill_text_field(form.tag, "filter_tag")
        self._wait_for_build_module(node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "optional": True,
                "format": ["bed", "bam"],
                "tag": "filter_tag",
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 4: optional=false, format=empty, tag=another_tag
        self._click_toggle(form.optional, node_label)  # toggle off
        self._fill_text_field(form.format, "")
        self._wait_for_build_module(node_label)
        self._fill_text_field(form.tag, "another_tag")
        self._wait_for_build_module(node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "optional": False,
                "tag": "another_tag",
            },
        )

    @selenium_test
    def test_data_collection_input_parameters(self):
        editor = self.components.workflow_editor
        form = editor.collection_input_form
        name, workflow_id = self._add_input_and_get_workflow_id("data_collection_input")
        node_label = "Input dataset collection"

        # Iteration 1: defaults (list, not optional, no format, no tag)
        self._save_and_verify_source(
            workflow_id,
            {
                "collection_type": "list",
                "optional": False,
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 2: paired, optional=true, format=fastq
        self._fill_text_field(form.collection_type, "paired")
        self._wait_for_build_module(node_label)
        self._click_toggle(form.optional, node_label)
        self.select_set_value(form.format, "fastq")
        self._save_and_verify_source(
            workflow_id,
            {
                "collection_type": "paired",
                "optional": True,
                "format": ["fastq"],
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 3: list:paired, optional=false, format=bam,bed, tag=filter_tag
        self._fill_text_field(form.collection_type, "list:paired")
        self._wait_for_build_module(node_label)
        self._click_toggle(form.optional, node_label)  # toggle off
        # Clear old format selection and add new ones
        self.select_set_value(form.format, "bam", multiple=True, clear_value=True)
        self.select_set_value(form.format, "bed", multiple=True)
        self._fill_text_field(form.tag, "filter_tag")
        self._wait_for_build_module(node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "collection_type": "list:paired",
                "optional": False,
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 4: list, optional=true, no format, tag=another_tag
        self._fill_text_field(form.collection_type, "list")
        self._wait_for_build_module(node_label)
        self._click_toggle(form.optional, node_label)  # toggle on
        self._fill_text_field(form.tag, "another_tag")
        self._wait_for_build_module(node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "collection_type": "list",
                "optional": True,
                "tag": "another_tag",
            },
        )

    @selenium_test
    def test_parameter_input_parameters(self):
        editor = self.components.workflow_editor
        form = editor.parameter_input_form
        name, workflow_id = self._add_input_and_get_workflow_id("parameter_input")
        node_label = "Input parameter"

        # Iteration 1: text, defaults (restrictions=none), not optional
        self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "text",
                "optional": False,
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 2: text, restrictions=staticRestrictions, values="a,b,c"
        self._select_restrictions_how("staticRestrictions", node_label)
        self._fill_text_field(form.restrictions_value, "a,b,c")
        self._wait_for_build_module(node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "text",
                "optional": False,
            },
        )
        assert (
            "restrictions" in tool_state
        ), f"Expected 'restrictions' in tool_state, got keys: {list(tool_state.keys())}"
        assert tool_state["restrictions"] == ["a", "b", "c"]
        self._leave_and_reopen(name, node_label)

        # Iteration 3: text, restrictions=onConnections
        self._select_restrictions_how("onConnections", node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "text",
                "optional": False,
            },
        )
        assert tool_state.get("restrictOnConnections") is True
        self._leave_and_reopen(name, node_label)

        # Iteration 4: text, restrictions=staticSuggestions, values="x,y,z"
        self._select_restrictions_how("staticSuggestions", node_label)
        self._fill_text_field(form.suggestions_value, "x,y,z")
        self._wait_for_build_module(node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "text",
                "optional": False,
            },
        )
        assert "suggestions" in tool_state, f"Expected 'suggestions' in tool_state, got keys: {list(tool_state.keys())}"
        assert tool_state["suggestions"] == ["x", "y", "z"]
        self._leave_and_reopen(name, node_label)

        # Iteration 5: text, multiple=true, optional=true, default="hello"
        self._select_restrictions_how("none", node_label)
        self._click_toggle(form.multiple, node_label)
        self._click_toggle(form.optional, node_label)  # toggle optional on
        self._click_toggle(form.specify_default, node_label)  # enable default
        self._fill_text_field(form.default_value, "hello")
        self._wait_for_build_module(node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "text",
                "optional": True,
                "multiple": True,
                "default": "hello",
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 6: integer, min=0, max=100, not optional
        self._select_parameter_type("integer", node_label)
        self._fill_text_field(form.min, "0")
        self._wait_for_build_module(node_label)
        self._fill_text_field(form.max, "100")
        self._wait_for_build_module(node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "integer",
                "optional": False,
            },
        )
        validators = tool_state.get("validators", [])
        in_range = [v for v in validators if v.get("type") == "in_range"]
        assert len(in_range) == 1, f"Expected 1 in_range validator, got {in_range}"
        assert in_range[0]["min"] == 0 or in_range[0]["min"] == "0"
        assert in_range[0]["max"] == 100 or in_range[0]["max"] == "100"
        self._leave_and_reopen(name, node_label)

        # Iteration 7: integer, no min/max, optional=true, default=42
        self._fill_text_field(form.min, "")
        self._wait_for_build_module(node_label)
        self._fill_text_field(form.max, "")
        self._wait_for_build_module(node_label)
        self._click_toggle(form.optional, node_label)
        self._click_toggle(form.specify_default, node_label)
        self._fill_text_field(form.default_value, "42")
        self._wait_for_build_module(node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "integer",
                "optional": True,
            },
        )
        assert tool_state.get("default") == 42 or tool_state.get("default") == "42"
        self._leave_and_reopen(name, node_label)

        # Iteration 8: float, min=0.0, max=1.0, not optional
        self._select_parameter_type("float", node_label)
        self._fill_text_field(form.min, "0.0")
        self._wait_for_build_module(node_label)
        self._fill_text_field(form.max, "1.0")
        self._wait_for_build_module(node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "float",
                "optional": False,
            },
        )
        validators = tool_state.get("validators", [])
        in_range = [v for v in validators if v.get("type") == "in_range"]
        assert len(in_range) == 1, f"Expected 1 in_range validator, got {in_range}"
        self._leave_and_reopen(name, node_label)

        # Iteration 9: boolean, optional, default=true
        self._select_parameter_type("boolean", node_label)
        self._click_toggle(form.optional, node_label)
        self._click_toggle(form.specify_default, node_label)
        # Boolean default is a checkbox/switch, click to set to true
        self._click_toggle(form.default_boolean, node_label)
        tool_state = self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "boolean",
                "optional": True,
            },
        )
        assert tool_state.get("default") is True or tool_state.get("default") == "true"
        self._leave_and_reopen(name, node_label)

        # Iteration 10: color, not optional
        self._select_parameter_type("color", node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "color",
                "optional": False,
            },
        )
        self._leave_and_reopen(name, node_label)

        # Iteration 11: directory_uri, not optional
        self._select_parameter_type("directory_uri", node_label)
        self._save_and_verify_source(
            workflow_id,
            {
                "parameter_type": "directory_uri",
                "optional": False,
            },
        )
