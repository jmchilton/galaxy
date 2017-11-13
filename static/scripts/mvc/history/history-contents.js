define("mvc/history/history-contents",["exports","mvc/base/controlled-fetch-collection","mvc/history/hda-model","mvc/history/hdca-model","mvc/history/history-preferences","mvc/history/job-states-model","mvc/base-mvc","utils/ajax-queue"],function(t,e,i,n,o,r,s,a){"use strict";function l(t){return t&&t.__esModule?t:{default:t}}Object.defineProperty(t,"__esModule",{value:!0});var d=l(e),c=l(i),u=l(n),h=l(o),f=l(r),y=l(s),m=l(a),p=500;try{p=localStorage.getItem("historyContentsLimitPerPageDefault")||p}catch(t){}var g=d.default.PaginatedCollection,v=g.extend(y.default.LoggableMixin).extend({_logNamespace:"history",limitPerPage:p,limitPerProgressiveFetch:p,order:"hid",urlRoot:Galaxy.root+"api/histories",url:function(){return this.urlRoot+"/"+this.historyId+"/contents"},initialize:function(t,e){this.on({"sync add":this.trackJobStates}),e=e||{},g.prototype.initialize.call(this,t,e),this.history=e.history||null,this.setHistoryId(e.historyId||null),this.includeDeleted=e.includeDeleted||this.includeDeleted,this.includeHidden=e.includeHidden||this.includeHidden,this.model.prototype.idAttribute="type_id"},trackJobStates:function(){var t=this;this.each(function(e){if(!e.has("job_states_summary")&&"dataset_collection"===e.attributes.history_content_type){var i=e.attributes.job_source_type,n=e.attributes.job_source_id;if(i){t.jobStateSummariesCollection.add({id:n,model:i,history_id:t.history_id,collection_id:e.attributes.id});var o=t.jobStateSummariesCollection.get(n);e.jobStatesSummary=o}}})},model:function(t,e){if("dataset"===t.history_content_type)return new c.default.HistoryDatasetAssociation(t,e);if("dataset_collection"===t.history_content_type){switch(t.collection_type){case"list":return new u.default.HistoryListDatasetCollection(t,e);case"paired":return new u.default.HistoryPairDatasetCollection(t,e);case"list:paired":return new u.default.HistoryListPairedDatasetCollection(t,e);case"list:list":return new u.default.HistoryListOfListsDatasetCollection(t,e)}var i="Unknown collection_type: "+t.collection_type;return console.warn(i,t),{validationError:i}}return{validationError:"Unknown history_content_type: "+t.history_content_type}},stopPolling:function(){this.jobStateSummariesCollection&&(this.jobStateSummariesCollection.active=!1,this.jobStateSummariesCollection.clearUpdateTimeout())},setHistoryId:function(t){this.stopPolling(),this.historyId=t,t&&(this._setUpWebStorage(),this.jobStateSummariesCollection=new f.default.JobStatesSummaryCollection,this.jobStateSummariesCollection.historyId=t,this.jobStateSummariesCollection.monitor())},_setUpWebStorage:function(t){return this.storage=new h.default.HistoryPrefs({id:h.default.HistoryPrefs.historyStorageKey(this.historyId)}),this.trigger("new-storage",this.storage,this),this.on({"include-deleted":function(t){this.storage.includeDeleted(t)},"include-hidden":function(t){this.storage.includeHidden(t)}}),this.includeDeleted=this.storage.includeDeleted()||!1,this.includeHidden=this.storage.includeHidden()||!1,this},comparators:_.extend(_.clone(g.prototype.comparators),{name:y.default.buildComparator("name",{ascending:!0}),"name-dsc":y.default.buildComparator("name",{ascending:!1}),hid:y.default.buildComparator("hid",{ascending:!1}),"hid-asc":y.default.buildComparator("hid",{ascending:!0})}),running:function(){return this.filter(function(t){return!t.inReadyState()})},runningAndActive:function(){return this.filter(function(t){return!t.inReadyState()&&t.get("visible")&&!t.get("deleted")})},getByHid:function(t){return this.findWhere({hid:t})},haveDetails:function(){return this.all(function(t){return t.hasDetails()})},hidden:function(){return this.filter(function(t){return t.hidden()})},deleted:function(){return this.filter(function(t){return t.get("deleted")})},visibleAndUndeleted:function(){return this.filter(function(t){return t.get("visible")&&!t.get("deleted")})},setIncludeDeleted:function(t,e){if(_.isBoolean(t)&&t!==this.includeDeleted){if(this.includeDeleted=t,_.result(e,"silent"))return;this.trigger("include-deleted",t,this)}},setIncludeHidden:function(t,e){if(_.isBoolean(t)&&t!==this.includeHidden){if(this.includeHidden=t,e=e||{},_.result(e,"silent"))return;this.trigger("include-hidden",t,this)}},fetch:function(t){if(t=t||{},this.historyId&&!t.details){var e=h.default.HistoryPrefs.get(this.historyId).toJSON();_.isEmpty(e.expandedIds)||(t.details=_.values(e.expandedIds).join(","))}return g.prototype.fetch.call(this,t)},_buildFetchData:function(t){return _.extend(g.prototype._buildFetchData.call(this,t),{v:"dev"})},_fetchParams:g.prototype._fetchParams.concat(["v","details"]),_buildFetchFilters:function(t){var e=g.prototype._buildFetchFilters.call(this,t)||{},i={};return this.includeDeleted||(i.deleted=!1,i.purged=!1),this.includeHidden||(i.visible=!0),_.defaults(e,i)},getTotalItemCount:function(){return this.history.contentsShown()},fetchUpdated:function(t,e){return t&&((e=e||{filters:{}}).remove=!1,e.filters={"update_time-ge":t.toISOString(),visible:""}),this.fetch(e)},fetchDeleted:function(t){var e=this;return t=t||{},t.filters=_.extend(t.filters,{deleted:!0,purged:void 0}),t.remove=!1,this.trigger("fetching-deleted",this),this.fetch(t).always(function(){e.trigger("fetching-deleted-done",e)})},fetchHidden:function(t){var e=this;return(t=t||{}).filters=_.extend(t.filters,{visible:!1}),t.remove=!1,e.trigger("fetching-hidden",e),e.fetch(t).always(function(){e.trigger("fetching-hidden-done",e)})},fetchAllDetails:function(t){var e={details:"all"};return(t=t||{}).data=_.extend(t.data||{},e),this.fetch(t)},_filterAndUpdate:function(t,e){var i=this,n=i.model.prototype.idAttribute,o=[e];return i.fetch({filters:t,remove:!1}).then(function(t){return t=t.reduce(function(t,e,o){var r=i.get(e[n]);return r?t.concat(r):t},[]),i.ajaxQueue("save",o,t)})},ajaxQueue:function(t,e,i){return i=i||this.models,new m.default.AjaxQueue(i.slice().reverse().map(function(i,n){var o=_.isString(t)?i[t]:t;return function(){return o.apply(i,e)}})).deferred},progressivelyFetchDetails:function(t){function e(s){s=s||0;var a=_.extend(_.clone(t),{view:"summary",keys:r,limit:o,offset:s,reset:0===s,remove:!1});_.defer(function(){n.fetch.call(n,a).fail(i.reject).done(function(t){i.notify(t,o,s),t.length!==o?(n.allFetched=!0,i.resolve(t,o,s)):e(s+o)})})}t=t||{};var i=jQuery.Deferred(),n=this,o=t.limitPerCall||n.limitPerProgressiveFetch,r=c.default.HistoryDatasetAssociation.prototype.searchAttributes.join(",");return e(),i},isCopyable:function(t){var e=["HistoryDatasetAssociation","HistoryDatasetCollectionAssociation"];return _.isObject(t)&&t.id&&_.contains(e,t.model_class)},copy:function(t){var e,i,n;_.isString(t)?(e=t,n="hda",i="dataset"):(e=t.id,n={HistoryDatasetAssociation:"hda",LibraryDatasetDatasetAssociation:"ldda",HistoryDatasetCollectionAssociation:"hdca"}[t.model_class]||"hda",i="hdca"===n?"dataset_collection":"dataset");var o=this,r=jQuery.ajax(this.url(),{method:"POST",contentType:"application/json",data:JSON.stringify({content:e,source:n,type:i})}).done(function(t){o.add([t],{parse:!0})}).fail(function(t,s,a){o.trigger("error",o,r,{},"Error copying contents",{type:i,id:e,source:n})});return r},createHDCA:function(t,e,i,n,o){return this.model({history_content_type:"dataset_collection",collection_type:e,history_id:this.historyId,name:i,hide_source_items:n||!1,element_identifiers:t}).save(o)},haveSearchDetails:function(){return this.allFetched&&this.all(function(t){return _.has(t.attributes,"annotation")})},matches:function(t){return this.filter(function(e){return e.matches(t)})},clone:function(){var t=Backbone.Collection.prototype.clone.call(this);return t.historyId=this.historyId,t},toString:function(){return["HistoryContents(",[this.historyId,this.length].join(),")"].join("")}});t.default={HistoryContents:v}});
//# sourceMappingURL=../../../maps/mvc/history/history-contents.js.map
