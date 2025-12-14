<script setup lang="ts">
import { computed } from "vue"
import type { components } from "@/schema"

type LogMessageResponse = components["schemas"]["LogMessageResponse"]

interface Props {
    messages?: LogMessageResponse[] | null
}

const props = defineProps<Props>()

const messageList = computed(() => props.messages ?? [])

const hasErrors = computed(() => messageList.value.some((m) => m.level === "error"))

const hasWarnings = computed(() => messageList.value.some((m) => m.level === "warning"))

const levelColor = (level: string): string => {
    switch (level) {
        case "debug":
            return "grey"
        case "info":
            return "primary"
        case "warning":
            return "warning"
        case "error":
            return "negative"
        default:
            return "grey"
    }
}
</script>

<template>
    <div :class="{ 'has-errors': hasErrors, 'has-warnings': hasWarnings && !hasErrors }">
        <div v-if="messageList.length === 0" class="text-grey q-pa-md">No log messages</div>
        <div v-else>
            <div class="text-caption q-mb-sm">{{ messageList.length }} messages</div>
            <q-list dense bordered separator class="rounded-borders">
                <q-item v-for="(msg, idx) in messageList" :key="idx" class="log-message">
                    <q-item-section side>
                        <q-badge
                            :data-level="msg.level"
                            :color="levelColor(msg.level)"
                            :label="msg.level.toUpperCase()"
                        />
                    </q-item-section>
                    <q-item-section class="log-message-text">
                        {{ msg.message }}
                    </q-item-section>
                </q-item>
            </q-list>
        </div>
    </div>
</template>

<style scoped>
.log-message-text {
    font-family: monospace;
    font-size: 0.85rem;
    word-break: break-word;
}
</style>
