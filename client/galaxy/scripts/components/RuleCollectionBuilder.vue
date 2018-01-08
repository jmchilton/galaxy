<template>
    <state-div v-if="state == 'build'">
        <rule-component title="Add Column"
                        :show.sync="addColumnShow"
                        @okay="handleAddColumn">
            <column-selector :target.sync="addColumnTarget" :col-headers="colHeaders" />
            <regular-expression-input :target.sync="addColumnExpression" />
        </rule-component>
        <rule-component title="Remove Column"
                        :show.sync="removeColumnShow"
                        @okay="handleRemoveColumn">
            <column-selector :target.sync="removeColumnTarget" :col-headers="colHeaders" />
        </rule-component>
        <!--
                        <option value="regex">Matches Regular Expression</option>
                        <option value="empty">Is Empty</option>
                        <option value="matches">Matches Value</option>
                        <option value="contains">Contains Value</option>
                        <option value="compare">Compare to Number</option>
        -->
        <rule-component title="Add Filter"
                        :show.sync="addFilterShow"
                        @okay="handleAddFilter">
            <div><label>
                Filter Type
                <select name="filter_type" v-model="addFilterType">
                    <option value="regex">Matches Regular Expression</option>
                </select>
            </label></div>
            <column-selector :target.sync="addFilterTarget" :col-headers="colHeaders" />
            <regular-expression-input :target.sync="addFilterExpression" />
        </rule-component>
        <rule-component title="Set Column Mapping"
                        :show.sync="columnMappingShow"
                        @okay="handleColumnMapping">
            <div>
                <div class="map"
                     v-for="map in mapping"
                     v-bind:index="map.index"
                     v-bind:key="map.type">
                     <column-selector :label="mapping_targets()[map.type].label" :target.sync="map.columns" :col-headers="colHeaders" :multiple="mapping_targets()[map.type].multiple" />
                </div>
                <div class="btn-group" v-if="unmappedTargets.length > 0">
                  <button type="button" class="primary-button dropdown-toggle" data-toggle="dropdown">
                    <span class="fa fa-plus"></span> {{ "Add Mapping" }}<span class="caret"></span>
                  </button>
                  <ul class="dropdown-menu" role="menu">
                    <li v-for="target in unmappedTargets"
                        v-bind:index="target"
                        v-bind:key="target">
                      <a @click="addIdentifier(target)">{{ mapping_targets()[target].label }}</a>
                    </li>
                  </ul>
                </div>
            </div>
        </rule-component>
        <rule-component title="Add Sort Rule"
                        :show.sync="addSortingShow"
                        @okay="handleSorting">
            <div>
                <column-selector :target.sync="addSortingTarget" :col-headers="colHeaders" />
                <label :title="titleNumericSort">
                    <input type="checkbox" v-model="addSortingNumeric" />
                    {{ l("Numeric sorting.") }}
                </label>
            </div>
        </rule-component>
        <div class="header flex-row no-flex">Describe rules for building up a collection.</div>
        <div class="middle flex-row flex-row-container">
            <div class="column-headers vertically-spaced flex-column-container">
                <div class="table-column flex-column column">
                    <div class="column-header">
                        <div class="column-title">
                            <span class="title">
                                {{ l("Build Collection from Table") }}
                            </span>
                            <!-- <span class="title-info"></span> -->
                        </div>
                        <div class="table-container pull-left">
                            <hot-table id="test-hot"
                                       :data="hotData['data']"
                                       :colHeaders="true"
                                       stretchH="all">
                            </hot-table>
                        </div>
                    </div>
                </div>
                <div class="rule-column flex-column column">
                    <div class="column-header">
                        <div class="column-title">
                            <span class="title">
                                {{ l("Rules") }}
                            </span>
                            <!-- <span class="title-info"></span> -->
                        </div>
                        <div class="rule-container pull-left">
                            <ol class="rules">
                                <!-- Example at the end of https://vuejs.org/v2/guide/list.html -->
                                <rule-display
                                  v-for="(rule, index) in rules"
                                  v-bind:rule="rule"
                                  v-bind:index="index"
                                  v-bind:key="index"
                                  @edit="editRule(rule)"
                                  @remove="removeRule(index)" />
                                <identifier-display v-for="(map, index) in mapping"
                                                    v-bind="map"
                                                    v-bind:index="index"
                                                    v-bind:key="map.type"
                                                    @remove="removeMapping(index)"
                                                    @edit="columnMappingShow = true"
                                                    :col-headers="colHeaders" />
                                <div v-if="mapping.length == 0">
                                    One or more column mappings must be specified. These are required to specify how to build collections and datasets from rows and columns of the table. <a href="#" @click="columnMappingShow = true">Click here</a> to manage column mappings.
                                </div>
                            </ol>
                            <div class="btn-group">
                              <button id="" type="button" class="primary-button dropdown-toggle" data-toggle="dropdown">
                                <span class="fa fa-plus"></span> {{ "Add New Rule" }}<span class="caret"></span>
                              </button>
                              <ul class="dropdown-menu" role="menu">
                                <li><a @click="addColumnNew">Add Column</a></li>
                                <li><a @click="addSortingNew">Add Sorting</a></li>
                                <li><a @click="removeColumnNew">Remove Column</a></li>
                                <li><a @click="addFilterNew">Add Row Filter</a></li>
                                <li><a @click="columnMappingShow = true">Add / Modify Column Mappings</a></li>
                              </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="footer flex-row no-flex">
            <div class="attributes clear">
                <div class="clear">
                    <label class="setting-prompt pull-right">
                        {{ l("Hide original elements") }}?
