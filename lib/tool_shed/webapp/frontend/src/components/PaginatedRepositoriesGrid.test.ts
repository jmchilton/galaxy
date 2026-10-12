import { afterEach, beforeEach, describe, it, expect, vi } from "vitest"
import { enableAutoUnmount, mount, flushPromises } from "@vue/test-utils"
import PaginatedRepositoriesGrid from "./PaginatedRepositoriesGrid.vue"
import {
    emptyQueryResults,
    type OnRequest,
    type Query,
    type QueryResults,
    type RepositoryGridItem,
} from "./RepositoriesGridInterface"

import { deferred } from "../../../../../../client/tests/vitest/deferred"

// RepositoryExplore (rendered in each row) pulls in @/router,
// which calls createRouter() at import time -- keep the real exports around
// that and only override the composables this component actually calls.
const route = vi.hoisted(() => ({ query: {} as Record<string, string> }))
vi.mock("vue-router", async (importOriginal) => {
    const actual = await importOriginal<typeof import("vue-router")>()
    return {
        ...actual,
        useRoute: () => route,
        useRouter: () => ({ replace: vi.fn() }),
    }
})

const { notifyOnCatch } = vi.hoisted(() => ({ notifyOnCatch: vi.fn() }))
vi.mock("@/util", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/util")>()),
    notifyOnCatch,
}))

// Only setTimeout, so flushPromises (setImmediate) still runs
function typeAndWait(input: { setValue: (value: string) => Promise<void> }, value: string) {
    return input.setValue(value).then(() => vi.advanceTimersByTime(300))
}

beforeEach(() => {
    route.query = {}
    notifyOnCatch.mockClear()
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
})

afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
})
enableAutoUnmount(afterEach)

describe("PaginatedRepositoriesGrid filter input", () => {
    it("renders the filter input when allowSearch is set", async () => {
        const wrapper = mount(PaginatedRepositoriesGrid, {
            props: {
                allowSearch: true,
                onRequest: vi.fn<OnRequest>().mockResolvedValue(emptyQueryResults()),
            },
        })
        await flushPromises()

        expect(wrapper.find("input").exists()).toBe(true)
    })

    it("asks the server once typing pauses, not on every keystroke", async () => {
        const onRequest = vi.fn<OnRequest>().mockResolvedValue(emptyQueryResults())
        const wrapper = mount(PaginatedRepositoriesGrid, { props: { onRequest, allowSearch: true } })
        await flushPromises()

        await wrapper.get("input").setValue("b")
        await wrapper.get("input").setValue("bo")
        await typeAndWait(wrapper.get("input"), "bow")
        await flushPromises()

        expect(onRequest).toHaveBeenCalledTimes(2)
        expect(onRequest).toHaveBeenLastCalledWith({ page: 1, rowsPerPage: 25, filter: "bow" })
    })

    it("does not render the filter input when allowSearch is unset", async () => {
        const wrapper = mount(PaginatedRepositoriesGrid, {
            props: {
                onRequest: vi.fn<OnRequest>().mockResolvedValue(emptyQueryResults()),
            },
        })
        await flushPromises()

        expect(wrapper.find("input").exists()).toBe(false)
    })
})

function makeItems(page: number, count: number): RepositoryGridItem[] {
    return Array.from({ length: count }, (_, i) => ({
        index: (page - 1) * 25 + i,
        id: `r${page}-${i}`,
        name: `repo${page}-${i}`,
        owner: "devteam",
        update_time: "2024-01-01T00:00:00",
        description: `Repository ${page}-${i}`,
        homepage_url: null,
        remote_repository_url: null,
    }))
}

