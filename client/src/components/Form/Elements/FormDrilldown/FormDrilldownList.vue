<script setup lang="ts">
import type { Option } from "./utilities";

import FormDrilldownOption from "./FormDrilldownOption.vue";

defineProps<{
    currentValue: string[];
    multiple: boolean;
    showIcons?: boolean;
    options: Array<Option>;
}>();
</script>

<template>
    <div class="ui-drilldown">
        <div v-for="option in options" :key="option.name" class="descendant-lines">
            <FormDrilldownOption
                :show-icons="showIcons"
                :current-value="currentValue"
                :multiple="multiple"
                :option="option" />
        </div>
    </div>
</template>

<style lang="scss" scoped>
@import "@/style/scss/theme/blue.scss";
.ui-drilldown {
    $ui-drilldown-border: 0.5px solid $gray-500;

    /* selector: all except first nested drilldown */
    & > * .descendant-lines {
        border-left: $ui-drilldown-border;
    }
}
</style>