f                    </label>
                    <span class="upload-footer-title">Type (set all):</span>
                    <span class="upload-footer-extension">
                        <!--
                        <select2 name="extension" :multiple="multiple">
                            <option v-for="(col, index) in Galaxy.list_extensions" :value="index">{{ col }}</option>
                        </select2>
                        -->
                    </span>
                    <span class="upload-footer-extension-info upload-icon-button fa fa-search"/>
                    <span class="upload-footer-title">Genome (set all):</span>
                </div>
                <div class="clear">
                    <input class="collection-name form-control pull-right" 
                    :placeholder="namePlaceholder" v-model="collectionName" />
                    <div class="collection-name-prompt pull-right">
                        {{ l("Name") }}:
                    </div>
                </div>
            </div>
            <option-buttons-div>
                <button @click="cancel" class="creator-cancel-btn btn" tabindex="-1">
                    {{ l("Cancel") }}
                </button>
                <button @click="resetRules" :title="titleReset" class="creator-reset-btn btn">
                    {{ l("Reset") }}
                </button>
                <button @click="createCollection" class="create-collection btn btn-primary" v-bind:class="{ disabled: !validInput }">
                    {{ l("Create") }}
                </button>
            </option-buttons-div>
        </div>
    </state-div>
    <state-div v-else-if="state == 'wait'">
        <div class="header flex-row no-flex">
            {{ l("Galaxy is waiting for collection creation, this dialog will close when this is complete.") }}
        </div>
        <div class="footer flex-row no-flex">
            <option-buttons-div>
                <button @click="cancel" class="creator-cancel-btn btn" tabindex="-1">
                    {{ l("Close") }}
                </button>
            </option-buttons-div>
        </div>
    </state-div>
    <state-div v-else-if="state == 'error'">
        <!-- TODO: steal styling from paired collection builder warning... -->
        <div>
            {{ errorMessage }}
        </div>
    </state-div>
</template>
<script>
import axios from "axios";
import _l from "utils/localization";
import HotTable from 'vue-handsontable-official';
import Vue from "libs/vue";
import Popover from "mvc/ui/ui-popover";

const MAPPING_TARGETS = {
    list_identifiers: {
        multiple: true,
        label: _l("List Identifiers"),
        help: _l("This should be a short description of the replicate, sample name, condition, etc... that describes each level of the list structure.")
    },
    paired_identifier: {
        label: _l("Paired-end Indicator"),
        help: _l("This should be set to '1', 'R1', 'forward', 'f', or 'F' to indicate forward reads, and '2', 'r' or 'reverse', 'R2', 'R', or 'R2' to indicate reverse reads.")
    },
    dbkey: {
        label: _l("Genome"),
        mode: "raw",
    },
    file_type: {
        label: _l("Type"),
        mode: "raw",
        help: _l("This should be the Galaxy file type corresponding to this file."),
    },
    url: {
        label: _l("URL"),
        mode: "raw",
        help: _l("This should be a URL the file can be downloaded from."),
    },
    ftp_path: {
        label: _l("FTP Path"),
        mode: "raw",
        help: _l("This should be the path to the target file to include relative to your FTP directory on the Galaxy server"),
    }
}