describe("PaginatedRepositoriesGrid paging", () => {
    it("lists the first page and pages forward and back through the server", async () => {
        const onRequest = vi.fn((query: Query) =>
            Promise.resolve({ items: makeItems(query.page, query.page < 3 ? 25 : 10), rowsNumber: 60 }),
        )
        const wrapper = mount(PaginatedRepositoriesGrid, { props: { onRequest } })
        await flushPromises()

        expect(onRequest).toHaveBeenLastCalledWith({ page: 1, rowsPerPage: 25 })
        expect(wrapper.findAll(".repository-entry")).toHaveLength(25)
        expect(wrapper.get(".grid-range").text()).toBe("1-25 of 60")
        expect(wrapper.get(".grid-page").text()).toBe("Page 1 of 3")

        await wrapper.get('[aria-label="Next page"]').trigger("click")
        await flushPromises()
        expect(onRequest).toHaveBeenLastCalledWith({ page: 2, rowsPerPage: 25 })
        expect(wrapper.get(".grid-range").text()).toBe("26-50 of 60")

        await wrapper.get('[aria-label="Previous page"]').trigger("click")
        await flushPromises()
        expect(onRequest).toHaveBeenLastCalledWith({ page: 1, rowsPerPage: 25 })
    })

    it("restarts from the first page with the filter when the filter changes", async () => {
        const onRequest = vi.fn((query: Query) => Promise.resolve({ items: makeItems(query.page, 25), rowsNumber: 60 }))
        const wrapper = mount(PaginatedRepositoriesGrid, { props: { onRequest, allowSearch: true } })
        await flushPromises()
        await wrapper.get('[aria-label="Next page"]').trigger("click")
        await flushPromises()

        await typeAndWait(wrapper.get("input"), "bowtie")
        await flushPromises()

        expect(onRequest).toHaveBeenLastCalledWith({ page: 1, rowsPerPage: 25, filter: "bowtie" })
    })

    it("ignores a response that arrives after a newer request", async () => {
        const slowResponse = deferred<QueryResults>()
        const onRequest = vi
            .fn<OnRequest>()
            .mockResolvedValueOnce({ items: makeItems(1, 2), rowsNumber: 2 })
            .mockReturnValueOnce(slowResponse.promise)
            .mockResolvedValueOnce({ items: makeItems(9, 1), rowsNumber: 1 })
        const wrapper = mount(PaginatedRepositoriesGrid, { props: { onRequest, allowSearch: true } })
        await flushPromises()

        try {
            await typeAndWait(wrapper.get("input"), "b")
            await typeAndWait(wrapper.get("input"), "bo")
            await flushPromises()
            slowResponse.resolve({ items: makeItems(5, 3), rowsNumber: 3 })
            await flushPromises()

            expect(wrapper.findAll(".repository-entry")).toHaveLength(1)
            expect(wrapper.text()).toContain("repo9-0")
        } finally {
            slowResponse.resolve({ items: makeItems(5, 3), rowsNumber: 3 })
            await flushPromises()
        }
    })

    it("says so when there are no repositories", async () => {
        const wrapper = mount(PaginatedRepositoriesGrid, {
            props: {
                onRequest: vi.fn<OnRequest>().mockResolvedValue(emptyQueryResults()),
                noDataLabel: "Nothing here",
            },
        })
        await flushPromises()

        expect(wrapper.get(".grid-empty").text()).toBe("Nothing here")
        expect(wrapper.find(".grid-pager").exists()).toBe(false)
    })

    it("leaves out the count heading until the server has answered", async () => {
        const response = deferred<QueryResults>()
        const onRequest = vi.fn<OnRequest>(() => response.promise)
        const wrapper = mount(PaginatedRepositoriesGrid, { props: { onRequest } })
        await flushPromises()

        try {
            expect(wrapper.find("h2").exists()).toBe(false)

            response.resolve({ items: makeItems(1, 1), rowsNumber: 1 })
            await flushPromises()
            expect(wrapper.get("h2").text()).toBe("1 repository")
        } finally {
            response.resolve({ items: makeItems(1, 1), rowsNumber: 1 })
            await flushPromises()
        }
    })

    it("stops loading and reports it when a request fails", async () => {
        const failure = new Error("server down")
        const wrapper = mount(PaginatedRepositoriesGrid, {
            props: { onRequest: vi.fn<OnRequest>().mockRejectedValue(failure) },
        })
        await flushPromises()

        expect(notifyOnCatch).toHaveBeenCalledWith(failure)
        expect(wrapper.find(".grid-loading").exists()).toBe(false)
        expect(wrapper.get("section").attributes("aria-busy")).toBe("false")
    })

    it("falls back to the defaults for page and page size values that aren't positive numbers", async () => {
        route.query = { page: "-2", rows_per_page: "abc" }
        const onRequest = vi.fn<OnRequest>().mockResolvedValue({ items: makeItems(1, 25), rowsNumber: 60 })
        const wrapper = mount(PaginatedRepositoriesGrid, { props: { onRequest } })
        await flushPromises()

        expect(onRequest).toHaveBeenCalledWith({ page: 1, rowsPerPage: 25 })
        expect(wrapper.get(".grid-range").text()).toBe("1-25 of 60")
    })
})
