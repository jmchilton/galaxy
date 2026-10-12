import { createTestingPinia } from "@pinia/testing";
import {
    dispatchEvent,
    emittedArg,
    getLocalVue,
    mockUnprivilegedToolsRequest,
    withPlugins,
} from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h, ref } from "vue";

import { useServerMock } from "@/api/client/__mocks__";
import { useActivityStore } from "@/stores/activityStore";
import { useEventStore } from "@/stores/eventStore";

import ActivityBar from "./ActivityBar.vue";

const mockConfig = ref({});

vi.mock("@/composables/config", () => ({
    useConfig: vi.fn(() => ({
        config: mockConfig,
        isConfigLoaded: true,
    })),
}));

vi.mock("vue-router", () => ({
    useRoute: vi.fn(() => ({ path: "/", params: {}, query: {} })),
    useRouter: vi.fn(() => ({ push: vi.fn() })),
}));

const { server, http } = useServerMock();

const localVue = getLocalVue();

// shallowMount stubs draggable without rendering its scoped item slot, so render it ourselves.
const draggableStub = {
    compatConfig: { MODE: 3 },
    props: ["modelValue"],
    render() {
        return h(
            "div",
            (this.modelValue || []).flatMap((element, index) => this.$slots.item({ element, index })),
        );
    },
};

function testActivity(id, newOptions = {}) {
    const defaultOptions = {
        anonymous: true,
        id: `test-${id}`,
        description: "test-description",
        icon: "test-icon",
        mutable: true,
        optional: false,
        title: "test-title",
        to: "test-to",
        tooltip: "test-tooltip",
        visible: true,
    };
    return { ...defaultOptions, ...newOptions };
}

describe("ActivityBar", () => {
    let activityStore;
    let eventStore;
    let wrapper;
    let ownedPinia;

    function createOwnedPinia() {
        const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
        ownedPinia.push(pinia);
        // Scoped activity stores resolve through active Pinia rather than accepting an instance.
        setActivePinia(pinia);
        return pinia;
    }

    beforeEach(async () => {
        ownedPinia = [];
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        mockConfig.value = {};
        const pinia = createOwnedPinia();
        activityStore = useActivityStore("default");
        eventStore = useEventStore(pinia);
        mockUnprivilegedToolsRequest(server, http);
        server.use(
            http.get("/api/configuration", ({ response }) => {
                return response(200).json({});
            }),
        );
        wrapper = shallowMount(ActivityBar, {
            global: { ...withPlugins(localVue, pinia), stubs: { draggable: draggableStub } },
        });
    });

    afterEach(() => {
        ownedPinia.forEach(disposePinia);
        vi.clearAllTimers();
        vi.useRealTimers();
        vi.clearAllMocks();
        mockConfig.value = {};
    });
    enableAutoUnmount(afterEach);
    afterEach(async () => {
        // Complete the store's existing 10ms synchronization while its wrappers are still mounted.
        await flushPromises();
        await vi.advanceTimersByTimeAsync(10);
        await flushPromises();
    });

    it("renders each configured activity", async () => {
        activityStore.setAll([testActivity("1"), testActivity("2"), testActivity("3")]);
        await wrapper.vm.$nextTick();
        const items = wrapper.findAll("[title='test-title']");
        expect(items.length).toBe(3);
    });

    it("emits the workflow run destination when a workflow is dragged onto the bar", async () => {
        activityStore.setAll([testActivity("1"), testActivity("2"), testActivity("3")]);
        eventStore.setDragData({
            id: "workflow-id",
            description: "workflow-description",
            model_class: "StoredWorkflow",
            name: "workflow-name",
        });
        const bar = wrapper.get("[data-description='activity bar']");
        dispatchEvent(bar, "dragenter");
        const emittedEvent = emittedArg(wrapper, "dragstart");
        expect(emittedEvent.to).toBe("/workflows/run?id=workflow-id");
    });

    describe("interactivetools visibility", () => {
        async function mountWithInteractiveToolsConfig(enabled, activityBarId) {
            mockConfig.value = { interactivetools_enable: enabled };
            const pinia = createOwnedPinia();
            const testStore = useActivityStore(activityBarId);
            testStore.setAll([
                testActivity("1"),
                testActivity("interactivetools", { id: "interactivetools", title: "Interactive Tools" }),
                testActivity("3"),
            ]);
            mockUnprivilegedToolsRequest(server, http);
            const testWrapper = shallowMount(ActivityBar, {
                global: { ...withPlugins(localVue, pinia), stubs: { draggable: draggableStub } },
                props: { activityBarId },
            });
            await testWrapper.vm.$nextTick();
            return testWrapper;
        }

        it("hides interactivetools activity when interactivetools_enable is false", async () => {
            const testWrapper = await mountWithInteractiveToolsConfig(false, "it-test-hide");
            expect(testWrapper.findAll("[id='interactivetools']").length).toBe(0);
        });

        it("shows interactivetools activity when interactivetools_enable is true", async () => {
            const testWrapper = await mountWithInteractiveToolsConfig(true, "it-test-show");
            expect(testWrapper.findAll("[id='interactivetools']").length).toBe(1);
        });

        it("keeps a hidden interactivetools activity when the visible ones are reordered", async () => {
            const testWrapper = await mountWithInteractiveToolsConfig(false, "it-test-reorder");
            const bar = testWrapper.getComponent(draggableStub);
            const visible = bar.props("modelValue");
            expect(visible.map((activity) => activity.id)).toEqual(["test-1", "test-3"]);
            bar.vm.$emit("update:modelValue", [...visible].reverse());
            await testWrapper.vm.$nextTick();
            const stored = useActivityStore("it-test-reorder").activities.map((activity) => activity.id);
            expect(stored).toEqual(["test-3", "test-1", "interactivetools"]);
        });
    });
});
