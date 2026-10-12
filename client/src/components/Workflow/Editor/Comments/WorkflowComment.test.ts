import { createTestingPinia } from "@pinia/testing";
import { emittedArg, nth, suppressErrorForCustomIcons } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount, shallowMount } from "@vue/test-utils";
import type { UseElementBoundingReturn } from "@vueuse/core";
import { disposePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { nextTick, reactive, ref } from "vue";

import { sanitizeHtml } from "@/directives/sanitizeHtml";
import type { LazyUndoRedoAction, UndoRedoAction } from "@/stores/undoRedoStore";
import type { TextWorkflowComment, WorkflowComment as WorkflowCommentModel } from "@/stores/workflowEditorCommentStore";

import MarkdownComment from "./MarkdownComment.vue";
import TextComment from "./TextComment.vue";
import WorkflowComment from "./WorkflowComment.vue";

const changeData = vi.fn();
const changeSize = vi.fn();
const changePosition = vi.fn();
const changeColor = vi.fn();
const deleteComment = vi.fn();

let pinia: ReturnType<typeof createTestingPinia>;
const sanitizeMock = vi.mocked(sanitizeHtml);
const originalSanitize = sanitizeMock.getMockImplementation();

afterEach(() => {
    sanitizeMock.mockReset();
    if (originalSanitize) {
        sanitizeMock.mockImplementation(originalSanitize);
    }
    vi.restoreAllMocks();
});
enableAutoUnmount(afterEach);
afterEach(async () => {
    // Let the mounted draggable's current resize/frame callbacks finish before unmount.
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
});

vi.mock("@/composables/workflowStores", () => ({
    useWorkflowStores: () => ({
        commentStore: {
            changeData,
            changeSize,
            changePosition,
            changeColor,
            deleteComment,
            isJustCreated: () => false,
            getCommentMultiSelected: () => false,
        },
        toolbarStore: reactive({
            snapActive: false,
            snapDistance: 12,
        }),
        undoRedoStore: {
            applyAction: (action: UndoRedoAction) => action.run(),
            applyLazyAction: (action: LazyUndoRedoAction) => {
                action.queued();
                action.run();
            },
        },
    }),
}));

// Mock transform injection that Draggable components expect
const mockTransform = ref({ x: 0, y: 0, k: 1 });
// These original fixtures omit bounding refs/update; no geometry interaction is exercised.

function commentMountOptions() {
    return { plugins: [pinia], provide: { transform: mockTransform } };
}

function getStyleProperty(element: Element, property: string) {
    const style = element.getAttribute("style") ?? "";

    const startIndex = style.indexOf(`${property}:`) + property.length + 1;
    const endIndex = style.indexOf(";", startIndex);

    return style.substring(startIndex, endIndex).trim();
}

describe("WorkflowComment", () => {
    const comment: Pick<TextWorkflowComment, "id" | "type" | "color" | "position" | "size"> & { data: object } = {
        id: 0,
        type: "text",
        color: "none",
        position: [0, 0],
        size: [100, 100],
        data: {},
    };

    beforeEach(() => {
        pinia = createTestingPinia({ createSpy: vi.fn });
        const ownedPinia = pinia;
        setActivePinia(pinia);
        onTestFinished(() => {
            disposePinia(ownedPinia);
            setActivePinia(undefined);
        });
        vi.clearAllMocks();
        suppressErrorForCustomIcons();
    });

    it("changes position and size reactively", async () => {
        const wrapper = shallowMount(WorkflowComment, {
            props: {
                // The original position-only fixture deliberately omits text/size data.
                comment: { ...comment } as TextWorkflowComment,
                scale: 1,
                rootOffset: {} as UseElementBoundingReturn,
            },
            global: commentMountOptions(),
        });

        const position = () => ({
            x: parseInt(getStyleProperty(wrapper.element, "--position-left")),
            y: parseInt(getStyleProperty(wrapper.element, "--position-top")),
        });

        const size = () => ({
            w: parseInt(getStyleProperty(wrapper.element, "--width")),
            h: parseInt(getStyleProperty(wrapper.element, "--height")),
        });

        expect(position()).toEqual({ x: 0, y: 0 });
        expect(size()).toEqual({ w: 100, h: 100 });

        await wrapper.setProps({
            comment: { ...comment, position: [123, 456] } as TextWorkflowComment,
            scale: 1,
            rootOffset: {} as UseElementBoundingReturn,
        });

        expect(position()).toEqual({ x: 123, y: 456 });
        expect(size()).toEqual({ w: 100, h: 100 });

        await wrapper.setProps({
            comment: { ...comment, size: [2000, 3000] } as TextWorkflowComment,
            scale: 1,
            rootOffset: {} as UseElementBoundingReturn,
        });

        expect(position()).toEqual({ x: 0, y: 0 });
        expect(size()).toEqual({ w: 2000, h: 3000 });
    });

    it("displays the correct comment type", async () => {
        const wrapper = mount(WorkflowComment, {
            props: {
                comment: { ...comment, type: "text", data: { size: 1, text: "HelloWorld" } },
                scale: 1,
                rootOffset: {} as UseElementBoundingReturn,
            },
            global: commentMountOptions(),
        });

        expect(wrapper.getComponent(TextComment).isVisible()).toBe(true);

        await wrapper.setProps({
            comment: { ...comment, type: "markdown", data: { text: "# Hello World" } },
            scale: 1,
            rootOffset: {} as UseElementBoundingReturn,
        });

        await nextTick();
        expect(wrapper.getComponent(MarkdownComment).isVisible()).toBe(true);
    });

    it("forwards events to the comment store", () => {
        const testComment: TextWorkflowComment = { ...comment, id: 123, data: { size: 1, text: "HelloWorld" } };

        const wrapper = mount(WorkflowComment, {
            props: {
                comment: testComment,
                scale: 1,
                rootOffset: {} as UseElementBoundingReturn,
            },
            global: commentMountOptions(),
        });

        const textComment = wrapper.getComponent(TextComment);

        textComment.vm.$emit("change", "abc");
        expect(changeData).toBeCalledWith(123, "abc");

        textComment.vm.$emit("resize", [1000, 1000]);
        expect(changeSize).toBeCalledWith(123, [1000, 1000]);

        textComment.vm.$emit("move", [20, 20]);
        expect(changePosition).toBeCalledWith(123, [20, 20]);

        textComment.vm.$emit("set-color", "pink");
        expect(changeColor).toBeCalledWith(123, "pink");

        textComment.vm.$emit("remove");
        expect(deleteComment).toBeCalledWith(123);
    });

    it("forwards pan events", () => {
        const wrapper = mount(WorkflowComment, {
            props: {
                comment: { ...comment, id: 123, data: { size: 1, text: "HelloWorld" } },
                scale: 1,
                rootOffset: {} as UseElementBoundingReturn,
            },
            global: commentMountOptions(),
        });

        const textComment = wrapper.getComponent(TextComment);

        textComment.vm.$emit("pan-by", { x: 50, y: 50 });
        expect(emittedArg(wrapper, "pan-by")).toEqual({ x: 50, y: 50 });
    });

    describe("rendering comment text", () => {
        function mountComment(renderedComment: WorkflowCommentModel) {
            vi.mocked(sanitizeHtml).mockClear();
            vi.mocked(sanitizeHtml).mockImplementation((html) => `<span class="sanitized">${html}</span>`);
            return mount(WorkflowComment, {
                props: { comment: renderedComment, scale: 1, rootOffset: {} as UseElementBoundingReturn },
                global: commentMountOptions(),
            });
        }

        it("renders text comments through v-sanitize-html", () => {
            const wrapper = mountComment({
                ...comment,
                type: "text",
                data: { size: 1, text: "line one<br>line <em>two</em>" },
            });
            // escapeAndSanitize runs DOMPurify first, whose happy-dom output isn't meaningful
            expect(sanitizeHtml).toHaveBeenCalledWith(expect.any(String), "default");
            expect(wrapper.find(".sanitized").exists()).toBe(true);
        });

        it("renders frame titles through v-sanitize-html", () => {
            const wrapper = mountComment({ ...comment, type: "frame", data: { title: "Frame <em>title</em>" } });
            expect(sanitizeHtml).toHaveBeenCalledWith(expect.any(String), "default");
            expect(wrapper.find(".sanitized").exists()).toBe(true);
        });

        it("renders markdown comments with the links profile", () => {
            const wrapper = mountComment({
                ...comment,
                type: "markdown",
                data: { text: "[docs](https://galaxyproject.org) <b>raw</b>" },
            });
            const [html, profile] = nth(sanitizeMock.mock.calls, 0);
            expect(profile).toBe("links");
            expect(html).toContain('target="_blank"');
            // markdown-it escapes raw HTML in the source before it reaches the sanitizer
            expect(html).toContain("&lt;b&gt;raw&lt;/b&gt;");
            expect(wrapper.find(".rendered-markdown .sanitized").exists()).toBe(true);
        });
    });
});
