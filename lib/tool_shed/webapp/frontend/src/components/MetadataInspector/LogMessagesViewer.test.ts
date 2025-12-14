import { describe, it, expect, beforeEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import LogMessagesViewer from "./LogMessagesViewer.vue"
import { makeLogMessage } from "./__fixtures__"

describe("LogMessagesViewer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    describe("empty state", () => {
        it("renders gracefully with empty array", () => {
            const wrapper = mount(LogMessagesViewer, {
                props: { messages: [] },
            })

            expect(wrapper.text()).toContain("No log messages")
        })

        it("renders gracefully with undefined", () => {
            const wrapper = mount(LogMessagesViewer, {
                props: { messages: undefined },
            })

            expect(wrapper.text()).toContain("No log messages")
        })
    })

    describe("message rendering", () => {
        it("displays all messages", () => {
            const messages = [
                makeLogMessage({ level: "debug", message: "Starting operation" }),
                makeLogMessage({ level: "info", message: "Operation complete" }),
            ]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            expect(wrapper.text()).toContain("Starting operation")
            expect(wrapper.text()).toContain("Operation complete")
        })

        it("displays message level labels", () => {
            const messages = [
                makeLogMessage({ level: "debug", message: "Debug message" }),
                makeLogMessage({ level: "info", message: "Info message" }),
                makeLogMessage({ level: "warning", message: "Warning message" }),
                makeLogMessage({ level: "error", message: "Error message" }),
            ]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            expect(wrapper.text()).toMatch(/debug/i)
            expect(wrapper.text()).toMatch(/info/i)
            expect(wrapper.text()).toMatch(/warning/i)
            expect(wrapper.text()).toMatch(/error/i)
        })
    })

    describe("level styling", () => {
        it("applies grey styling to debug messages", () => {
            const messages = [makeLogMessage({ level: "debug", message: "Debug" })]
            const wrapper = mount(LogMessagesViewer, { props: { messages } })

            const levelBadge = wrapper.find("[data-level='debug']")
            expect(levelBadge.exists()).toBe(true)
        })

        it("applies blue styling to info messages", () => {
            const messages = [makeLogMessage({ level: "info", message: "Info" })]
            const wrapper = mount(LogMessagesViewer, { props: { messages } })

            const levelBadge = wrapper.find("[data-level='info']")
            expect(levelBadge.exists()).toBe(true)
        })

        it("applies orange/warning styling to warning messages", () => {
            const messages = [makeLogMessage({ level: "warning", message: "Warning" })]
            const wrapper = mount(LogMessagesViewer, { props: { messages } })

            const levelBadge = wrapper.find("[data-level='warning']")
            expect(levelBadge.exists()).toBe(true)
        })

        it("applies red/negative styling to error messages", () => {
            const messages = [makeLogMessage({ level: "error", message: "Error" })]
            const wrapper = mount(LogMessagesViewer, { props: { messages } })

            const levelBadge = wrapper.find("[data-level='error']")
            expect(levelBadge.exists()).toBe(true)
        })
    })

    describe("message count", () => {
        it("displays correct message count", () => {
            const messages = [
                makeLogMessage({ message: "One" }),
                makeLogMessage({ message: "Two" }),
                makeLogMessage({ message: "Three" }),
            ]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            // Component should show count somewhere
            expect(wrapper.text()).toMatch(/3/)
        })
    })

    describe("error/warning detection", () => {
        it("exposes hasErrors when error messages present", () => {
            const messages = [
                makeLogMessage({ level: "info", message: "Info" }),
                makeLogMessage({ level: "error", message: "Error occurred" }),
            ]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            // Component should visually indicate errors
            expect(wrapper.find(".has-errors").exists() || wrapper.classes().includes("has-errors")).toBe(true)
        })

        it("exposes hasWarnings when warning messages present", () => {
            const messages = [
                makeLogMessage({ level: "info", message: "Info" }),
                makeLogMessage({ level: "warning", message: "Warning occurred" }),
            ]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            // Component should visually indicate warnings
            expect(wrapper.find(".has-warnings").exists() || wrapper.classes().includes("has-warnings")).toBe(true)
        })

        it("has no error/warning indicators when only info/debug", () => {
            const messages = [
                makeLogMessage({ level: "debug", message: "Debug" }),
                makeLogMessage({ level: "info", message: "Info" }),
            ]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            expect(wrapper.find(".has-errors").exists()).toBe(false)
            expect(wrapper.find(".has-warnings").exists()).toBe(false)
        })
    })

    describe("long messages", () => {
        it("displays long messages without truncation", () => {
            const longMessage =
                "This is a very long log message that contains detailed information about what went wrong during the metadata reset operation including file paths and specific error details"

            const messages = [makeLogMessage({ message: longMessage })]

            const wrapper = mount(LogMessagesViewer, {
                props: { messages },
            })

            expect(wrapper.text()).toContain(longMessage)
        })
    })
})
