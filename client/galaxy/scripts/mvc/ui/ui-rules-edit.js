import axios from "axios";
import _l from "utils/localization";
import Utils from "utils/utils";
import Ui from "mvc/ui/ui-misc";
import ListCollectionCreator from "mvc/collection/list-collection-creator";

/**
 * Bridge rule based builder and the tool form.
 */
var View = Backbone.View.extend({
    // initialize
    initialize: function(options) {
        // link this
        this.options = options;
        this.target = options.target;
        const view = this;

        // create insert new list element button
        this.browse_button = new Ui.ButtonIcon({
            title: _l("Edit"),
            icon: "fa fa-edit",
            tooltip: _l("Edit Rules"),
            onclick: () => {
                const url = `${Galaxy.root}api/dataset_collections/${view.target.id}?instance_type=history`;
                axios
                    .get(url)
                    .then(view._showCollection)
                    .catch(view._renderFetchError);
            }
        });

        // create elements
        this.setElement(this._template(options));
        this.$(".ui-rules-edit-button").append(this.browse_button.$el);
    },

    _showCollection: function(response) {
        const data = response.data;
        const elements = data;
        const elementsType = "collection_contents";
        const importType = "collection";
        const options = {

        }
        ListCollectionCreator.ruleBasedCollectionCreatorModal(
            elements,
            elementsType,
            importType,
            options
        ).done(() => {
        });
    },

    _renderFetchError: function(e) {
        console.log(e);
        console.log("problem fetching collection");
    },

    /** Main Template */
    _template: function(options) {
        return (`
            <div class="ui-rules-edit">
                <span class="ui-rules-edit-button" />
            </div>
        `);
    },

    /** Return/Set currently selected genomespace filename */
    value: function(new_value) {
        // check if new_value is defined
        if (new_value !== undefined) {
            this._setValue(new_value);
        } else {
            return this._getValue();
        }
    },

    // update
    refreshDefinition: function(input_def) {
        self.target = input_def.target;
        // refresh
        this._refresh();
    },

    // refresh
    _refresh: function() {
    },

    // get value
    _getValue: function() {
        return this._value;
    },

    // set value
    _setValue: function(new_value) {
        if(new_value) {
            this._value = new_value;
        }
        this.options.onchange && this.options.onchange(new_value);
    }
});

export default {
    View: View
};
