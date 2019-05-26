<template>
    <span>
        <div class="unified-panel-header" unselectable="on">
            <div class="unified-panel-header-inner">
                Page Editor: {{ title }}
                <a id="save-button" class="btn btn-secondary fa fa-save float-right" @click="saveContent"></a>
            </div>
        </div>
        <page-editor-html :page-id="pageId" :content="content" v-if="contentFormat == 'html'" ref="contentEditor" />
        <page-editor-markdown
            :page-id="pageId"
            :initial-content="content"
            v-if="contentFormat == 'markdown'"
            ref="contentEditor"
        />
    </span>
</template>

<script>
import PageEditorHtml from "./PageEditorHtml";
import PageEditorMarkdown from "./PageEditorMarkdown";

export default {
    props: {
        pageId: {
            required: true,
            type: String
        },
        content: {
            type: String
        },
        contentFormat: {
            type: String,
            default: "html"
        },
        title: {
            type: String
        }
    },
    methods: {
        saveContent: function() {
            this.$refs.contentEditor.saveContent();
        }
    },
    components: {
        PageEditorHtml,
        PageEditorMarkdown
    }
};
</script>