// Local components...

// Based on https://vuejs.org/v2/examples/select2.html but adapted to handle list values
// with "multiple: true" set.
const Select2 = {
  props: ['options', 'value'],
  template: `<select>
    <slot></slot>
  </select>`,
  mounted: function () {
    var vm = this
    $(this.$el)
      // init select2
      .select2({ data: this.options })
      .val(this.value)
      .trigger('change')
      // emit event on change.
      .on('change', function (event) {
        vm.$emit('input', event.val);
      })
  },
  watch: {
    value: function (value) {
      // update value
      $(this.$el).val(value)
    },
    options: function (options) {
      // update options
      $(this.$el).empty().select2({ data: options })
    }
  },
  destroyed: function () {
    $(this.$el).off().select2('destroy')
  }
};


const ColumnSelector = {
    template: `
        <div><label>
            {{ label }}
            <select2 name="add_column" :value="target" @input="handleInput" :multiple="multiple">
                <option v-for="(col, index) in colHeaders" :value="index">{{ col }}</option>
            </select2>
        </label></div>
    `,
    props: {
        target: {
            required: true
        },
        label: {
            required: false,
            type: String,
            default: _l("From Column"),
        },
        colHeaders: {
            type: Array,
            required: true
        },
        multiple: {
            type: Boolean,
            required: false,
            default: false,
        },
    },
    methods: {
        handleInput(value) {
            if(this.multiple) {
                // https://stackoverflow.com/questions/262427/why-does-parseint-yield-nan-with-arraymap
                let val = value.map((idx) => parseInt(idx));
                this.$emit('update:target', val);
            } else {
                this.$emit('update:target', parseInt(value));
            }
        }
    },
    components: {
        Select2,
    }
}


const RegularExpressionInput = {
    template: `
        <div><label>
            Regular Expression
            <input name="expression" type="text" :value="target" @input="$emit('update:target', $event.target.value)" />
        </label></div>
    `,
    props: {
        target: {
             required: true
        },
    }
}


const RuleDisplay = {
    template: `
        <li class="rule">{{ title }}
            <span class="fa fa-edit" @click="edit"></span>
            <span class="fa fa-times" @click="remove"></span>
        </li>
    `,
    props: {
        rule: {
           required: true,
           type: Object,
        }
    },
    computed: { 
        title() {
            const ruleType= this.rule.type;
            if(this.rule.type == "add_column") {
                return "Add Column";
            } else if(ruleType == "remove_column") {
                return "Remove Column";
            } else if(ruleType == "add_filter") {
                return "Filter Rows"
            } else if(ruleType == "sort") {
                return "Sort by Column";
            } else {
                return "Unknown rule encountered."
            }
        }
    },
    methods: {
        edit() {
            this.$emit('edit');
        },
        remove() {
            this.$emit('remove');
        }
    },
}

const Identifier = {
    template: `<div class="map">{{ type }}<input type="text" :value="columns" @input="$emit('update:columns', $event.target.value.split(','))"></div>`,
    props: {
        type: {
            type: String,
            required: true
        },
        columns: {
            type: Array,
            required: true
        }
    }
}

