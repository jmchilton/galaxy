define("mvc/history/hdca-li",["exports","mvc/dataset/states","mvc/collection/collection-li","mvc/collection/collection-view","mvc/base-mvc","mvc/history/history-item-li","utils/localization"],function(e,t,s,i,n,a,r){"use strict";function o(e){return e&&e.__esModule?e:{default:e}}Object.defineProperty(e,"__esModule",{value:!0});var l=o(t),c=o(s),d=o(i),p=(o(n),o(a)),u=o(r),h=c.default.DCListItemView,m=h.extend({className:h.prototype.className+" history-content",_setUpListeners:function(){var e=this;h.prototype._setUpListeners.call(this);var t=function(t,s){e.render()};this.model.jobStatesSummary&&this.listenTo(this.model.jobStatesSummary,"change",t),this.listenTo(this.model,{"change:tags change:visible change:state":t})},_getFoldoutPanelClass:function(){var e=this.model.get("collection_type");switch(e){case"list":return d.default.ListCollectionView;case"paired":return d.default.PairCollectionView;case"list:paired":return d.default.ListOfPairsCollectionView;case"list:list":return d.default.ListOfListsCollectionView}throw new TypeError("Unknown collection_type: "+e)},_swapNewRender:function(e){h.prototype._swapNewRender.call(this,e);var t,s=this.model.jobStatesSummary;t=s?s.new()?"new":s.errored()?"error":s.terminal()?"ok":s.running()?"running":"queued":this.model.get("job_source_id")?l.default.NEW:this.model.get("populated_state")?l.default.OK:l.default.RUNNING,this.$el.addClass("state-"+t);var i=this.stateDescription();return console.log(i),this.$(".state-description").html(i),this.$el},stateDescription:function(){var e=this.model,t=e.get("element_count");console.log(t);var s,i=e.get("job_source_type"),n=this.model.get("collection_type");s="list"==n?"list":"paired"==n?"dataset pair":"list:paired"==n?"list of pairs":"nested list";var a="";1==t?a=" with 1 item":t&&(a=" with "+t+" items");var r=e.jobStatesSummary,o=""+s+a;if(i&&"Job"!=i){if(r&&r.hasDetails()){var l=r.new(),c=l?null:r.jobCount();if(l)return'\n                        <div class="progress state-progress">\n                            <span class="note">Creating jobs...</span>\n                            <div class="progress-bar info" style="width:100%">\n                        </div>';if(r.errored())return"a "+s+" with "+r.numInError()+" / "+c+" jobs in error";if(r.terminal())return"a "+o;var d=r.states().running||0,p=(r.states().ok||0)/(1*c),u=d/(1*c),h=1-p-u;return'\n                        <div class="progress state-progress">\n                            <span class="note">'+(c&&c>1?c+" jobs":"a job")+" generating a "+s+'</span>\n                            <div class="progress-bar ok" style="width:'+100*p+'%"></div>\n                            <div class="progress-bar running" style="width:'+100*u+'%"></div>\n                            <div class="progress-bar new" style="width:'+100*h+'%">\n                        </div>'}return'\n                    <div class="progress state-progress">\n                        <span class="note">Loading job data for '+s+'...</span>\n                        <div class="progress-bar info" style="width:100%">\n                    </div>'}return"a "+o},toString:function(){return"HDCAListItemView("+(this.model?""+this.model:"(no model)")+")"}});m.prototype.templates=function(){var e=_.extend({},h.prototype.templates.warnings,{hidden:function(e){e.visible||(0,u.default)("This collection has been hidden")}});return _.extend({},h.prototype.templates,{warnings:e,titleBar:function(e){return'\n        <div class="title-bar clear" tabindex="0">\n            <span class="state-icon"></span>\n            <div class="title">\n                <span class="hid">'+e.hid+'</span>\n                <span class="name">'+_.escape(e.name)+'</span>\n            </div>\n            <div class="state-description">\n            </div>\n            '+p.default.nametagTemplate(e)+"\n        </div>\n    "}})}(),e.default={HDCAListItemView:m}});