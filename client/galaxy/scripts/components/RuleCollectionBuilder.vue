<template>
    <state-div v-if="state == 'build'">
        <!--
                        <option value="add_filter_matches">Matches Value</option>
                        <option value="add_filter_contains">Contains Value</option>
                        <option value="add_filter_compare">Compare to Number</option>
                        <option value="add_column_prefix">Prefix / Suffix</option>
        -->
        <div class="header flex-row no-flex">Describe rules for building up a collection.</div>
        <div class="middle flex-row flex-row-container">
            <div class="column-headers vertically-spaced flex-column-container">
                <div class="rule-column flex-column column" style="width: 30%; padding: 10px;">
                    <div class="column-header">
                        <div class="rules-container">
                            <rule-component rule-type="sort"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="addSortingTarget" :col-headers="colHeaders" />
                                <label :title="titleNumericSort">
                                    <input type="checkbox" v-model="addSortingNumeric" />
                                    {{ l("Numeric sorting.") }}
                                </label>
                            </rule-component>
                            <rule-component rule-type="add_column_basename"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="addColumnBasenameTarget" :col-headers="colHeaders" />
                            </rule-component>
                            <rule-component rule-type="add_column_regex"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="addColumnRegexTarget" :col-headers="colHeaders" />
                                <regular-expression-input :target.sync="addColumnExpression" />
                            </rule-component>
                            <rule-component rule-type="add_column_concatenate"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="addColumnConcatenateTarget0" :col-headers="colHeaders" />
                                <column-selector :target.sync="addColumnConcatenateTarget1" :col-headers="colHeaders" />
                            </rule-component>
                            <rule-component rule-type="remove_columns"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="removeColumnTargets" :col-headers="colHeaders" :multiple="true" />
                            </rule-component>
                            <rule-component rule-type="split_columns"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="splitColumnsTargets0" :col-headers="colHeaders" :multiple="true" />
                                <column-selector :target.sync="splitColumnsTargets1" :col-headers="colHeaders" :multiple="true" />
                            </rule-component>
                            <rule-component rule-type="swap_columns"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="swapColumnsTarget0" :col-headers="colHeaders" />
                                <column-selector :target.sync="swapColumnsTarget1" :col-headers="colHeaders" />
                            </rule-component>
                            <rule-component rule-type="add_filter_regex"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="addFilterRegexTarget" :col-headers="colHeaders" />
                                <regular-expression-input :target.sync="addFilterRegexExpression" />
                                <label :title="titleInvertFilterRegex">
                                    <input type="checkbox" v-model="addFilterRegexInvert" />
                                    {{ l("Invert filter.") }}
                                </label>
                            </rule-component>
                            <rule-component rule-type="add_filter_empty"
                                            :display-rule-type="displayRuleType"
                                            :builder="this">
                                <column-selector :target.sync="addFilterEmptyTarget" :col-headers="colHeaders" />
                                <label :title="titleInvertFilterEmpty">
                                    <input type="checkbox" v-model="addFilterEmptyInvert" />
                                    {{ l("Invert filter.") }}
                                </label>
                            </rule-component>
                            <div v-if="displayRuleType == 'mapping'">
                                <div class="map"
                                     v-for="map in mapping"
                                     v-bind:index="map.index"
                                     v-bind:key="map.type">
                                     <column-selector :label="mappingTargets()[map.type].label" :target.sync="map.columns" :col-headers="colHeaders" :multiple="mappingTargets()[map.type].multiple"
                                     :value-as-list="true" />
                                </div>
                                <div class="buttons">
                                    <div class="btn-group" v-if="unmappedTargets.length > 0">
                                      <button type="button" class="primary-button dropdown-toggle" data-toggle="dropdown">
                                        <span class="fa fa-plus"></span> {{ "Add Mapping" }}<span class="caret"></span>
                                      </button>
                                      <ul class="dropdown-menu" role="menu">
                                        <li v-for="target in unmappedTargets"
                                            v-bind:index="target"
                                            v-bind:key="target">
                                          <a @click="addIdentifier(target)">{{ mappingTargets()[target].label }}</a>
                                        </li>
                                      </ul>
                                    </div>
                                   <button type="button" class="ui-button-default btn btn-default" @click="displayRuleType = null">Okay</button>
                                </div>
                            </div>
                            <div class="rule-summary" v-if="displayRuleType == null">
                                <span class="title">
                                    {{ l("Rules") }}
                                </span>
                                <ol class="rules">
                                    <!-- Example at the end of https://vuejs.org/v2/guide/list.html -->
                                    <rule-display
                                      v-for="(rule, index) in rules"
                                      v-bind:rule="rule"
                                      v-bind:index="index"
                                      v-bind:key="index"
                                      @edit="editRule(rule)"
                                      @remove="removeRule(index)"
                                      :col-headers="colHeaders" />
                                    <identifier-display v-for="(map, index) in mapping"
                                                        v-bind="map"
                                                        v-bind:index="index"
                                                        v-bind:key="map.type"
                                                        @remove="removeMapping(index)"
                                                        @edit="displayRuleType = 'mapping'"
                                                        :col-headers="colHeaders" />
                                    <div v-if="mapping.length == 0">
                                        One or more column mappings must be specified. These are required to specify how to build collections and datasets from rows and columns of the table. <a href="#" @click="displayRuleType = 'mapping'">Click here</a> to manage column mappings.
                                    </div>
                                </ol>
                                <div class="btn-group dropup">
                                  <button id="" type="button" class="primary-button dropdown-toggle" data-toggle="dropdown">
                                    <span class="fa fa-plus"></span> {{ "Rules" }}<span class="caret"></span>
                                  </button>
                                  <ul class="dropdown-menu" role="menu">
                                    <li><a @click="addNewRule('sort')">Add Sorting</a></li>
                                    <li><a @click="addNewRule('remove_columns')">Remove Columns</a></li>
                                    <li><a @click="addNewRule('split_columns')">Split Columns</a></li>
                                    <li><a @click="addNewRule('swap_columns')">Swap Columns</a></li>
                                    <li><a @click="displayRuleType = 'mapping'">Add / Modify Column Mappings</a></li>
                                  </ul>
                                </div>
                                <div class="btn-group dropup">
                                    <button id="" type="button" class="primary-button dropdown-toggle" data-toggle="dropdown">
                                        <span class="fa fa-plus"></span> {{ "Filter" }}<span class="caret"></span>
                                    </button>
                                    <ul class="dropdown-menu" role="menu">
                                        <li><a @click="addNewRule('add_filter_regex')">{{ l("Using a Regular Expression") }}</a></li>
                                        <li><a @click="addNewRule('add_filter_empty')">{{ l("On Emptiness") }}</a></li>
                                  </ul>
                                </div>                                
                                <div class="btn-group dropup">
                                    <button id="" type="button" class="primary-button dropdown-toggle" data-toggle="dropdown">
                                        <span class="fa fa-plus"></span> {{ "Column" }}<span class="caret"></span>
                                    </button>
                                    <ul class="dropdown-menu" role="menu">
                                        <li><a @click="addNewRule('add_column_basename')">{{ l("Basename of Path of URL") }}</a></li>
                                        <li><a @click="addNewRule('add_column_regex')">{{ l("Using a Regular Expression") }}</a></li>
                                        <li><a @click="addNewRule('add_column_concatenate')">{{ l("Concatenate Columns") }}</a></li>
                                  </ul>
                                </div>                                
                            </div>
                        </div>
                    </div>
                </div>
                <div class="table-column flex-column column" style="width: 70%;">
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
            </div>
        </div>
        <div class="footer flex-row no-flex">
            <div class="attributes clear">
                <label class="rule-option" v-if="elementsType == 'datasets'">
                    {{ l("Hide original elements") }}:
                    <input type="checkbox" v-model="hideSourceItems" />
                </label>
                <label class="rule-option" v-if="elementsType !== 'datasets' && !mappingAsDict.file_type">
                    {{ l("Type") }}:
                    <select2 id="extension-selector" name="extension" style="width: 120px" v-model="extension" v-if="extension">
                        <option v-for="(col, index) in extensions" :value="col['id']"">{{ col["text"] }}</option>
                    </select2>
                </label>
                <label class="rule-option" v-if="elementsType !== 'datasets' && !mappingAsDict.dbkey">
                    {{ l("Genome") }}:
                    <select2 id="genome-selector" style="width: 120px" v-model="genome" v-if="genome">
                        <option v-for="(col, index) in genomes" :value="col['id']"">{{ col["text"] }}</option>
                    </select2>
                </label>
                <label class="rule-option pull-right">
                    {{ l("Name") }}:
                    <input class="collection-name" style="width: 200px" 
                    :placeholder="namePlaceholder" v-model="collectionName" />
                </label>
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
import UploadUtils from "mvc/upload/upload-utils";