const IdentifierDisplay = {
    template: `
      <li class="rule" :title="help">
        Set {{ columnsLabel }} as {{ typeDisplay }}
        <span class="fa fa-edit" @click="edit"></span>
        <span class="fa fa-times" @click="remove"></span>
      </li>
    `,
    props: {
        type: {
            type: String,
            required: true
        },
        columns: {
            required: true
        },
        colHeaders: {
            type: Array,
            required: true
        },
    },
    methods: {
        remove() {
            this.$emit('remove');
        },
        edit() {
            this.$emit('edit');
        }
    },
    computed: {
        typeDisplay() {
            return MAPPING_TARGETS[this.type].label;
        },
        help() {
            return MAPPING_TARGETS[this.type].help || '';
        },
        columnsLabel() {
            let columnNames;
            if(typeof this.columns == "object") {
                columnNames = this.columns.map(idx => this.colHeaders[idx]);
            } else {
                columnNames = [this.colHeaders[this.columns]];
            }
            if(columnNames.length == 2) {
                return "columns " + columnNames[0] + " and " + columnNames[1];
            } else if(columnNames.length > 2) {
                return "columns " + columnNames.slice(0, -1).join(", ") + ", and " + columnNames[columnNames.length - 1];
            } else {
                return "column " + columnNames[0];
            }
        }
    }
}

const RuleComponent = {
    template: `    
    <div class="ui-popover popover" style="display: block" v-show="show">
        <div class="arrow"/>
        <div class="popover-title">
            <div class="popover-title-label">{{ title }}</div>
            <div class="popover-close fa fa-times-circle" @click="close" />
        </div>
        <div class="popover-content">
            <slot></slot>
            <div class="buttons">
               <button type="button" class="ui-button-default btn btn-default" @click="okay">Okay</button>
               <button type="button" class="ui-button-default btn" @click="close">Close</button>
            </div>
        </div>
    </div>`,
    props: {
        'title': {
            type: String,
            required: true,
        },
        'show': {
            type: Boolean,
            required: false
        },
    },
    methods: {
      close() {
          this.$emit('close');
          this.$emit('update:show', false);
      },
      okay() {
          this.$emit('okay');
          this.close();
      },
    },
    mounted: function () {
      document.addEventListener("keydown", (e) => {
        if (this.show && e.keyCode == 27) {
          this.close();
        }
      });
    }
};

const StateDiv = {
    template: `<div class="rule-collection-creator collection-creator flex-row-container"><slot></slot></div>`
}

const OptionButtonsDiv = {
    template: `<div class="actions clear vertically-spaced"><div class="main-options pull-right"><slot></slot></div></div>`
}

