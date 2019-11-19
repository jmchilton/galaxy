import { standardInit, addInitialization } from "onload";
import Page from "layout/page";
import WorkflowHome from "components/WorkflowHome.vue";
import Vue from "vue";
import store from "store";

export function initLoginView(Galaxy, { options }) {
    console.log("initLoginView");
    options.config.masthead_show_analysis = false;
    options.config.masthead_show_workflows = false;
    options.config.masthead_show_shared_data = false;
    options.config.visualizations_visible = false;
    options.config.masthead_show_activities = true;
    options.config.masthead_show_scratchbook = false;
    console.log(options);
    Galaxy.page = new Page.View(options);
    const vm = document.createElement("div");
    Galaxy.display(vm);
    const homeInstance = Vue.extend(WorkflowHome);
    new homeInstance({
        propsData: {},
        store
    }).$mount(vm);
}

addInitialization(initLoginView);

window.addEventListener("load", () => standardInit("login"));