const MAPPING_TARGETS = {
    list_identifiers: {
        multiple: true,
        label: _l("List Identifier(s)"),
        help: _l("This should be a short description of the replicate, sample name, condition, etc... that describes each level of the list structure.")
    },
    paired_identifier: {
        label: _l("Paired-end Indicator"),
        help: _l("This should be set to '1', 'R1', 'forward', 'f', or 'F' to indicate forward reads, and '2', 'r' or 'reverse', 'R2', 'R', or 'R2' to indicate reverse reads.")
    },
    dbkey: {
        label: _l("Genome"),
        modes: ["raw", "ftp"],
    },
    file_type: {
        label: _l("Type"),
        modes: ["raw", "ftp"],
        help: _l("This should be the Galaxy file type corresponding to this file."),
    },
    url: {
        label: _l("URL"),
        modes: ["raw"],
        help: _l("This should be a URL the file can be downloaded from."),
    },
    ftp_path: {
        label: _l("FTP Path"),
        modes: ["raw", "ftp"],
        help: _l("This should be the path to the target file to include relative to your FTP directory on the Galaxy server"),
    }
}

const applyRegex = function(regex, target, data) {
    const regExp = RegExp(regex);
    let failedCount = 0;
    function newRow(row) {
        const source = row[target];
        const match = regExp.exec(source);
        let newValue;
        if(!match) {
          failedCount++;
          return null;
        } else if(match.length > 1) {
          newValue = match[1];
        } else {
          newValue = match[0];
        }
        return row.concat([newValue]);
    }
    data = data.map(newRow);
    if(failedCount > 0) {
        return {error: `${failedCount} row(s) failed to match specified regular expression.`};
    }
    return {data};
}

