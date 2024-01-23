/**
 * These functions are for mounting the tag display/editor in non-Vue
 * environments such as the existing python scripts and Backbone views.
 */

import { mountVueComponent } from "utils/mountVueComponent";

import { BackboneTagService } from "./backboneTagService";
import Tags from "./Tags";
import { TagService } from "./tagService";

/**
 * General mount function for the tags that were previously rendered
 * by the tagging_common.mako file
 */
export const mountMakoTags = (options = {}, el) => {
    const { id, itemClass, tags = [], disabled = false, context = "unspecified" } = options;

    const propData = {
        storeKey: `${itemClass}-${id}`,
        tagService: new TagService({ id, itemClass, context }),
        tags,
        disabled,
    };

    const fn = mountVueComponent(Tags);
    const vm = fn(propData, el);
    vm.$on("tag-click", makoClickHandler(options, vm));
    return vm;
};

/**
 * Generate a click handler for the tags
 *
 * @param {object} options Passed options from mount fn
 */
const makoClickHandler = (options, vm) =>
    function (tag) {
        if (!tag) {
            return;
        }

        console.error("MAKO Tag click handler deprecated");
    };

/**
 * Mount function when a backbone model is provided.
 */
export const mountModelTags = (options = {}, el) => {
    const { model, disabled = false, context = "unspecified" } = options;

    if (!model) {
        console.warn("Missing model in mountModelTags");
        return;
    }

    const { id, model_class: itemClass, tags = [] } = model.attributes;

    const propData = {
        storeKey: `${itemClass}-${id}`,
        tagService: new BackboneTagService({ id, itemClass, context, model }),
        tags,
        disabled,
    };

    const fn = mountVueComponent(Tags);
    return fn(propData, el);
};
