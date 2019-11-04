<template>
    <div v-if="!codemirror" style="display: flex; flex: 1; flex-direction: column">
        <ul class="galaxymark-toolbar" ref="menu">
            <li><a href="#" class="fa-2x fa fa-file" @click="selectData"></a></li>
            <li><a href="#" class="fa-2x fa fa-folder" @click="selectDataCollection"></a></li>
            <li><a href="#" class="fa-2x fa fa-sitemap fa-rotate-270" @click="selectWorkflow"></a></li>
        </ul>
        <textarea class="markdown-textarea" id="workflow-report-editor" v-model="input" @input="update" ref="editor">
        </textarea>
    </div>
    <div style="min-height: 100px; width: 100%;" v-else>
        <codemirror v-model="input" ref="editor" style="height: 100%">
        </codemirror>
        <ul class="galaxymark-toolbar" ref="menu">
            <li><a href="#" class="fa-2x fa fa-folder"></a></li>
            <li><a href="#" class="fa-2x fa fa-file"></a></li>
            <li><a href="#" class="fa-2x fa fa-folder"></a></li>
        </ul>
    </div>
</template>

<script>
import _ from "underscore";
import 'codemirror/lib/codemirror.css'
import 'codemirror/mode/markdown/markdown'
import Vue from 'vue'
import VueCodemirror from 'vue-codemirror'
import { getGalaxyInstance } from "app/index";
import { dialog, datasetCollectionDialog, workflowDialog } from "utils/data";

const FENCE = '```';
const USE_CODE_MIRROR = false;

Vue.use(VueCodemirror, {
    options: { theme: 'galaxymark'},
});

// https://stackoverflow.com/questions/11076975/insert-text-into-textarea-at-cursor-position-javascript
function _insertAtCursor(myField, myValue) {
    //IE support
    if (document.selection) {
        myField.focus();
        sel = document.selection.createRange();
        sel.text = myValue;
    }
    //MOZILLA and others
    else if (myField.selectionStart || myField.selectionStart == '0') {
        var startPos = myField.selectionStart;
        var endPos = myField.selectionEnd;
        myField.value = myField.value.substring(0, startPos)
            + myValue
            + myField.value.substring(endPos, myField.value.length);
    } else {
        myField.value += myValue;
    }
}


export default {
    props: {
        initialMarkdown: {
            required: true,
            type: String
        },
        onupdate: {
            type: Function
        },
        codemirror: {
            type: Boolean,
            default: USE_CODE_MIRROR
        }
    },
    data: function() {
        return {
            input: this.initialMarkdown
        };
    },
    mounted: function() {
        if( USE_CODE_MIRROR ) {
            const toolbar = this.$refs["menu"];
            const cminstance = this.$refs["editor"].cminstance.getWrapperElement();
            cminstance.insertBefore(toolbar, cminstance.firstChild);
        }
    },
    methods: {
        update: _.debounce(function(e) {
            if (this.onupdate) {
                this.onupdate(this.input);
            }
        }, 300),
        insertMarkdown(markdown) {
            const editorTextarea = this.$refs["editor"];
            _insertAtCursor(editorTextarea, markdown);
            Vue.nextTick(() => {
                const event = new Event('input')
                editorTextarea.dispatchEvent(event);
            });
        },
        insertGalaxyMarkdownBlock(block) {
            this.insertMarkdown(`${FENCE}galaxy\n${block}\n${FENCE}\n`);
        },
        selectData() {
            dialog(
                response => {
                    const datasetId = response.id;
                    this.insertGalaxyMarkdownBlock(`history_dataset_display(history_dataset_id=${datasetId})`);
                }, {
                    multiple: false,
                    format: null
                }
            );
        },
        selectDataCollection() {
            datasetCollectionDialog(
                response => {
                    console.log(response);
                    this.insertGalaxyMarkdownBlock(`history_dataset_collection_display(history_dataset_collection_id=${response})`);
                }, {}
            );
        },
        selectWorkflow() {
            workflowDialog(
                response => {
                    console.log(response);
                    this.insertGalaxyMarkdownBlock(`workflow_display(workflow_id=${response.id})`);
                }, {}
            );
        }
    }
};
</script>

<style lang="scss">
.galaxymark-toolbar {
	background: #fff;
	border-bottom: 1px solid rgba(0,0,0,0.1);
	display: block;
	width: 100%;
	margin-top: 0;
	margin-bottom: 0;
	padding-left: 0;
	padding-right: 0;
}

.galaxymark-toolbar li {
    display: inline-block;
    position: relative;
    z-index: 1;
}

.galaxymark-toolbar li a {
    color: #888;
    cursor: pointer;
    display: block;
    font-size: 16px;
    height: 40px;
    line-height: 40px;
    text-align: center;
    transition: color .2s linear;
    width: 40px;
}

.galaxymark-toolbar li a:hover {
    color: #000;
    text-decoration: none;
}

.markdown-text {
    font: 16px/1.7 Menlo, Consolas, Monaco, 'Andale Mono', monospace;
}

.markdown-textarea {
    border: none;
    border-right: 1px solid #ccc;
    border-left: 1px solid #ccc;
    resize: none;
    outline: none;
    background-color: #f6f6f6;
    @extend .markdown-text;
    padding: 20px;
    width: 100%;
    flex: 1;
}

/* Style for codemirror. */
.cm-s-galaxymark {
    background-color: #f6f6f6;
    @extend .markdown-text;
	box-sizing: border-box;
	height: 100%;
	margin: auto;
	position: relative;
	z-index: 0;

	.CodeMirror-scroll {
		height: auto !important;
		overflow: visible !important;
		padding: 30px 4%;
		box-sizing: border-box;
	}

	&.CodeMirror-fullscreen .CodeMirror-scroll {
		height: 100% !important;
		overflow: scroll !important;
	}

	pre.CodeMirror-placeholder { color: #999; }
}

</style>
