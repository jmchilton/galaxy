define([
  "libs/toastr",
  "admin/repos-row-view",
  "admin/tools-model",
  "mvc/ui/ui-select",
  "utils/utils",
  ],
  function(
    mod_toastr,
    mod_repo_row_view,
    mod_tools_model,
    mod_ui_select,
    mod_utils
   ) {

var AdminToolsListView = Backbone.View.extend({
  el: '#center',

  rowViews: {},

  defaults: {
    view: 'all',
    section_filter: null,
    sort_by: 'date',
    sort_order: 'asc',
  },

  events: {
    'click #select-all-checkboxes': 'selectAll',
    'click th > a'                : 'sortClicked',
  },

  list_sections: [],

  initialize: function( options ){
    this.options = _.defaults( this.options || {}, options, this.defaults );
    this.collection = new mod_tools_model.Repos();

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
    var repo_list_template = this.templateToolList();
    this.$el.html(repo_list_template({section_filter: this.options.section_filter}));
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
    _.each( models, function( repo ) {
      that.renderOne( repo );
    });
  },

  /**
   * Create a view for the given repo and add it to the list view.
   * @param {Repo} model of the view that will be rendered
   */
  renderOne: function(repo){
    var repoView = null;
    var is_visible = false;
    var is_uninstalled_or_deactivated = repo.get('status').toLowerCase() === 'uninstalled' || repo.get('status').toLowerCase() === 'deactivated';
    var is_filter_valid = (typeof repo.get('sections') !== 'undefined') && (repo.get('sections').indexOf(this.options.section_filter) >= 0);
    is_visible = this.options.view === 'uninstalled' && is_uninstalled_or_deactivated;
    is_visible = is_visible || ((this.options.view === 'all' || this.options.view === repo.get('type')) && !is_uninstalled_or_deactivated);
    is_visible = is_visible && (!this.options.section_filter || is_filter_valid);

    if (is_visible) {
      if (this.rowViews[repo.get('id')]){
        repoView = this.rowViews[repo.get('id')].render();
        this.$el.find('[data-toggle]').tooltip();
      } else {
        repoView = new mod_repo_row_view.AdminReposRowView({repo: repo});
        this.rowViews[repo.get('id')] = repoView;
        this.$el.find('[data-toggle]').tooltip();
      }
      this.$el.find('#tools_list_body').append(repoView.el);
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
     $(':checkbox', '#tools_list_body').each(function() {
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

  templateToolList: function(){
    return _.template([
      '<div class="repos_container">',
        '<div class="repos_toolbar">',
            '<span><strong>TOOLS</strong></span>',
            '<span id="admin_section_select" class="admin-section-select toolbar-item" />',

          // '</form>',
          '<ul class="nav nav-tabs repos-nav">',
            '<li role="presentation" class="tab_all">',
              '<a href="#repos/v/all">All</a>',
              // '<a href="#repos/v/all<% print("/f/" + filter) %>">All</a>',
            '</li>',
            '<li role="presentation" class="tab_tools"><a href="#repos/v/tools">With Tools</a></li>',
            '<li role="presentation" class="tab_packages"><a href="#repos/v/packages">Packages</a></li>',
            '<li role="presentation" class="tab_uninstalled"><a href="#repos/v/uninstalled">Uninstalled or Deactivated</a></li>',
            // '<li role="presentation" class="tab_suites"><a href="#repos?view=suites">Suites</a></li>',
            // '<li role="presentation" class="tab_with_dm"><a href="#repos?view=dm">Data Managers</a></li>',
            // '<li role="presentation" class="tab_with_datatypes"><a href="#repos?view=datatypes">Datatypes</a></li>',
          '</ul>',
        '</div>',
        '<div id="repositories_list">',
          '<div class="repos_container table-responsive">',
            '<table class="grid table table-condensed">',
              '<thead>',
                '<th style="text-align: center; width: 20px; " title="Check to select all repositories">',
                  '<input id="select-all-checkboxes" style="margin: 0;" type="checkbox">',
                '</th>',
                '<th>',
                  '<a class="sort-repos-name" data-toggle="tooltip" data-placement="top" title="sort alphabetically" href="#">',
                    'Name',
                  '</a>',
                  '<span class="sort-icon-name fa fa-sort-asc" style="display: none;"/>',
                '</th>',
              '</thead>',
              '<tbody id="tools_list_body">',
              // repo item views will attach here
              '</tbody>',
            '</table>',
          '</div>',
        '</div>',
      '</div>'
    ].join(''));
  }

});

return {
    AdminToolsListView: AdminToolsListView
};

});
