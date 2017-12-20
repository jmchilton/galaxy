import _l from "utils/localization";
import Ui from "mvc/ui/ui-misc";
import Select from "mvc/ui/ui-select";
import axios from "axios";


export default Backbone.View.extend({
    initialize: function(app) {
        this.app = app;
        this.options = app.options;
        this.setElement(this._template());
        this.btnBuild = new Ui.Button({
            id: "btn-build",
            title: _l("Build"),
            onclick: () => {
                this._eventBuild();
            }
        });
        _.each(
            [
                this.btnBuild,
            ],
            button => {
                this.$(".upload-buttons").prepend(button.$el);
            }
        );
        const selectionTypeOptions = [
            {"id": "paste", text: "Paste Tabular Data"},
            {"id": "dataset", text: "Select History Dataset"},
        ]
        this.selectionType = "paste";
        this.selectionTypeView = new Select.View({
            css: "upload-footer-selection",
            container: this.$(".upload-footer-select-type"),
            data: selectionTypeOptions,
            value: this.selectionType,
            onchange: (value) => {
                this.selectionType = value;
                this._renderSelectedType();
            }
        });
        this.selectedDatasetId = null;

        this._renderSelectedType();
    },

    _renderSelectedType() {
        const selectionType = this.selectionType;
        if(selectionType == "dataset") {
            this.selectedDatasetId = null;
            // Render dataset selector...
            this.$(".upload-top-info").text(_l("Select Tabular Dataset from History"));

            const history = parent.Galaxy && parent.Galaxy.currHistoryPanel && parent.Galaxy.currHistoryPanel.model;
            const historyContentModels = history.contents.models;
            const options = [];
            for(let historyContentModel of historyContentModels) {
                const attr = historyContentModel.attributes;
                if(attr.history_content_type !== "dataset") {
                    continue;
                }
                options.push({"id": attr.id, "text": `${attr.hid}: ${_.escape(attr.name)}`});
            }
            this.$(".upload-box").html(
                `<span class="dataset-selector"/>`
            );
            this.selectionTypeView = new Select.View({
                container: this.$(".dataset-selector"),
                data: options,
                onchange: (value) => {
                    this.selectedDatasetId = value;
                }
            });
        } else {
            // Render paste box...
            this.$(".upload-top-info").text(_l("Paste Tabular Data Below"));
            // '<div class="upload-text" style="width: 800px; top: 26px; display: block; height: 100%">' +
            // '</div>'
            this.$(".upload-box").html(`<textarea class="upload-text-content form-control" style="height: 100%"></textarea>`);
        }
    },

    _eventBuild: function() {
        const selectionType = this.selectionType;
        if(selectionType == "dataset") {
            axios
                .get(`${Galaxy.root}api/histories/${Galaxy.currHistoryPanel.model.id}/contents/${this.selectedDatasetId}/display`)
                .then((response) => this._buildSelection(response.data))
                .catch((error) => console.log(error));
        } else {
            const selection = this.$(".upload-text-content").val();
            this._buildSelection(selection);
        }
    },

    _buildSelection: function(selection) {
        Galaxy.currHistoryPanel.buildCollection("rules", selection, true);
        this.app.modal.hide();
    },

    /** Template */
    _template: function() {
        return `
            <div class="upload-view-default">
                <div class="upload-top">
                    <h6 class="upload-top-info"></h6>
                </div>
                <div class="upload-box">
                </div>
                <div class="upload-footer">
                    <span class="upload-footer-title">${_l("Initialize Rules Against")}</span>
                    <span class="upload-footer-select-type"/>
                </div>
                <div class="upload-buttons"/>
                </div>
        `;
    }

});