const Rules = {
    add_column_basename: {
        display: (rule, colHeaders) => {
          return `Add column using basename of column ${colHeaders[rule.target_column]}`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.addColumnBasenameTarget = 0;
            } else {
                component.addColumnBasenameTarget = rule.target_column;
            }
        },
        save: (component, rule) => {
            rule.target_column = component.addColumnBasenameTarget;
        },
        apply: (rule, data, sources) => {
            // https://github.com/kgryte/regex-basename-posix/blob/master/lib/index.js        
            const re = /^(?:\/?|)(?:[\s\S]*?)((?:\.{1,2}|[^\/]+?|)(?:\.[^.\/]*|))(?:[\/]*)$/;
            const target = rule.target_column;
            return applyRegex(re, target, data);
        }
    },
    add_column_regex: {
        display: (rule, colHeaders) => {
          return `Add new column using ${rule.expression} applied to column ${colHeaders[rule.target_column]}`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.addColumnRegexTarget = 0;
                component.addColumnExpression = "";
            } else {
                component.addColumnRegexTarget = rule.target_column;
                component.expression = rule.expression;
            }
        },
        save: (component, rule) => {
            rule.target_column = component.addColumnRegexTarget;
            rule.expression = component.addColumnExpression;
        },
        apply: (rule, data, sources) => {
          const target = rule.target_column;
          return applyRegex(rule.expression, target, data);
        }
    },
    add_column_concatenate: {
        display: (rule, colHeaders) => {
          return `Concatenate column ${colHeaders[rule.target_column_0]} and column ${colHeaders[rule.target_column_1]}`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.addColumnConcatenateTarget0 = 0;
                component.addColumnConcatenateTarget1 = 0;
            } else {
                component.addColumnConcatenateTarget0 = rule.target_column_0;
                component.addColumnConcatenateTarget1 = rule.target_column_1;
            }
        },
        save: (component, rule) => {
            rule.target_column_0 = component.addColumnConcatenateTarget0;
            rule.target_column_1 = component.addColumnConcatenateTarget1;
        },
        apply: (rule, data, sources) => {
          const target0 = rule.target_column_0;
          const target1 = rule.target_column_1;
          function newRow(row) {     
            const newRow = row.slice();
            newRow.push(row[target0] + row[target1]);
            return newRow;
          }
          data = data.map(newRow);
          return {data};
        }       
    },
    remove_columns: {
        display: (rule, colHeaders) => {
          return `Remove columns`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.removeColumnTargets = [];
            } else {
                component.removeColumnTargets = rule.target_columns;
            }
        },
        save: (component, rule) => {
            rule.target_columns = component.removeColumnTargets;
        },
        apply: (rule, data, sources) => {
          const targets = rule.target_columns;
          function newRow(row) {
            const newRow = []
            for(let index in row) {
              if(targets.indexOf(parseInt(index)) == -1) {
                newRow.push(row[index]);
              }
            }
            return newRow;
          }
          data = data.map(newRow);
          return {data};
        }
    },
    add_filter_regex: {
        display: (rule, colHeaders) => {
            return `Filter rows using ${rule.expression} on column ${colHeaders[rule.target_column]}`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.addFilterRegexTarget = 0;
                component.addFilterRegexExpression = "";
                component.addFilterRegexInvert = false;
            } else {                
               component.addFilterRegexTarget = rule.target_column;
               component.addFilterRegexExpression = rule.expression;
               component.addFilterRegexInvert = rule.invert;               
            }
        },
        save: (component, rule) => {
            rule.target_column = component.addFilterRegexTarget;
            rule.expression = component.addFilterRegexExpression;
            rule.invert = component.addFilterRegexInvert;
        },
        apply: (rule, data, sources) => {
          const target = rule.target_column;
          const invert = rule.invert;
          const regExp = RegExp(rule.expression);
          const filterFunction = function(el, index) {
              const row = data[parseInt(index)];
              return regExp.exec(row[target]) ? !invert : invert;
          }
          sources = sources.filter(filterFunction);
          data = data.filter(filterFunction);
          return {data, sources};
        }
    },
    add_filter_empty: {
        display: (rule, colHeaders) => {
            return `Filter rows if no value for column ${colHeaders[rule.target_column]}`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.addFilterEmptyTarget = 0;
                component.addFilterEmptyInvert = false;
            } else {
               component.addFilterEmptyTarget = rule.target_column;
               component.addFilterEmptyInvert = rule.invert;
            }
        },
        save: (component, rule) => {
            rule.target_column = component.addFilterEmptyTarget;
            rule.invert = component.addFilterEmptyInvert;
        },
        apply: (rule, data, sources) => {
          const target = rule.target_column;
          const invert = rule.invert;
          const filterFunction = function(el, index) {
              const row = data[parseInt(index)];
              return row[target].length ? !invert : invert;
          }
          sources = sources.filter(filterFunction);
          data = data.filter(filterFunction);
          return {data, sources};
        }
    },
    sort: {
        display: (rule, colHeaders) => {
            return `Sort on column ${colHeaders[rule.target_column]}`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.addSortingTarget = 0;
                component.addSortingNumeric = false;
            } else {                
               component.addSortingTarget = rule.target_column;
               component.addSortingNumeric = rule.numeric;
            }
        },
        save: (component, rule) => {
            rule.target_column = component.addSortingTarget;
            rule.numeric = component.addSortingNumeric;
        },
        apply: (rule, data, sources) => {
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
          return {data, sources};
        }
    },
    swap_columns: {
        display: (rule, colHeaders) => {
            return `Swap columns`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.swapColumnsTarget0 = 0;
                component.swapColumnsTarget1 = 0;
            } else {
                component.swapColumnsTarget0 = rule.target_column_0;
                component.swapColumnsTarget1 = rule.target_column_1;
            }
        },
        save: (component, rule) => {
            rule.target_column_0 = component.swapColumnsTarget0;
            rule.target_column_1 = component.swapColumnsTarget1;
        },
        apply: (rule, data, sources) => {
          const target0 = rule.target_column_0;
          const target1 = rule.target_column_1;
          function newRow(row) {     
            const newRow = row.slice();
            newRow[target0] = row[target1];
            newRow[target1] = row[target0];
            return newRow;
          }
          data = data.map(newRow);
          return {data};
        }
    },
    split_columns: {
        display: (rule, colHeaders) => {
            return `Duplicate each row and split up columns`;
        },
        init: (component, rule) => {
            if(!rule) {
                component.splitColumnsTargets0 = [];
                component.splitColumnsTargets1 = [];
            } else {
                component.splitColumnsTargets0 = rule.target_columns_0;
                component.splitColumnsTargets1 = rule.target_columns_1;
            }
        },
        save: (component, rule) => {
            rule.target_columns_0 = component.splitColumnsTargets0;
            rule.target_columns_1 = component.splitColumnsTargets1;
        },
        apply: (rule, data, sources) => {
            const targets0 = rule.target_columns_0;
            const targets1 = rule.target_columns_1;

            const splitRow = function(row) {
                const newRow0 = [], newRow1 = [];
                for(let index in row) {
                    index = parseInt(index);
                    if(targets0.indexOf(index) > -1) {
                        newRow0.push(row[index]);
                    } else if(targets1.indexOf(index) > -1) {
                        newRow1.push(row[index]);
                    } else {
                        newRow0.push(row[index]);
                        newRow1.push(row[index]);
                    }
                }
                return [newRow0, newRow1];
            }

            data = flatMap(splitRow, data);
            sources = flatMap((src) => [src, src], data);
            return {data, sources};
        }
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
        console.log(event.val);
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
            <select2 :value="target" @input="handleInput" :multiple="multiple">
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
        valueAsList: {
            type: Boolean,
            required: false,
            default: false,
        }
    },
    methods: {
        handleInput(value) {
            if(this.multiple) {
                // https://stackoverflow.com/questions/262427/why-does-parseint-yield-nan-with-arraymap
                let val = value.map((idx) => parseInt(idx));
                this.$emit('update:target', val);
            } else {
                let val = parseInt(value);
                if(this.valueAsList) {
                    val = [val];
                }
                this.$emit('update:target', val);
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
        <li class="rule">
            <span class="rule-display">{{ title }}
                <span class="fa fa-edit" @click="edit"></span>
                <span class="fa fa-times" @click="remove"></span>
            </span>
            <span class="rule-warning" v-if="rule.warn">
                {{ rule.warn }}
            </span>
            <span class="rule-error" v-if="rule.error">
                <span class="alert-message">{{ rule.error }}</span>
            </span>
        </li>
    `,
    props: {
        rule: {
           required: true,
           type: Object,
        },
        colHeaders: {
            type: Array,
            required: true
        },
    },
    computed: { 
        title() {
            const ruleType = this.rule.type;
            return Rules[ruleType].display(this.rule, this.colHeaders);
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
    <div v-if="ruleType == displayRuleType">
        <slot></slot>
        <div class="buttons" style="margin: 5px; height: 25px;">
           <button type="button" class="ui-button-default btn btn-default" @click="okay">Okay</button>
           <button type="button" class="ui-button-default btn" @click="close">Close</button>
        </div>
    </div>`,
    props: {
        ruleType: {
            type: String,
            required: true,
        },
        displayRuleType: {
            required: true,
        },
        builder: {

        },
    },
    methods: {
        close() {
            this.builder.displayRuleType = null;
        },
        okay() {
            this.builder.handleRuleSave(this.ruleType);
            this.close();
        },
    }
}

const StateDiv = {
    template: `<div class="rule-collection-creator collection-creator flex-row-container"><slot></slot></div>`
}

const OptionButtonsDiv = {
    template: `<div class="actions clear vertically-spaced"><div class="main-options pull-right"><slot></slot></div></div>`
}

const flatMap = (f,xs) => {
    return xs.reduce((acc,x) => acc.concat(f(x)), []);
}

export default {
  data: function() {
    let mapping;
    if(this.elementsType == "ftp") {
      mapping = [{"type": "ftp_path", "columns": [0]}];
    } else {
      // TODO: incorrect to ease testing, fix.    
      mapping = [{"type": "url", "columns": [0]}, {"type": "list_identifiers", "columns": [1]}, {"type": "paired_identifier", "columns": [3]}];
    }
    return {
        rules: [],
        mapping: mapping,
        state: 'build',  // 'build', 'error', 'wait',
        errorMessage: '',
        hasRuleErrors: false,
        waitingJobState: 'new',
        titleReset: _l("Undo all reordering and discards"),
        titleNumericSort: _l("By default columns will be sorted lexiographically, check this option if the columns are numeric values and should be sorted as numbers."),
        titleInvertFilterRegex: _l("Remove rows not matching the specified regular expression at specified column."),
        titleInvertFilterEmpty: _l("Remove rows that have non-empty values at specified column."),
        namePlaceholder: _l("Enter a name for your new collection"),
        activeRule: null,
        addColumnRegexTarget: 0,
        addColumnBasenameTarget: 0,
        addColumnExpression: "",
        addColumnConcatenateTarget0: 0,
        addColumnConcatenateTarget1: 0,
        removeColumnTargets: [],
        addFilterRegexTarget: 0,
        addFilterRegexExpression: "",
        addFilterRegexInvert: false,
        addFilterEmptyTarget: 0,
        addFilterEmptyInvert: false,
        addSortingTarget: 0,
        addSortingNumeric: false,
        splitColumnsTargets0: [],
        splitColumnsTargets1: [],
        swapColumnsTarget0: 0,
        swapColumnsTarget1: 0,
        collectionName: "",
        displayRuleType: null,
        extensions: [],
        extension: null,
        genomes: [],
        genome: null,
        hideSourceItems: this.defaultHideSourceItems,
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
    defaultHideSourceItems: {
        type: Boolean,
        required: false,
        default: true,
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
        const targetModes = MAPPING_TARGETS[target].modes;

        if(targetModes && targetModes.indexOf(this.elementsType) < 0) {
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

      let hasRuleError = false;
      for(var rule of this.rules) {
        rule.error = null;
        rule.warn = null;
        if(hasRuleError) {
          rule.warn = _l("Skipped due to previous errors.");
          continue;
        }
        var ruleType = rule.type;
        const res = Rules[ruleType].apply(rule, data, sources);
        if(res.error) {
          hasRuleError = true;
          rule.error = res.error;
          continue;
        }
        if(res.warn) {
          rule.warn = res.warn;
        }
        data = res.data || data;
        sources = res.sources || sources;
      }
      return {data, sources};
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
      let identifierColumns = []
      if(this.mappingAsDict.list_identifiers) {
          identifierColumns = this.mappingAsDict.list_identifiers.columns;
      }
      let collectionType = identifierColumns.map(col => "list").join(":");
      if(this.mappingAsDict.paired_identifier) {
          collectionType += ":paired";
      }
      return collectionType;
    },
    validInput() {
        let valid = this.collectionName.length > 0;
        const mappingAsDict = this.mappingAsDict;
        if(mappingAsDict.ftp_path && mappingAsDict.url) {
          valid = false;
        }
        for(var rule of this.rules) {
          if(rule.error) {
            valid = false;
          }
        }
        // raw tabular variant can build stand-alone datasets without identifier
        // columns for the collection builder for existing datasets cannot do this.
        if(this.elementsType == "datasets" && this.identifierColumns().length == 0) {
            valid = false;
        }
        return valid;
    }
  },
  methods: {
    l(str) {  // _l conflicts private methods of Vue internals, expose as l instead
        return _l(str);
    },
    cancel() {
        this.oncancel();
    },
    mappingTargets() {
      return MAPPING_TARGETS;
    },
    resetRules() {
      this.rules.splice(0, this.rules.length);
      this.mapping.splice(0, this.mapping.length);
      this.state = 'build';
      this.errorMessage = '';
      this.collectionName = '';
    },
    addNewRule(ruleType) {
      Rules[ruleType].init(this);
      this.displayRuleType = ruleType;
      this.activeRule = null;
    },
    handleRuleSave(ruleType) {
      const rule = this.activeRule;
      if(rule) {
        Rules[ruleType].save(this, rule);
      } else {
        const rule = {"type": ruleType};
        Rules[ruleType].save(this, rule);
        this.rules.push(rule);
      }
    },
    handleColumnMapping() {

    },
    addIdentifier(identifier) {
      this.mapping.push({"type": identifier, "columns": [0]})
    },
    editRule(rule) {
       const ruleType = rule.type;
       this.activeRule = rule;
       Rules[ruleType].init(this, rule);
       this.displayRuleType = ruleType;
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
            const historyId = Galaxy.currHistoryPanel.model.id;
            let elements, targets;
            if(collectionType) {
                elements = this.creationElementsForFetch();                
                targets = [{
                    "destination": {"type": "hdca"},
                    "elements": elements,
                    "collection_type": collectionType,
                    "name": name,
                }];
            } else {
                elements = this.creationDatasetsForFetch();                
                targets = [{
                    "destination": {"type": "hdas"},
                    "elements": elements,
                    "name": name,
                }];
            }

            axios
                .post(`${Galaxy.root}api/tools/fetch`, {
                    "history_id": historyId,
                    "targets": targets,
                })
                .then(this.waitOnJob)
                .catch(this.renderFetchError);
        }
    },
    identifierColumns() {
        const mappingAsDict = this.mappingAsDict;
        let identifierColumns = []
        if(mappingAsDict.list_identifiers) {
            identifierColumns = mappingAsDict.list_identifiers.columns.slice();        
        }
        if(this.mappingAsDict.paired_identifier) {
            identifierColumns.push(this.mappingAsDict.paired_identifier.columns[0]);
        }
        return identifierColumns;
    },
    buildRequestElements(createDatasetDescription, createSubcollectionDescription, subElementProp) {
        const data = this.hotData["data"];
        const identifierColumns = this.identifierColumns();
        if(identifierColumns.length < 1) {
          console.log("Error but this shouldn't have happened, create button should have been disabled.");
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
                            this.state = 'error';
                            this.errorMessage = 'Unknown indicator of paired status encountered - only values of F, R, 1, 2, R1, R2, forward, or reverse are allowed.';
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
    creationElementsForFetch() { // fetch elements for HDCA
        const data = this.hotData["data"];
        const mappingAsDict = this.mappingAsDict;

        return this.buildRequestElements(
            (dataIndex, identifier) => {
                const res = this._datasetFor(dataIndex, data, mappingAsDict);
                res["name"] = identifier;
                return res;
            },
            (identifier) => {
                return {"name": identifier};
            },
            "elements",
        );
    },
    creationDatasetsForFetch() { // fetch elements for HDAs if not collection information specified.
        const data = this.hotData["data"];
        const mappingAsDict = this.mappingAsDict;

        const datasets = [];

        for(let dataIndex in data) {
            const rowData = data[dataIndex];
            const res = this._datasetFor(dataIndex, data, mappingAsDict);
            datasets.push(res);
        }

        return datasets;
    },    
    _datasetFor(dataIndex, data, mappingAsDict) {
        const res = {};
        if(mappingAsDict.url) {
            const urlColumn = mappingAsDict.url.columns[0];
            const url = data[dataIndex][urlColumn];
            res["url"] = url;
            res["src"] = "url";
        } else {
            const ftpPathColumn = mappingAsDict.ftp_path.columns[0];
            const ftpPath = data[dataIndex][ftpPathColumn];
            res["ftp_path"] = ftpPath;
            res["src"] = "ftp_path";
        }
        if(mappingAsDict.dbkey) {
            const dbkeyColumn = mappingAsDict.dbkey.columns[0];
            const dbkey = data[dataIndex][dbkeyColumn];
            res["dbkey"] = dbkey;
        } else if(this.genome) {
            res["dbkey"] = this.genome;
        }
        if(mappingAsDict.file_type) {
            const fileTypeColumn = mappingAsDict.file_type.columns[0];
            const fileType = data[dataIndex][fileTypeColumn];
            res["ext"] = file_type;
        } else if(this.extension) {
            res["ext"] = this.extension;
        }
        return res;
    },
  },
  created() {
      UploadUtils.getUploadDatatypes((extensions) => {this.extensions = extensions; this.extension = "auto"}, false, UploadUtils.AUTO_EXTENSION);
      UploadUtils.getUploadGenomes((genomes) => {this.genomes = genomes; this.genome = "?";}, "?");
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
    Select2,
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
  .rules-container {
    border: 1px dashed #ccc;
    padding: 5px;
  }
  .rules-container .title {
    font-weight: bold;
  }
  .rule-option {
    padding-left: 20px;
  }
  .rules {
    height: 335px;
  }
  .rules li {
    list-style-type: circle;
    list-style-position: inside;
    padding: 5px;
    padding-top: 0px;
    padding-bottom: 0px;
  }
  .rules .rule-error {
    display: block;
    margin-left: 10px;
    font-style: italic;
    color: red;
  }
  .rules .rule-warning {
    display: block;
    margin-left: 10px;
    font-style: italic;
    color: #e28809;
  }
  .rules-buttons {

  }
</style>
