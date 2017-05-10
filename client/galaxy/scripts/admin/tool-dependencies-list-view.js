define([
  "libs/toastr",
  "admin/tool-dependencies-row-view",
  "admin/tool-dependencies-model",
  "mvc/ui/ui-select",
  "utils/utils",
  ],
  function(
    mod_toastr,
    mod_tools_row_view,
    mod_tools_model,
    mod_ui_select,
    mod_utils
   ) {

var AdminToolDependenciesListView = Backbone.View.extend({
  el: '#center',

  rowViews: {},

  defaults: {
    view: 'all',
    section_filter: null,
    sort_by: 'name',
    sort_order: 'asc',
  },

  events: {
    'click #select-all-checkboxes': 'selectAll',
    'click th > a'                : 'sortClicked',
  },

  list_sections: [],

  initialize: function( options ){
    this.options = _.defaults( this.options || {}, options, this.defaults );
    this.collection = new mod_tools_model.Tools();
    // start to listen if someone modifies the collection
    // this.listenTo( this.collection, 'add', this.renderOne );
    // this.listenTo( this.collection, 'change', this.renderAll );
    // this.listenTo( this.collection, 'reset', this.renderAll );
    this.listenTo( this.collection, 'sync', this.renderAll );
    // this.listenTo( this.collection, 'remove', this.removeOne );
    this.collection.switchComparator(this.options.sort_by);
    this.render();
    this.fetchRepos();
    this.adjustMenu();
  },

  render: function(options){
    this.options = _.extend( this.options, options );
    var tool_dependencies_list_template = this.templateList();
    this.$el.html(tool_dependencies_list_template({section_filter: this.options.section_filter}));
    this.fetchSections();
    $( "#center" ).css( 'overflow','auto' );
    this.$el.find('[data-toggle]').tooltip();
    return this;
  },

  fetchRepos: function(){
    var that = this;
    this.collection.fetch({
      success: function(collection, response, options){
      },
      error: function(collection, response, options){
      }
    });
  },

  repaint: function(options){
    this.options = _.extend( this.options, options );
    this.render();
    this.removeAllRows();
    this.clearFilter();
    this.adjustMenu();
    this.renderAll();
    return this;
  },

  adjustMenu: function(options){
    this.options = _.extend( this.options, options );
    this.$el.find('li').removeClass('active');
    $('.tab_' + this.options.view).addClass('active');
    if (this.options.view === 'uninstalled'){
      $("#admin_section_select").hide();
    } else{
      $("#admin_section_select").show();
    }
  },

  /**
   * Iterate this view's collection and call the render
   * function for each in case it passes the filter.
   */
  renderAll: function(options){
    this.select_section.value(this.options.section_filter);
    this.options = _.extend( this.options, options );
    this.collection.switchComparator(this.options.sort_by);
    this.collection.sort();
    var models = this.options.sort_order === 'desc' ? this.collection.models.reverse() : this.collection.models;
    var that = this;
    _.each( models, function( model ) {
      if(model.has_requirements()) {
        that.renderOne( model ); 
      }
    });
  },

  /**
   * Create a view for the given repo and add it to the list view.
   * @param {Repo} model of the view that will be rendered
   */
  renderOne: function(tool_dependencies){
    var toolView = null;
    var is_visible = true;
    var is_filter_valid = (typeof tool_dependencies.get('sections') !== 'undefined') && (tool_dependencies.get('sections').indexOf(this.options.section_filter) >= 0);
    is_visible = is_visible || (this.options.view === 'all');
    is_visible = is_visible && (!this.options.section_filter || is_filter_valid);
    if (is_visible) {
      if (this.rowViews[tool_dependencies.get('id')]){
        toolView = this.rowViews[tool_dependencies.get('id')].render();
        this.$el.find('[data-toggle]').tooltip();
      } else {
        toolView = new mod_tools_row_view.AdminToolsRowView({tool_dependencies: tool_dependencies});
        this.rowViews[tool_dependencies.get('id')] = toolView;
        this.$el.find('[data-toggle]').tooltip();
      }
      this.$el.find('#tool_dependencies_list_body').append(toolView.el);
    }
  },

  removeOne: function(){

  },

  /**
   * Remove all repo row elements from the DOM.
   */
  removeAllRows: function(){
    var that = this;
    this.$el.find('.repo-row').each( function(){
      var view_id = $(this).data('id')
      that.rowViews[view_id].remove();
    });
  },

  /**
   * User clicked the checkbox in the table heading
   * @param  {context} event
   */
  selectAll : function (event) {
     var selected = event.target.checked;
     that = this;
     // Iterate each checkbox
     $(':checkbox', '#tool_dependencies_list_body').each(function() {
      this.checked = selected;
      view_id = $(this.parentElement.parentElement).data('id');
      if (selected) {
        that.rowViews[view_id].turnDark();
      } else {
        that.rowViews[view_id].turnLight();
      }
    });
   },

   sortClicked: function(event){
    event.preventDefault();
    this.adjustHeading(event);
    this.removeAllRows();
    this.renderAll();
   },

   adjustHeading: function(event){
    var source_class = $(event.target).attr('class').split('-')[2];
    if (source_class === this.options.sort_by){
      this.options.sort_order = this.options.sort_order === 'asc' ? 'desc' : 'asc';
    }
    this.options.sort_by = source_class;
    console.log(this.options.sort_by);
    this.$el.find('span[class^="sort-icon"]').hide().removeClass('fa-sort-asc').removeClass('fa-sort-desc');
    this.$el.find('.sort-icon-' + source_class).addClass('fa-sort-' + this.options.sort_order).show();
   },

  /**
   * Request all sections from Galaxy toolpanel
   * and save them in the list for select2. Call
   * render on success callback.
   */
  fetchSections: function(){
    var that = this;
    mod_utils.get({
      url      :  Galaxy.root + "api/toolpanel",
      success  :  function( sections ) {
                    that.list_sections = [];
                    that.list_sections.push({id: '',text: ''})
                    for (key in sections) {
                      that.list_sections.push({
                        id              : sections[key].id,
                        text            : sections[key].name
                      });
                    }
                  that._renderSelectBox();
                  },
      cache    : true
    });
  },

  _renderSelectBox: function(){
    /**
     * Render the toolpanel section select box.
     *
     * TODO switch to common resources:
     * https://trello.com/c/dIUE9YPl/1933-ui-common-resources-and-data-into-galaxy-object
     */
    var that = this;
    this.select_section = new mod_ui_select.View({
      css: 'admin-section-select',
      data: that.list_sections,
      container: that.$el.find('#admin_section_select'),
      placeholder: "Section Filter",
      allowClear: true,
      value: that.options.section_filter
    });
    this.$el.find('#admin_section_select')
      .on("select2-selecting", function(e){
        Galaxy.adminapp.admin_router.navigate('repos/v/' + that.options.view + '/f/' + e.val, {trigger: true});
      })
      .on("select2-removed", function(e){
        Galaxy.adminapp.admin_router.navigate('repos/v/' + that.options.view, {trigger: true});
      })
  },

  clearFilter: function(){
    if (this.select_section){
      this.select_section.clear();
    }
  },

  templateList: function(){
    return _.template([
      '<div class="tool_dependencies_container">',
        '<div class="admin_toolbar">',
            '<span><strong>TOOL DEPENDENCIES</strong></span>',
            '<button data-toggle="tooltip" data-placement="top" title="Install selected tool dependencies" class="btn btn-default primary-button toolbar-item" type="button">',
              'Install',
            '</button>',
            '<button data-toggle="tooltip" data-placement="top" title="Uninstall selected dependencies" class="btn btn-default primary-button toolbar-item" type="button">',
              'Uninstall',
            '</button>',
            '<span id="admin_section_select" class="admin-section-select toolbar-item" />',

          // '</form>',
          '<ul class="nav nav-tabs repos-nav">',
            '<li role="presentation" class="tab_by_tool">',
              '<a href="#tool_dependencies/v/by_tool">By Tool</a>',
            '</li>',
            '<li role="presentation" class="tab_by_requirement"><a href="#tool_dependencies/v/by_requirement">By Requirement</a></li>',
            '<li role="presentation" class="tab_unused"><a href="#tool_dependencies/v/unused">Unused</a></li>',
          '</ul>',
        '</div>',
        '<div id="repositories_list">',
          '<div class="tool_dependencies_container table-responsive">',
            '<table class="grid table table-condensed">',
              '<thead>',
                this.templateHeader(),
              '</thead>',
              '<tbody id="tool_dependencies_list_body">',
              // repo item views will attach here
              '</tbody>',
            '</table>',
          '</div>',
        '</div>',
      '</div>'
    ].join(''));
  },

  templateHeader: function() {
    if( this.options.view == 'by_tool' ) {
      return [
        '<th style="text-align: center; width: 20px; " title="Check to select all repositories">',
          '<input id="select-all-checkboxes" style="margin: 0;" type="checkbox">',
        '</th>',
        '<th>',
          '<a class="sort-repos-name" data-toggle="tooltip" data-placement="top" title="sort alphabetically" href="#">',
            'Name',
          '</a>',
          '<span class="sort-icon-name fa fa-sort-asc" style="display: none;"/>',
        '</th>',
        '<th>',
          '<a class="sort-repos-id" data-toggle="tooltip" data-placement="top" title="sort alphabetically" href="#">',
            'ID',
          '</a>',
          '<span class="sort-icon-id fa fa-sort-asc" style="display: none;"/>',
        '</th>',
        '<th>',
          '<a class="sort-repos-requirement" data-toggle="tooltip" data-placement="top" title="sort alphabetically" href="#">',
            'Requirement',
          '</a>',
          '<span class="sort-icon-requirement fa fa-sort-asc" style="display: none;"/>',
        '</th>',
        '<th>',
          '<a class="sort-repos-version" data-toggle="tooltip" data-placement="top" title="sort alphabetically" href="#">',
            'Version',
          '</a>',
          '<span class="sort-icon-version fa fa-sort-asc" style="display: none;"/>',
        '</th>',
      ].join('');
    } else if( this.options.view == 'by_requirement' ) {
      return [
        '<th style="text-align: center; width: 20px; " title="Check to select all repositories">',
          '<input id="select-all-checkboxes" style="margin: 0;" type="checkbox">',
        '</th>',
        '<th>',
          '<a class="sort-repos-name" data-toggle="tooltip" data-placement="top" title="sort alphabetically" href="#">',
            'Requirement(s)',
          '</a>',
          '<span class="sort-icon-name fa fa-sort-asc" style="display: none;"/>',
        '</th>',
      ].join('');
    }
  }

});

return {
    AdminToolDependenciesListView: AdminToolDependenciesListView
};

});
