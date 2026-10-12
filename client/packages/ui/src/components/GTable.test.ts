import "@testing-library/jest-dom/vitest";

import { nth } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, onTestFinished } from "vitest";

import GTable from "./GTable.vue";

enableAutoUnmount(afterEach);

const items = [
    { id: 1, name: "first" },
    { id: 2, name: "second" },
];

type TableProps = Parameters<typeof GTable>[0];

function attachmentTarget() {
    const target = document.createElement("div");
    document.body.appendChild(target);
    onTestFinished(() => target.remove());
    return target;
}

function mountSelectable(props: TableProps = {}) {
    return mount(GTable, {
        props: {
            items,
            fields: [{ key: "name" }],
            selectable: true,
            clickableRows: true,
            showSelectAll: true,
            ...props,
        },
        attachTo: attachmentTarget(),
    });
}

describe("GTable selection", () => {
    it.each([undefined, "Select dataset"])("names the selection checkboxes (%s)", (title) => {
        const wrapper = mount(GTable, {
            props: {
                items,
                fields: [{ key: "name" }],
                selectable: true,
                showSelectAll: true,
                selectCheckboxTitle: title,
            },
            attachTo: attachmentTarget(),
        });

        expect(wrapper.get("thead input").element).toHaveAccessibleName("Select all for bulk actions");
        for (const checkbox of wrapper.findAll("tbody input")) {
            expect(checkbox.element).toHaveAccessibleName(title ?? "Select for bulk actions");
        }
    });

    // Selenium clicks the checkbox's label; the click must stop at the checkbox rather than
    // also reaching the row, whose own handler would toggle the selection a second time.
    it("selects a row once from its checkbox without counting a row click", async () => {
        const wrapper = mountSelectable();

        await nth(wrapper.findAll("tbody tr"), 0).get(".g-checkbox").trigger("click");

        expect(wrapper.emitted("row-select")).toEqual([[{ item: items[0], index: 0, selected: true }]]);
        expect(wrapper.emitted("row-click")).toBeUndefined();
    });

    it("selects all from the header checkbox", async () => {
        const wrapper = mountSelectable();

        await wrapper.get("thead .g-checkbox").trigger("click");

        expect(wrapper.emitted("select-all")).toEqual([[true]]);
    });

    it("shows partial selection on the header and on indeterminate rows", () => {
        const wrapper = mountSelectable({ selectedItems: [0], indeterminateItems: [1] });
        const rows = wrapper.findAll<HTMLInputElement>("tbody input");
        const first = nth(rows, 0).element;
        const second = nth(rows, 1).element;
        const header = wrapper.get<HTMLInputElement>("thead input").element;

        expect(header.indeterminate).toBe(true);
        expect(first.checked).toBe(true);
        expect(first.indeterminate).toBe(false);
        expect(second.indeterminate).toBe(true);
    });

    it("checks the header, not partially, once every row is selected", () => {
        const wrapper = mountSelectable({ selectedItems: [0, 1] });
        const header = wrapper.get<HTMLInputElement>("thead input").element;

        expect(header.checked).toBe(true);
        expect(header.indeterminate).toBe(false);
    });
});

describe("GTable sorting", () => {
    function mountSortable(slots: Record<string, string> = {}) {
        return mount(GTable, {
            props: {
                items,
                fields: [
                    { key: "name", label: "Name", sortable: true },
                    { key: "id", label: "Id", sortable: true },
                    { key: "note", label: "Note" },
                ],
                sortBy: "name",
            },
            slots,
            attachTo: attachmentTarget(),
        });
    }

    it("exposes the sort state on sortable headers only", () => {
        const wrapper = mountSortable();
        const headers = wrapper.findAll("thead th");
        const name = nth(headers, 0);
        const id = nth(headers, 1);
        const note = nth(headers, 2);

        expect(name.attributes("aria-sort")).toBe("ascending");
        expect(name.attributes("tabindex")).toBe("0");
        expect(id.attributes("aria-sort")).toBe("none");
        expect(id.attributes("tabindex")).toBe("0");
        expect(note.attributes("aria-sort")).toBeUndefined();
        expect(note.attributes("tabindex")).toBeUndefined();
    });

    it("sorts from the keyboard with Enter and Space", async () => {
        const wrapper = mountSortable();
        const name = nth(wrapper.findAll("thead th"), 0);

        await name.trigger("keydown", { key: "Enter" });
        expect(wrapper.emitted("sort-changed")).toEqual([["name", true]]);
        expect(name.attributes("aria-sort")).toBe("descending");
        expect(wrapper.findAll("tbody tr td:first-child").map((cell) => cell.text())).toEqual(["second", "first"]);

        await name.trigger("keydown", { key: " " });
        expect(wrapper.emitted("sort-changed")).toEqual([
            ["name", true],
            ["name", false],
        ]);
    });

    // Space would otherwise scroll the page as well as sorting
    it("keeps Space on a sortable header from scrolling the page", () => {
        const wrapper = mountSortable();
        const space = new KeyboardEvent("keydown", { key: " ", cancelable: true });

        nth(wrapper.findAll("thead th"), 0).element.dispatchEvent(space);

        expect(space.defaultPrevented).toBe(true);
    });

    it("leaves Enter alone for a control inside a header slot", async () => {
        const wrapper = mountSortable({ "head(name)": "<button class='head-control'>Options</button>" });

        await wrapper.get(".head-control").trigger("keydown", { key: "Enter" });

        expect(wrapper.emitted("sort-changed")).toBeUndefined();
    });
});
