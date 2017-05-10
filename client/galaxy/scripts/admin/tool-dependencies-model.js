define([], function() {

  var Tool = Backbone.Model.extend({
    urlRoot: Galaxy.root + 'api/dependency_resolvers/tools',

    has_requirements: function() {
      return this.attributes.requirements.length > 0;
    },

    parse: function(response) {
       response.id = response.tool.id;
       response.name = response.tool.name;
       return response;
    }
  });

  var Tools = Backbone.Collection.extend({
    url: Galaxy.root + 'api/dependency_resolvers/tools',

    model: Tool,

    switchComparator: function(comparator_name){
      this.comparator = comparator_name;
    }

  });

// ============================================================================
// JSTREE MODEL
/** Represents folder structure parsable by the jstree component.
 *
 */

var Jstree = Backbone.Model.extend({
  urlRoot: Galaxy.root + 'api/dependency_resolvers/tools/'
});

return {
    Tool: Tool,
    Tools: Tools,
    Jstree: Jstree
};

});
