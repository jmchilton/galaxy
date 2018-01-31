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
    def test_rules_example_1_datasets(self):
        # Test case generated for:
        #   https://www.ebi.ac.uk/ena/data/view/PRJDA60709
        self.home()
        self.upload_rule_start()
        self.screenshot("rules_example_1_1_rules_landing")
        self.components.upload.rule_source_content.wait_for_and_send_keys("""study_accession sample_accession    experiment_accession    fastq_ftp
PRJDA60709  SAMD00016379    DRX000475   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000770/DRR000770.fastq.gz
PRJDA60709  SAMD00016383    DRX000476   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000771/DRR000771.fastq.gz
PRJDA60709  SAMD00016380    DRX000477   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000772/DRR000772.fastq.gz
PRJDA60709  SAMD00016378    DRX000478   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000773/DRR000773.fastq.gz
PRJDA60709  SAMD00016381    DRX000479   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000774/DRR000774.fastq.gz
PRJDA60709  SAMD00016382    DRX000480   ftp.sra.ebi.ac.uk/vol1/fastq/DRR000/DRR000775/DRR000775.fastq.gz""")
        self.screenshot("rules_example_1_2_paste")
        self.upload_rule_build()
        rule_builder = self.components.rule_builder
        rule_builder._.wait_for_and_click()
        self.screenshot("rules_example_1_3_initial_rules")
        rule_builder.menu_button_filter.wait_for_and_click()
        self.screenshot("rule_builder_filters")
        rule_builder.menu_item_rule_type(rule_type="add-filter-count").wait_for_and_click()
        filter_editor = rule_builder.rule_editor(rule_type="add-filter-count")
        filter_editor_element = filter_editor.wait_for_visible()
        filter_input = filter_editor_element.find_element_by_css_selector("input[type='number']")
        filter_input.clear()
        filter_input.send_keys("1")
        self.screenshot("rules_example_1_4_filter_header")
        rule_builder.rule_editor_ok.wait_for_and_click()
        self.rule_builder_set_mapping("url", "D")
        self.rule_builder_set_mapping("name", "C", screenshot_name="rules_example_1_5_mapping_edit")
        self.screenshot("rules_example_1_6_mapping_set")
        self.select2_set_value(".rule-option-extension", "fastqsanger.gz")
        self.screenshot("rules_example_1_7_extension_set")
        # rule_builder.main_button_ok.wait_for_and_click()
        # self.history_panel_wait_for_hid_ok(6)
        # self.screenshot("rules_example_1_6_download_complete")

    @selenium_test
    def test_rules_example_2_list(self):
        self.perform_upload(self.get_filename("rules/PRJDA60709.tsv"))
        self.history_panel_wait_for_hid_ok(1)
        self.upload_rule_start()
        self.upload_rule_set_data_type("Collection")
        self.upload_rule_set_input_type("History Dataset")
        self.upload_rule_set_dataset("1:")
        self.screenshot("rules_example_2_1_inputs")
        self.upload_rule_build()
        rule_builder = self.components.rule_builder
        rule_builder._.wait_for_and_click()
        self.screenshot("rules_example_2_2_initial_rules")
        # Filter header.
        self.rule_builder_filter_count(1)
        self.rule_builder_set_mapping("url", "D")
        self.rule_builder_set_mapping("list-identifiers", "C")
        self.rule_builder_set_extension("fastqsanger.gz")
        self.screenshot("rules_example_2_3_rules")
        self.rule_builder_set_collection_name("PRJDA60709")
        self.screenshot("rules_example_2_4_name")
        # rule_builder.main_buton_ok.wait_for_and_click()
        # self.history_panel_wait_for_hid_ok(2)
        # self.screenshot("rules_example_2_5_download_complete")

    @selenium_test
    def test_rules_example_3_list_pairs(self):
        self.perform_upload(self.get_filename("rules/PRJDB3920.tsv"))
        self.history_panel_wait_for_hid_ok(1)
        self.upload_rule_start()
        self.upload_rule_set_data_type("Collection")
        self.upload_rule_set_input_type("History Dataset")
        self.upload_rule_set_dataset("1:")
        self.screenshot("rules_example_3_1_inputs")
        self.upload_rule_build()
        rule_builder = self.components.rule_builder
        rule_builder._.wait_for_and_click()
        self.screenshot("rules_example_3_2_initial_rules")
        # Filter header.
        self.rule_builder_filter_count(1)
        self.rule_builder_set_mapping("list-identifiers", "C")
        self.select2_set_value(".rule-option-extension", "fastqsanger.gz")
        self.screenshot("rules_example_3_3_old_rules")
        self.rule_builder_add_regex_groups("D", 2, "(.*);(.*)", screenshot_name="rules_example_3_4_regex")
        self.screenshot("rules_example_3_6_with_regexes")
        # Remove A also?
        self.rule_builder_remove_columns(["D"], screenshot_name="rules_example_3_7_removed_column")
        self.rule_builder_split_column("D", "E", screenshot_name="rules_example_3_8_split_columns")
        self.screenshot("rules_example_3_9_columns_are_split")
        self.rule_builder_add_regex_groups("D", 1, ".*_(\d).fastq.gz", screenshot_name="rules_example_3_10_regex_paired")
        self.screenshot("rules_example_3_11_has_paired_id")
        self.rule_builder_swap_columns("D", "E", screenshot_name="rules_example_3_12_swap_columns")
        self.screenshot("rules_example_3_13_swapped_columns")
        self.rule_builder_set_mapping("paired-identifier", "D")
        self.rule_builder_set_mapping("url", "E")
        self.rule_builder_set_collection_name("PRJDB3920")
        self.screenshot("rules_example_3_14_paired_identifier_set")

    @selenium_test
    def test_rules_example_4_accessions(self):
        # http://www.uniprot.org/uniprot/?query=proteome:UP000052092+AND+proteomecomponent:%22Genome%22
        self.perform_upload(self.get_filename("rules/uniprot.tsv"))
        self.history_panel_wait_for_hid_ok(1)
        self.upload_rule_start()
        self.upload_rule_set_data_type("Collection")
        self.upload_rule_set_input_type("History Dataset")
        self.upload_rule_set_dataset("1:")
        self.screenshot("rules_example_4_1_inputs")
        self.upload_rule_build()
        rule_builder = self.components.rule_builder
        rule_builder._.wait_for_and_click()
        self.screenshot("rules_example_4_2_initial_rules")
        self.rule_builder_filter_count(1)
        self.rule_builder_remove_columns(["B", "C", "E", "F", "G"])
        # TODO: sort
        self.rule_builder_set_mapping("info", "B")
        self.screenshot("rules_example_4_3_basic_rules")

        self.rule_builder_add_value("http://www.uniprot.org/uniprot/", screenshot_name="rules_example_4_4_add_value")  # C
        self.rule_builder_concatenate_columns("C", "A", screenshot_name="rules_example_4_5_concatenate_columns")  # D
        self.rule_builder_remove_columns(["C"])
        self.rule_builder_add_value("fasta")  # D
        self.rule_builder_concatenate_columns("C", "D")  # E
        self.rule_builder_remove_columns(["C"])
        self.screenshot("rules_example_4_6_url_built")
        self.rule_builder_set_mapping("list-identifiers", "B")
        self.rule_builder_set_mapping("url", "C")
        self.rule_builder_set_extension("fasta")
        self.rule_builder_set_collection_name("PRJDB3920")
        self.screenshot("rules_example_4_7_mapping_extension_and_name")

    # @selenium_test
    # def test_rules_example_5_matching_collections(self):
    #    self.rule_builder_add_value("Protein FASTA")
    #     self.rule_builder_add_value("gff")
    #    self.rule_builder_add_value("Protein GFF")
