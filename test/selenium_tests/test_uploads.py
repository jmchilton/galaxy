from .framework import (
    selenium_test,
    SeleniumTestCase,
    UsesHistoryItemAssertions,
)


class UploadsTestCase(SeleniumTestCase, UsesHistoryItemAssertions):

    @selenium_test
    def test_upload_simplest(self):
        self.perform_upload(self.get_filename("1.sam"))

        self.history_panel_wait_for_hid_ok(1)
        history_contents = self.current_history_contents()
        history_count = len(history_contents)
        assert history_count == 1, "Incorrect number of items in history - expected 1, found %d" % history_count

        hda = history_contents[0]
        assert hda["name"] == '1.sam', hda
        assert hda["extension"] == "sam", hda

        self.history_panel_click_item_title(hid=1, wait=True)
        self.assert_item_dbkey_displayed_as(1, "?")

    @selenium_test
    def test_upload_specify_ext(self):
        self.perform_upload(self.get_filename("1.sam"), ext="txt")
        self.history_panel_wait_for_hid_ok(1)
        history_contents = self.current_history_contents()
        hda = history_contents[0]
        assert hda["name"] == '1.sam'
        assert hda["extension"] == "txt", hda

    @selenium_test
    def test_upload_specify_genome(self):
        self.perform_upload(self.get_filename("1.sam"), genome="hg18")
        self.history_panel_wait_for_hid_ok(1)

        self.history_panel_click_item_title(hid=1, wait=True)
        self.assert_item_dbkey_displayed_as(1, "hg18")

    @selenium_test
    def test_upload_specify_ext_all(self):
        self.perform_upload(self.get_filename("1.sam"), ext_all="txt")
        self.history_panel_wait_for_hid_ok(1)
        history_contents = self.current_history_contents()
        hda = history_contents[0]
        assert hda["name"] == '1.sam'
        assert hda["extension"] == "txt", hda

    @selenium_test
    def test_upload_specify_genome_all(self):
        self.perform_upload(self.get_filename("1.sam"), genome_all="hg18")
        self.history_panel_wait_for_hid_ok(1)

        self.history_panel_click_item_title(hid=1, wait=True)
        self.assert_item_dbkey_displayed_as(1, "hg18")

    @selenium_test
    def test_upload_list(self):
        self.upload_list([self.get_filename("1.tabular")], name="Test List")
        self.history_panel_wait_for_hid_ok(2)
        # Make sure modals disappeared - both List creator (TODO: upload).
        self.wait_for_selector_absent_or_hidden(".collection-creator")

        self.assert_item_name(2, "Test List")

        # Make sure source item is hidden when the collection is created.
        self.history_panel_wait_for_hid_hidden(1)

    @selenium_test
    def test_upload_pair(self):
        self.upload_list([self.get_filename("1.tabular"), self.get_filename("2.tabular")], name="Test Pair")
        self.history_panel_wait_for_hid_ok(3)
        # Make sure modals disappeared - both collection creator (TODO: upload).
        self.wait_for_selector_absent_or_hidden(".collection-creator")

        self.assert_item_name(3, "Test Pair")

        # Make sure source items are hidden when the collection is created.
        self.history_panel_wait_for_hid_hidden(1)
        self.history_panel_wait_for_hid_hidden(2)

    @selenium_test
    def test_upload_pair_specify_extension(self):
        self.upload_list([self.get_filename("1.tabular"), self.get_filename("2.tabular")], name="Test Pair", ext="txt", hide_source_items=False)
        self.history_panel_wait_for_hid_ok(3)
        self.history_panel_wait_for_hid_ok(1)

        history_contents = self.current_history_contents()
        hda = history_contents[0]
        assert hda["name"] == '1.tabular'
        assert hda["extension"] == "txt", hda

    @selenium_test
    def test_upload_paired_list(self):
        self.upload_paired_list([self.get_filename("1.tabular"), self.get_filename("2.tabular")], name="Test Paired List")
        self.history_panel_wait_for_hid_ok(3)
        # Make sure modals disappeared - both collection creator (TODO: upload).
        self.wait_for_selector_absent_or_hidden(".collection-creator")
        self.assert_item_name(3, "Test Paired List")

        # Make sure source items are hidden when the collection is created.
        self.history_panel_wait_for_hid_hidden(1)
        self.history_panel_wait_for_hid_hidden(2)

    @selenium_test
    def test_datasets_via_rules_example_1(self):
        # Test case generated for:
        #   https://www.ebi.ac.uk/ena/data/view/PRJDA60709
        self.home()
        self.upload_start_click()
        self.upload_tab_click("rule-based")
        self.screenshot("rules_example_1_1_rules_landing")
        self.components.upload.rule_source_content.wait_for_and_send_keys("""study_accession sample_accession    experiment_accession    fastq_ftp
PRJDA60709  SAMD00016379    DRX000475   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000770/DRR000770.fastq.gz
PRJDA60709  SAMD00016383    DRX000476   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000771/DRR000771.fastq.gz
PRJDA60709  SAMD00016380    DRX000477   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000772/DRR000772.fastq.gz
PRJDA60709  SAMD00016378    DRX000478   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000773/DRR000773.fastq.gz
PRJDA60709  SAMD00016381    DRX000479   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000774/DRR000774.fastq.gz
PRJDA60709  SAMD00016382    DRX000480   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000775/DRR000775.fastq.gz""")
        self.screenshot("rules_example_1_2_paste")
        self.upload_build(tab="rule-based")
        rule_builder = self.components.rule_builder
        rule_builder._.wait_for_and_click()
        self.screenshot("rules_example_1_3_initial_rules")
        rule_builder.menu_button_filter.wait_for_and_click()
        self.screenshot("rule_builder_filters")
        rule_builder.menu_item_rule_type(rule_type="add-filter-count").wait_for_and_click()
        filter_editor = rule_builder.rule_editor(rule_type="add-filter-count")
        filter_editor_element = filter_editor.wait_for_visible()
        self.screenshot("rules_example_1_4_filter_header")
        filter_input = filter_editor_element.find_element_by_css_selector("input[type='number']")
        filter_input.clear()
        filter_input.send_keys("1")
        rule_builder.rule_editor_ok.wait_for_and_click()
        rule_builder.menu_button_rules.wait_for_and_click()
        rule_builder.menu_item_rule_type(rule_type="mapping").wait_for_and_click()
        # TODO: finish test...