export default {
  data: () => {
    return {
        rules: [],
        // TODO: incorrect to ease testing, fix.
        //mapping: [{"type": "list_identifiers", "columns": [1, 2]}],
        mapping: [{"type": "url", "columns": [0]}, {"type": "list_identifiers", "columns": [1]}, {"type": "paired_identifier", "columns": [3]}],
        state: 'build',  // 'build', 'error', 'wait',
        errorMessage: '',
        waitingJobState: 'new',
        titleReset: _l("Undo all reordering and discards"),
        titleNumericSort: _l("By default columns will be sorted lexiographically, check this option if the columns are numeric values and should be sorted as numbers."),
        namePlaceholder: _l("Enter a name for your new collection"),
        addColumnTarget: 0,
        addColumnExpression: "",
        addColumnShow: false,
        addColumnActiveRule: null,
        removeColumnTarget: 0,
        removeColumnShow: false,
        removeColumnActiveRule: null,
        addFilterShow: false,
        addFilterType: "regex",
        addFilterTarget: 0,
        addFilterExpression: "",
        addFilterActiveRule: null,
        addSortingShow: false,
        addSortingTarget: 0,
        addSortingActiveRule: null,
        addSortingNumeric: false,
        columnMappingShow: false,
        collectionName: "",
    };
  },
  props: {
    initialElements: {
        type: Array,
        required: true
    },
    elementsType: {
        type: String,
        required: false,
        default: "datasets",
    },
    // required if elementsType is "datasets" - hook into Backbone code for creating
    // collections from HDAs, etc...
    creationFn: {
        required: false,
        type: Function,
    },
    // Callbacks sent in by modal code.
    oncancel: {
        required: true,
        type: Function,
    },
    oncreate: {
        required: true,
        type: Function,
    }
  },
  computed: {
    mappedTargets() {
      const targets = [];
      for(let mapping of this.mapping) {
        targets.push(mapping.type);
      }
      return targets;
    },
    unmappedTargets() {
      const targets = [];
      const mappedTargets = this.mappedTargets;
      for(let target in MAPPING_TARGETS) {
        const targetMode = MAPPING_TARGETS[target].mode;
        if(targetMode && targetMode !== this.elementsType) {
          continue;
        }
        if(mappedTargets.indexOf(target) < 0) {
          targets.push(target);
        }
      }
      return targets;
    },
    hotData() {
      let data, sources;
      if(this.elementsType == "datasets") {
        data = this.initialElements.map(el => [el["name"], "sample1", el["name"]]);
        sources = this.initialElements.slice();
      } else {
        data = this.initialElements.slice();
        sources = data.map(el => null);
      }

      for(var rule of this.rules) {
        var ruleType = rule.type;
        if(ruleType === "add_column") {
          const regExp = RegExp(rule.expression);
          const target = rule.target_column;
          function newRow(row) {
            const source = row[target];
            const match = regExp.exec(source);
            let newValue;
            if(match.length == 0) {
              //TODO: signal error with rule
            } else if(match.length > 1) {
              newValue = match[1];
            } else {
              newValue = match[0];
            }
            return row.concat([newValue]);
          }
          data = data.map(newRow);
        } else if(ruleType == "remove_column") {
          const target = rule.target_column;
          function newRow(row) {     
            row.splice(target, 1);
            return row;
          }
          data = data.map(newRow);
        } else if(ruleType == "add_filter") {
          const target = rule.target_column;
          const regExp = RegExp(rule.expression);
          // TODO: dispatch on filter type...
          filterFunction = function(el, index) {
              const row = data[index];
              return regExp.exec(row[target]);
          }
          data = data.filter(filterFunction);
          sources = sources.filter(filterFunction)
        } else if(ruleType == "sort") {
          const target = rule.target_column;
          const numeric = rule.numeric;
          const sort = (a, b) => {
            let aVal = a[target];
            let bVal = b[target];
            if(numeric) {
              aVal = parseFloat(aVal);
              bVal = parseFloat(bVal);
            }
            if(aVal < bVal) {
              return -1;
            } else if(bVal < aVal) {
              return 1;
            } else {
              return 0;
            }
          }
          data.sort(sort);
          sources.sort(sort);
        }
      }
      return {"data": data, "sources": sources};
    },
    colHeaders() {
      return this.hotData["data"][0].map((el, i) => String.fromCharCode(65 + i));
    },
    mappingAsDict() {
      const asDict = {};
      for(let mapping of this.mapping) {
        asDict[mapping.type] = mapping;
      }
      return asDict;
    },
    collectionType() {
      const identifierColumns = this.mappingAsDict.list_identifiers.columns;
      let collectionType = identifierColumns.map(col => "list").join(":");
      if(this.mappingAsDict.paired_identifier) {
          collectionType += ":paired";
      }
      return collectionType;
    },
    validInput() {
        let valid = this.collectionName.length > 0;
        const mappingAsDict = this.mappingAsDict;
        if(mappingAsDict.ftp_path && mapping.url) {
          valid = false;
        }
        return valid;
    }
  },
  methods: {
    l(str) {
        return _l(str);
    },
    cancel() {
        this.oncancel();
    },
    mapping_targets() {
      return MAPPING_TARGETS;
    },
    resetRules() {
      this.rules.splice(0, this.rules.length);
      this.mapping.splice(0, this.mapping.length);
      this.state = 'build';
      this.errorMessage = '';
      this.collectionName = '';
    },
    addColumnNew() {
      this.addColumnTarget = 0;
      this.addColumnExpression = "";
      this.addColumnActiveRule = null;
      this.addColumnShow = true;
    },
    addFilterNew() {
      this.addFilterTarget = 0;
      this.addFilterExpression = "";
      this.addFilterActiveRule = null;
      this.addFilterShow = true;
    },
    addSortingNew() {
      this.addSortingTarget = 0;
      this.addSortingShow = true;
      this.addSortingNumeric = false;
    },
    removeColumnNew() {
       this.removeColumnTarget = 0;
       this.removeColumnActiveRule = null;
       this.removeColumnShow = true;
    },
    handleAddColumn() {
      const rule = this.addColumnActiveRule;
      if(rule) {
        rule.target_column = this.addColumnTarget;
        rule.expression = this.addColumnExpression;
      } else {
        this.rules.push({
          "type": "add_column",
          "target_column": this.addColumnTarget,
          "expression": this.addColumnExpression,
        });
      }
    },
    handleSorting() {
      const rule = this.addSortingActiveRule;
      const numeric = this.addSortingNumeric;
      const target = this.addSortingTarget;
      if(rule) {
        rule.target_column = target;
        rule.numeric = numeric;
      } else {
        this.rules.push({
          "type": "sort",
          "numeric": numeric,
          "target_column": target,
        });
      }
    },
    handleRemoveColumn() {
      const rule = this.removeColumnActiveRule;
      if(rule) {
        rule.target_column = this.removeColumnTarget;
      } else {
        this.rules.push({
          "type": "remove_column",
          "target_column": this.removeColumnTarget,
        });
      }    
    },
    handleAddFilter() {
      const rule = this.addFilterActiveRule;
      if(rule) {
        rule.target_column = this.addFilterTarget;
        rule.filter_type = this.addFilterType;
        rule.expression = this.addFilterExpression;
      } else {
        this.rules.push({
          "type": "add_filter",
          "target_column": this.addFilterTarget,
          "expression": this.addFilterExpression,
          "filter_type": this.addFilterType,
        });
      }    
    },
    handleColumnMapping() {

    },
    addIdentifier(identifier) {
      this.mapping.push({"type": identifier, "columns": [0]})
    },
    editRule(rule) {
       const ruleType = rule.type;
       if(ruleType == "add_column") {
           this.addColumnTarget = rule.target_column;
           this.addColumnExpression = rule.expression;
           this.addColumnShow = true;
           this.addColumnActiveRule = rule;
       } else if (ruleType == "remove_column") {
           this.removeColumnText = rule.target_column;
           this.removeColumnShow = true;
           this.removeColumnActiveRule = rule;
       } else if(ruleType == "add_filter") {
           this.addFilterTarget = rule.target_column;
           this.addFilterExpression = rule.expression;
           this.addFilterType = rule.filter_type;
           this.addFilterShow = true;
           this.addFilterActiveRule = rule;
       } else if(ruleType == "sort") {
           this.addSortingTarget = rule.target_column;
           this.addSortingNumeric = rule.numeric;
           this.addSortingShow = true;
           this.addSortingActiveRule = rule;        
       }
    },
    removeRule(index) {
        this.rules.splice(index, 1);
    },
    removeMapping(index) {
        this.mapping.splice(index, 1);
    },
    waitOnJob(response) {
        const jobId = response.data.jobs[0].id;
        const handleJobShow = (jobResponse) => {
            console.log(jobResponse);
            const state = jobResponse.data.state;
            this.waitingJobState = state;
            if(state === "ok") {
                const history = parent.Galaxy && parent.Galaxy.currHistoryPanel && parent.Galaxy.currHistoryPanel.model;
                history.refresh();
                this.oncreate();
            } else {
                setTimeout(doJobCheck, 1000);
            }
        }
        const doJobCheck = () => {
            axios
                .get(`${Galaxy.root}api/jobs/${jobId}`)
                .then(handleJobShow)
                .catch(this.renderFetchError);
        }
        setTimeout(doJobCheck, 1000);
    },
    renderFetchError(error) {
        this.state = 'error';
        if(error.response) {
            console.log(error.response);
            this.errorMessage = error.response.data.err_msg;        
        } else {
            console.log(error);
            this.errorMessage = "Unknown error encountered: " + error;
        }
    },
    createCollection() {
        this.state = 'wait';
        const name = this.collectionName;
        const collectionType = this.collectionType;
        if(this.elementsType == "datasets") {
            const elements = this.creationElementsFromDatasets();
            const response = this.creationFn(
                elements, collectionType, name
            )
            response.done(this.oncreate);
            response.error(this.renderFetchError);
        } else {
            const elements = this.creationElementsForFetch();
            const historyId = Galaxy.currHistoryPanel.model.id;
            const targets = [{
                "destination": {"type": "hdca"},
                "elements": elements,
                "collection_type": collectionType,
                "name": name,
            }];
            axios
                .post(`${Galaxy.root}api/tools/fetch`, {
                    "history_id": historyId,
                    "targets": targets,
                })
                .then(this.waitOnJob)
                .catch(this.renderFetchError);
        }
    },
    buildRequestElements(createDatasetDescription, createSubcollectionDescription, subElementProp) {
        const data = this.hotData["data"];
        const mappingAsDict = this.mappingAsDict;
        const identifierColumns = mappingAsDict.list_identifiers.columns.slice();
        if(this.mappingAsDict.paired_identifier) {
            identifierColumns.push(this.mappingAsDict.paired_identifier.columns[0]);
        }
        if(!identifierColumns || identifierColumns.length < 1) {
            // TODO: flag error if not list of columns...
            return;
        }

        const numIdentifierColumns = identifierColumns.length;
        const collectionType = this.collectionType;
        const elements = [];

        for(let dataIndex in data) {
            const rowData = data[dataIndex];

            // For each row, find place in depth for this element.
            let collectionTypeAtDepth = collectionType;
            let elementsAtDepth = elements;

            for(let identifierColumnIndex = 0; identifierColumnIndex < numIdentifierColumns; identifierColumnIndex++) {
                let identifier = rowData[identifierColumns[identifierColumnIndex]];
                if(identifierColumnIndex + 1 == numIdentifierColumns) {
                    // At correct final position in nested structure for this dataset.
                    if(collectionTypeAtDepth === "paired") {
                        if(["f", "1", "r1", "forward"].indexOf(identifier.toLowerCase()) > -1) {
                            identifier = "forward";
                        } 
                        else if(["r", "2", "r2", "reverse"].indexOf(identifier.toLowerCase()) > -1) {
                            identifier = "reverse";
                        }
                        else {
                            // TODO
                            console.log("Problem with paired identifier - this will fail...");
                        }
                    }
                    const element = createDatasetDescription(dataIndex, identifier);
                    elementsAtDepth.push(element);
                } else {
                    // Create nesting for this element.
                    collectionTypeAtDepth = collectionTypeAtDepth.split(":").slice(1).join(":");
                    let found = false;
                    for(let element of elementsAtDepth) {
                        if(element["name"] == identifier) {
                            elementsAtDepth = element[subElementProp];
                            found = true;
                            break;
                        }
                    }
                    if(!found) {
                        const subcollection = createSubcollectionDescription(identifier);
                        elementsAtDepth.push(subcollection);
                        const childCollectionElements = [];
                        subcollection[subElementProp] = childCollectionElements;
                        subcollection.collection_type = collectionTypeAtDepth;
                        elementsAtDepth = childCollectionElements;
                    }
                }
            }
        }

        return elements;
    },
    // TODO: refactor next two methods with for overlap via a visitor pattern.
    creationElementsFromDatasets() {
        const sources = this.hotData["sources"];
        const data = this.hotData["data"];

        return this.buildRequestElements(
            (dataIndex, identifier) => {
                const source = sources[dataIndex];
                return {"id": source["id"], "name": identifier, "src": "hda"}
            },
            (identifier) => {
                return {"name": identifier, "src": "new_collection"};
            },
            "element_identifiers",
        );
    },
    creationElementsForFetch() {
        const data = this.hotData["data"];
        const mappingAsDict = this.mappingAsDict;

        return this.buildRequestElements(
            (dataIndex, identifier) => {
                const urlColumn = mappingAsDict.url.columns[0];
                const url = data[dataIndex][urlColumn];
                return {"url": url, "name": identifier, "src": "url"}
            },
            (identifier) => {
                return {"name": identifier};
            },
            "elements",
        );
    }
  },
  components: {
    HotTable,
    RuleComponent,
    RuleDisplay,
    Identifier,
    IdentifierDisplay,
    ColumnSelector,
    RegularExpressionInput,
    StateDiv,
    OptionButtonsDiv,
  }
}
</script>

<style>
  .table-container {
    width: 100%;
  }
  #test-hot {
    width: 100%;
    height: 400px;
    overflow: hidden;
  }
  .rules {
    height: 360px;
  }
  .rules-buttons {

  }
</style>
