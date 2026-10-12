import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { components } from "@/schema/schema"
import { useAuthStore } from "@/stores"
import { createMemoryRouter } from "@/test-utils"
import ShedToolbar from "./ShedToolbar.vue"

// The toolbar consumes these two user fields; the authentication request is stubbed.
type ToolbarUser = Pick<components["schemas"]["UserV2"], "username" | "is_admin">
const mountHosts = new Set<HTMLElement>()

afterEach(() => {
    for (const host of mountHosts) {
        host.remove()
    }
    mountHosts.clear()
    vi.restoreAllMocks()
})
// Stacked afterEach hooks unmount before removing hosts and restoring store spies.
enableAutoUnmount(afterEach)

function mountToolbar(user: ToolbarUser | null) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const authStore = useAuthStore(pinia)
    vi.spyOn(authStore, "setup").mockResolvedValue(undefined)
    const logout = vi.spyOn(authStore, "logout").mockResolvedValue(undefined)
    authStore.user = user
    const host = document.createElement("div")
    mountHosts.add(host)
    document.body.append(host)
    const wrapper = mount(ShedToolbar, {
        props: { title: "Tool Shed" },
        global: { plugins: [pinia, createMemoryRouter()] },
        attachTo: host,
    })
    return { wrapper, logout }
}

function menuLinks(wrapper: ReturnType<typeof mountToolbar>["wrapper"], toggleText: string) {
    const toggle = wrapper.findAll(".masthead-toggle").find((button) => button.text() === toggleText)
    if (!toggle) {
        throw new Error(`no "${toggleText}" menu`)
    }
    const menu = wrapper.get(`#${toggle.attributes("aria-controls")}`)
    return menu.findAll("a").map((link) => link.attributes("href"))
}

describe("ShedToolbar", () => {
    it("offers the repository browsing routes under Explore", () => {
        const { wrapper } = mountToolbar(null)

        expect(menuLinks(wrapper, "Explore")).toEqual([
            "/repositories_by_category",
            "/repositories_by_owner",
            "/repositories_by_search",
        ])
    })

    it("shows a login link and no user or admin menu when logged out", () => {
        const { wrapper } = mountToolbar(null)

        expect(wrapper.get(".toolbar-login").attributes("href")).toBe("/login")
        expect(wrapper.get(".toolbar-login").attributes("aria-label")).toBe("Login")
        expect(wrapper.find(".toolbar-logout").exists()).toBe(false)
        expect(wrapper.findAll(".masthead-toggle").map((button) => button.text())).toEqual(["Explore"])
    })

    it("shows the user's menu and logs out from the toolbar", async () => {
        const { wrapper, logout } = mountToolbar({ username: "bob", is_admin: false })

        expect(menuLinks(wrapper, "bob")).toEqual(["/user/api_key", "/user/change_password"])
        expect(wrapper.find(".toolbar-login").exists()).toBe(false)

        await wrapper.get(".toolbar-logout").trigger("click")
        await flushPromises()

        expect(logout).toHaveBeenCalledTimes(1)
    })

    it("adds the admin menu only for admins", () => {
        const { wrapper } = mountToolbar({ username: "alice", is_admin: true })

        expect(menuLinks(wrapper, "Admin")).toEqual(["/admin", "/_component_showcase"])
    })
})
