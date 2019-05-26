<template>
    <div class="width: 100%; height: 100%">
        <nav class="navbar navbar-light bg-light">
            <a class="fa fa-file-o" />
            <a class="fa fa-folder-o" />
            <a class="fa fa-sitemap fa-rotate-270" />
        </nav>
        <markdown-editor :initial-markdown="initialContent" :onupdate="onUpdate" ref="markdownEditor"> </markdown-editor>
    </div>
</template>

<script>
import MarkdownEditor from "components/Markdown/MarkdownEditor";
import { save } from "./util";

export default {
    components: {
        MarkdownEditor
    },
    data: function() {
        return {
            content: ""
        };
    },
    props: {
        pageId: {
            required: true,
            type: String
        },
        initialContent: {
            type: String
        }
    },
    methods: {
        onUpdate: function(content) {
            this.content = content;
        },
        saveContent: function() {
            save(this.pageId, this.content);
        }
    }
};
</script>
