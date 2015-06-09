define(["utils/utils","mvc/tools/tools-form-workflow","mvc/workflow/workflow-objects"],function(a,b,c){function d(a){this.collectionType=a,this.isCollection=!0,this.rank=a.split(":").length}function f(a,b){this.canvas=null,this.dragging=!1,this.inner_color="#FFFFFF",this.outer_color="#D8B365",a&&b&&this.connect(a,b)}function g(a){this.canvas_container=a,this.id_counter=0,this.nodes={},this.name=null,this.has_changes=!1,this.active_form_has_changes=!1}function h(a,b,d){var e=$("<div class='toolForm toolFormInCanvas'></div>"),f=new C({element:e});f.type=a,"tool"==a&&(f.tool_id=d);var g=$("<div class='toolFormTitle unselectable'>"+b+"</div>");e.append(g),e.css("left",$(window).scrollLeft()+20),e.css("top",$(window).scrollTop()+20);var h=$("<div class='toolFormBody'></div>"),i="<div><img height='16' align='middle' src='"+galaxy_config.root+"static/images/loading_small_white_bg.gif'/> loading tool info...</div>";h.append(i),f.form_html=i,e.append(h);var j=$("<div class='buttons' style='float: right;'></div>");j.append($("<div>").addClass("fa-icon-button fa fa-times").click(function(){f.destroy()})),e.appendTo("#canvas-container");var k=$("#canvas-container").position(),l=$("#canvas-container").parent(),m=e.width(),n=e.height();return e.css({left:-k.left+l.width()/2-m/2,top:-k.top+l.height()/2-n/2}),j.prependTo(g),m+=j.width()+10,e.css("width",m),$(e).bind("dragstart",function(){c.workflow.activate_node(f)}).bind("dragend",function(){c.workflow.node_changed(this),c.workflow.fit_canvas_to_nodes(),c.canvas_manager.draw_overview()}).bind("dragclickonly",function(){c.workflow.activate_node(f)}).bind("drag",function(a,b){var c=$(this).offsetParent().offset(),d=b.offsetX-c.left,e=b.offsetY-c.top;$(this).css({left:d,top:e}),$(this).find(".terminal").each(function(){this.terminal.redraw()})}),f}function i(a,b){return a=D[a],b=D[b],E[a]&&b in E[a]}function j(a){D=a.ext_to_class_name,E=a.class_to_classes}function k(a){this.panel=a}function l(a,b){this.cv=a,this.cc=this.cv.find("#canvas-container"),this.oc=b.find("#overview-canvas"),this.ov=b.find("#overview-viewport"),this.init_drag()}$.extend(d.prototype,{append:function(a){return a===NULL_COLLECTION_TYPE_DESCRIPTION?this:a===ANY_COLLECTION_TYPE_DESCRIPTION?otherCollectionType:new d(this.collectionType+":"+a.collectionType)},canMatch:function(a){return a===NULL_COLLECTION_TYPE_DESCRIPTION?!1:a===ANY_COLLECTION_TYPE_DESCRIPTION?!0:a.collectionType==this.collectionType},canMapOver:function(a){if(a===NULL_COLLECTION_TYPE_DESCRIPTION)return!1;if(a===ANY_COLLECTION_TYPE_DESCRIPTION)return!1;if(this.rank<=a.rank)return!1;var b=a.collectionType;return this._endsWith(this.collectionType,b)},effectiveMapOver:function(a){var b=a.collectionType,c=this.collectionType.substring(0,this.collectionType.length-b.length-1);return new d(c)},equal:function(a){return a.collectionType==this.collectionType},toString:function(){return"CollectionType["+this.collectionType+"]"},_endsWith:function(a,b){return-1!==a.indexOf(b,a.length-b.length)}}),NULL_COLLECTION_TYPE_DESCRIPTION={isCollection:!1,canMatch:function(){return!1},canMapOver:function(){return!1},toString:function(){return"NullCollectionType[]"},append:function(a){return a},equal:function(a){return a===this}},ANY_COLLECTION_TYPE_DESCRIPTION={isCollection:!0,canMatch:function(a){return NULL_COLLECTION_TYPE_DESCRIPTION!==a},canMapOver:function(){return!1},toString:function(){return"AnyCollectionType[]"},append:function(){throw"Cannot append to ANY_COLLECTION_TYPE_DESCRIPTION"},equal:function(a){return a===this}};var m=Backbone.Model.extend({initialize:function(a){this.mapOver=a.mapOver||NULL_COLLECTION_TYPE_DESCRIPTION,this.terminal=a.terminal,this.terminal.terminalMapping=this},disableMapOver:function(){this.setMapOver(NULL_COLLECTION_TYPE_DESCRIPTION)},setMapOver:function(a){this.mapOver=a,this.trigger("change")}}),n=Backbone.View.extend({tagName:"div",className:"fa-icon-button fa fa-folder-o",initialize:function(){var a="Run tool in parallel over collection";this.$el.tooltip({delay:500,title:a}),this.model.bind("change",_.bind(this.render,this))},render:function(){this.model.mapOver.isCollection?this.$el.show():this.$el.hide()}}),o=n.extend({events:{click:"onClick",mouseenter:"onMouseEnter",mouseleave:"onMouseLeave"},onMouseEnter:function(){var a=this.model;!a.terminal.connected()&&a.mapOver.isCollection&&this.$el.css("color","red")},onMouseLeave:function(){this.$el.css("color","black")},onClick:function(){var a=this.model;!a.terminal.connected()&&a.mapOver.isCollection&&a.terminal.resetMapping()}}),p=m,q=m,r=m,s=n,t=o,u=m,v=n,w=Backbone.Model.extend({initialize:function(a){this.element=a.element,this.connectors=[]},connect:function(a){this.connectors.push(a),this.node&&this.node.markChanged()},disconnect:function(a){this.connectors.splice($.inArray(a,this.connectors),1),this.node&&(this.node.markChanged(),this.resetMappingIfNeeded())},redraw:function(){$.each(this.connectors,function(a,b){b.redraw()})},destroy:function(){$.each(this.connectors.slice(),function(a,b){b.destroy()})},destroyInvalidConnections:function(){_.each(this.connectors,function(a){a.destroyIfInvalid()})},setMapOver:function(a){this.multiple||this.mapOver().equal(a)||(this.terminalMapping.setMapOver(a),_.each(this.node.output_terminals,function(b){b.setMapOver(a)}))},mapOver:function(){return this.terminalMapping?this.terminalMapping.mapOver:NULL_COLLECTION_TYPE_DESCRIPTION},isMappedOver:function(){return this.terminalMapping&&this.terminalMapping.mapOver.isCollection},resetMapping:function(){this.terminalMapping.disableMapOver()},resetMappingIfNeeded:function(){}}),x=w.extend({initialize:function(a){w.prototype.initialize.call(this,a),this.datatypes=a.datatypes},resetMappingIfNeeded:function(){this.node.hasConnectedOutputTerminals()||this.node.hasConnectedMappedInputTerminals()||_.each(this.node.mappedInputTerminals(),function(a){a.resetMappingIfNeeded()});var a=!this.node.hasMappedOverInputTerminals();a&&this.resetMapping()},resetMapping:function(){this.terminalMapping.disableMapOver(),_.each(this.connectors,function(a){var b=a.handle2;b&&(b.resetMappingIfNeeded(),a.destroyIfInvalid())})}}),y=w.extend({initialize:function(a){w.prototype.initialize.call(this,a),this.update(a.input)},canAccept:function(a){return this._inputFilled()?!1:this.attachable(a)},resetMappingIfNeeded:function(){var a=this.mapOver();if(a.isCollection){var b=this.node.hasConnectedMappedInputTerminals()||!this.node.hasConnectedOutputTerminals();b&&this.resetMapping()}},resetMapping:function(){this.terminalMapping.disableMapOver(),this.node.hasMappedOverInputTerminals()||_.each(this.node.output_terminals,function(a){a.resetMapping()})},connected:function(){return 0!==this.connectors.length},_inputFilled:function(){var a;return this.connected()?this.multiple?this._collectionAttached()?inputsFilled=!0:a=!1:a=!0:a=!1,a},_collectionAttached:function(){if(this.connected()){var a=this.connectors[0].handle1;return a&&(a.isCollection||a.isMappedOver()||a.datatypes.indexOf("input_collection")>0)?!0:!1}return!1},_mappingConstraints:function(){if(!this.node)return[];var a=this.mapOver();if(a.isCollection)return[a];var b=[];return this.node.hasConnectedOutputTerminals()?b.push(_.first(_.values(this.node.output_terminals)).mapOver()):_.each(this.node.connectedMappedInputTerminals(),function(a){b.push(a.mapOver())}),b},_producesAcceptableDatatype:function(a){for(var b in this.datatypes){var c=new Array;if(c=c.concat(a.datatypes),a.node.post_job_actions)for(var d in a.node.post_job_actions){var e=a.node.post_job_actions[d];"ChangeDatatypeAction"!=e.action_type||""!=e.output_name&&e.output_name!=a.name||!e.action_arguments||c.push(e.action_arguments.newtype)}for(var f in c){var g=c[f];if("input"==g||"input_collection"==g||i(c[f],this.datatypes[b]))return!0}}return!1},_otherCollectionType:function(a){var b=NULL_COLLECTION_TYPE_DESCRIPTION;a.isCollection&&(b=a.collectionType);var c=a.mapOver();return c.isCollection&&(b=c.append(b)),b}}),z=y.extend({update:function(a){this.datatypes=a.extensions,this.multiple=a.multiple,this.collection=!1},connect:function(a){y.prototype.connect.call(this,a);var b=a.handle1;if(b){var c=this._otherCollectionType(b);c.isCollection&&this.setMapOver(c)}},attachable:function(a){var b=this._otherCollectionType(a),c=this.mapOver();if(b.isCollection){if(this.multiple)return this.connected()&&!this._collectionAttached()?!1:1==b.rank?this._producesAcceptableDatatype(a):!1;if(c.isCollection&&c.canMatch(b))return this._producesAcceptableDatatype(a);var d=this._mappingConstraints();return d.every(_.bind(b.canMatch,b))?this._producesAcceptableDatatype(a):!1}return c.isCollection?!1:this._producesAcceptableDatatype(a)}}),A=y.extend({update:function(a){this.multiple=!1,this.collection=!0,this.datatypes=a.extensions,this.collectionType=a.collection_type?new d(a.collection_type):ANY_COLLECTION_TYPE_DESCRIPTION},connect:function(a){y.prototype.connect.call(this,a);var b=a.handle1;if(b){var c=this._effectiveMapOver(b);this.setMapOver(c)}},_effectiveMapOver:function(a){var b=this.collectionType,c=this._otherCollectionType(a);return b.canMatch(c)?NULL_COLLECTION_TYPE_DESCRIPTION:c.effectiveMapOver(b)},_effectiveCollectionType:function(){var a=this.collectionType,b=this.mapOver();return b.append(a)},attachable:function(a){var b=this._otherCollectionType(a);if(b.isCollection){var c=this._effectiveCollectionType(),d=this.mapOver();if(c.canMatch(b))return this._producesAcceptableDatatype(a);if(d.isCollection)return!1;if(b.canMapOver(this.collectionType)){var e=this._effectiveMapOver(a);if(!e.isCollection)return!1;var f=this._mappingConstraints();if(f.every(e.canMatch))return this._producesAcceptableDatatype(a)}}return!1}}),B=x.extend({initialize:function(a){w.prototype.initialize.call(this,a),this.datatypes=a.datatypes,this.collectionType=new d(a.collection_type),this.isCollection=!0},update:function(a){var b=new d(a.collection_type);b.collectionType!=this.collectionType.collectionType&&_.each(this.connectors,function(a){a.destroy()}),this.collectionType=b}});$.extend(f.prototype,{connect:function(a,b){this.handle1=a,this.handle1&&this.handle1.connect(this),this.handle2=b,this.handle2&&this.handle2.connect(this)},destroy:function(){this.handle1&&this.handle1.disconnect(this),this.handle2&&this.handle2.disconnect(this),$(this.canvas).remove()},destroyIfInvalid:function(){this.handle1&&this.handle2&&!this.handle2.attachable(this.handle1)&&this.destroy()},redraw:function(){var a=$("#canvas-container");this.canvas||(this.canvas=document.createElement("canvas"),window.G_vmlCanvasManager&&G_vmlCanvasManager.initElement(this.canvas),a.append($(this.canvas)),this.dragging&&(this.canvas.style.zIndex="300"));var b=function(b){return $(b).offset().left-a.offset().left},c=function(b){return $(b).offset().top-a.offset().top};if(this.handle1&&this.handle2){var d=b(this.handle1.element)+5,e=c(this.handle1.element)+5,f=b(this.handle2.element)+5,g=c(this.handle2.element)+5,h=100,i=Math.min(d,f),j=Math.max(d,f),k=Math.min(e,g),l=Math.max(e,g),m=Math.min(Math.max(Math.abs(l-k)/2,100),300),n=i-h,o=k-h,p=j-i+2*h,q=l-k+2*h;this.canvas.style.left=n+"px",this.canvas.style.top=o+"px",this.canvas.setAttribute("width",p),this.canvas.setAttribute("height",q),d-=n,e-=o,f-=n,g-=o;var r=(this.canvas.getContext("2d"),null),s=null,t=1;if(this.handle1&&this.handle1.isMappedOver()){var r=[-6,-3,0,3,6];t=5}else var r=[0];if(this.handle2&&this.handle2.isMappedOver()){var s=[-6,-3,0,3,6];t=5}else var s=[0];for(var u=this,v=0;t>v;v++){var w=5,x=7;(r.length>1||s.length>1)&&(w=1,x=3),u.draw_outlined_curve(d,e,f,g,m,w,x,r[v%r.length],s[v%s.length])}}},draw_outlined_curve:function(a,b,c,d,e,f,g,h,i){var h=h||0,i=i||0,j=this.canvas.getContext("2d");j.lineCap="round",j.strokeStyle=this.outer_color,j.lineWidth=g,j.beginPath(),j.moveTo(a,b+h),j.bezierCurveTo(a+e,b+h,c-e,d+i,c,d+i),j.stroke(),j.strokeStyle=this.inner_color,j.lineWidth=f,j.beginPath(),j.moveTo(a,b+h),j.bezierCurveTo(a+e,b+h,c-e,d+i,c,d+i),j.stroke()}});var C=Backbone.Model.extend({initialize:function(a){this.element=a.element,this.input_terminals={},this.output_terminals={},this.tool_errors={}},connectedOutputTerminals:function(){return this._connectedTerminals(this.output_terminals)},_connectedTerminals:function(a){var b=[];return $.each(a,function(a,c){c.connectors.length>0&&b.push(c)}),b},hasConnectedOutputTerminals:function(){var a=this.output_terminals;for(var b in a)if(a[b].connectors.length>0)return!0;return!1},connectedMappedInputTerminals:function(){return this._connectedMappedTerminals(this.input_terminals)},hasConnectedMappedInputTerminals:function(){var a=this.input_terminals;for(var b in a){var c=a[b];if(c.connectors.length>0&&c.isMappedOver())return!0}return!1},_connectedMappedTerminals:function(a){var b=[];return $.each(a,function(a,c){var d=c.mapOver();d.isCollection&&c.connectors.length>0&&b.push(c)}),b},mappedInputTerminals:function(){return this._mappedTerminals(this.input_terminals)},_mappedTerminals:function(a){var b=[];return $.each(a,function(a,c){var d=c.mapOver();d.isCollection&&b.push(c)}),b},hasMappedOverInputTerminals:function(){var a=!1;return _.each(this.input_terminals,function(b){var c=b.mapOver();c.isCollection&&(a=!0)}),a},redraw:function(){$.each(this.input_terminals,function(a,b){b.redraw()}),$.each(this.output_terminals,function(a,b){b.redraw()})},destroy:function(){$.each(this.input_terminals,function(a,b){b.destroy()}),$.each(this.output_terminals,function(a,b){b.destroy()}),c.workflow.remove_node(this),$(this.element).remove()},make_active:function(){$(this.element).addClass("toolForm-active")},make_inactive:function(){var a=this.element.get(0);!function(b){b.removeChild(a),b.appendChild(a)}(a.parentNode),$(a).removeClass("toolForm-active")},init_field_data:function(a){a.type&&(this.type=a.type),this.name=a.name,this.form_html=a.form_html,this.tool_state=a.tool_state,this.tool_errors=a.tool_errors,this.tooltip=a.tooltip?a.tooltip:"",this.annotation=a.annotation,this.post_job_actions=a.post_job_actions?a.post_job_actions:{},this.label=a.label,this.uuid=a.uuid,this.workflow_outputs=a.workflow_outputs?a.workflow_outputs:[];var b=this,d=new F({el:this.element[0],node:b});b.nodeView=d,$.each(a.data_inputs,function(a,b){d.addDataInput(b)}),a.data_inputs.length>0&&a.data_outputs.length>0&&d.addRule(),$.each(a.data_outputs,function(a,b){d.addDataOutput(b)}),d.render(),c.workflow.node_changed(this,!0)},update_field_data:function(a){var b=this;if(nodeView=b.nodeView,this.tool_state=a.tool_state,this.form_html=a.form_html,this.tool_errors=a.tool_errors,this.annotation=a.annotation,"post_job_actions"in a){var c=$.parseJSON(a.post_job_actions);this.post_job_actions=c?c:{}}b.nodeView.renderToolErrors();var d=nodeView.$("div.inputs"),e=nodeView.newInputsDiv(),f={};_.each(a.data_inputs,function(a){var c=b.nodeView.addDataInput(a,e);f[a.name]=c}),_.each(_.difference(_.values(nodeView.terminalViews),_.values(f)),function(a){a.el.terminal.destroy()}),nodeView.terminalViews=f,1==a.data_outputs.length&&"collection_type"in a.data_outputs[0]&&nodeView.updateDataOutput(a.data_outputs[0]),d.replaceWith(e),this.markChanged(),this.redraw()},error:function(a){var b=$(this.element).find(".toolFormBody");b.find("div").remove();var d="<div style='color: red; text-style: italic;'>"+a+"</div>";this.form_html=d,b.html(d),c.workflow.node_changed(this)},markChanged:function(){c.workflow.node_changed(this)}});$.extend(g.prototype,{create_node:function(a,b,d){var e=h(a,b,d);return this.add_node(e),this.fit_canvas_to_nodes(),c.canvas_manager.draw_overview(),this.activate_node(e),e},add_node:function(a){a.id=this.id_counter,a.element.attr("id","wf-node-step-"+a.id),this.id_counter++,this.nodes[a.id]=a,this.has_changes=!0,a.workflow=this},remove_node:function(a){this.active_node==a&&this.clear_active_node(),delete this.nodes[a.id],this.has_changes=!0},remove_all:function(){wf=this,$.each(this.nodes,function(a,b){b.destroy(),wf.remove_node(b)})},rectify_workflow_outputs:function(){var a=!1,b=!1;$.each(this.nodes,function(c,d){d.workflow_outputs&&d.workflow_outputs.length>0&&(a=!0),$.each(d.post_job_actions,function(a,c){"HideDatasetAction"===c.action_type&&(b=!0)})}),(a!==!1||b!==!1)&&$.each(this.nodes,function(b,d){if("tool"===d.type){var e=!1;null==d.post_job_actions&&(d.post_job_actions={},e=!0);var f=[];$.each(d.post_job_actions,function(a,b){"HideDatasetAction"==b.action_type&&f.push(a)}),f.length>0&&$.each(f,function(a,b){e=!0,delete d.post_job_actions[b]}),a&&$.each(d.output_terminals,function(a,b){var c=!0;if($.each(d.workflow_outputs,function(a,d){b.name===d&&(c=!1)}),c===!0){e=!0;var f={action_type:"HideDatasetAction",output_name:b.name,action_arguments:{}};d.post_job_actions["HideDatasetAction"+b.name]=null,d.post_job_actions["HideDatasetAction"+b.name]=f}}),c.workflow.active_node==d&&e===!0&&c.workflow.reload_active_node()}})},to_simple:function(){var a={};return $.each(this.nodes,function(b,c){var d={};$.each(c.input_terminals,function(a,b){d[b.name]=null;var c=[];$.each(b.connectors,function(a,e){c[a]={id:e.handle1.node.id,output_name:e.handle1.name},d[b.name]=c})});var e={};c.post_job_actions&&$.each(c.post_job_actions,function(a,b){var c={action_type:b.action_type,output_name:b.output_name,action_arguments:b.action_arguments};e[b.action_type+b.output_name]=null,e[b.action_type+b.output_name]=c}),c.workflow_outputs||(c.workflow_outputs=[]);var f={id:c.id,type:c.type,tool_id:c.tool_id,tool_state:c.tool_state,tool_errors:c.tool_errors,input_connections:d,position:$(c.element).position(),annotation:c.annotation,post_job_actions:c.post_job_actions,uuid:c.uuid,label:c.label,workflow_outputs:c.workflow_outputs};a[c.id]=f}),{steps:a}},from_simple:function(a){wf=this;var b=0;wf.name=a.name;var d=!1;$.each(a.steps,function(a,c){var e=h(c.type,c.name,c.tool_id);e.init_field_data(c),c.position&&e.element.css({top:c.position.top,left:c.position.left}),e.id=c.id,wf.nodes[e.id]=e,b=Math.max(b,parseInt(a)),d||"tool"!==e.type||(e.workflow_outputs.length>0?d=!0:$.each(e.post_job_actions,function(a,b){"HideDatasetAction"===b.action_type&&(d=!0)}))}),wf.id_counter=b+1,$.each(a.steps,function(a,b){var e=wf.nodes[a];$.each(b.input_connections,function(a,b){b&&($.isArray(b)||(b=[b]),$.each(b,function(b,c){var d=wf.nodes[c.id],g=new f;g.connect(d.output_terminals[c.output_name],e.input_terminals[a]),g.redraw()}))}),d&&"tool"===e.type&&$.each(e.output_terminals,function(a,b){void 0===e.post_job_actions["HideDatasetAction"+b.name]&&(e.workflow_outputs.push(b.name),callout=$(e.element).find(".callout."+b.name),callout.find("img").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small.png"),c.workflow.has_changes=!0)})})},check_changes_in_active_form:function(){this.active_form_has_changes&&(this.has_changes=!0,$("#right-content").find("form").submit(),this.active_form_has_changes=!1)},reload_active_node:function(){if(this.active_node){var a=this.active_node;this.clear_active_node(),this.activate_node(a)}},clear_active_node:function(a){this.active_node&&(this.active_node.make_inactive(),this.active_node=null),this.show_tool_form("<div>No node selected</div>",{id:"no-node"},a)},activate_node:function(a){this.active_node!=a&&(this.check_changes_in_active_form(),this.clear_active_node(),this.show_tool_form(a.form_html,a),a.make_active(),this.active_node=a)},node_changed:function(a,b){this.has_changes=!0,this.active_node==a&&b&&(this.check_changes_in_active_form(),this.show_tool_form(a.form_html,a))},show_tool_form:function(c,d,e){var f="right-content",g=f+"-"+d.id,h=$("#"+f),i=h.find("#"+g);if(i.length>0&&0==i.find(".section-row").length&&i.remove(),0==h.find("#"+g).length){var j=$('<div id="'+g+'" class="'+f+'"/>');if(a.isJSON(c)){var k=JSON.parse(c);k.node=d,k.datatypes=datatypes,j.append(new b.View(k).$el)}else j.append(c);h.append(j)}$("."+f).hide(),h.find("#"+g).show(),h.show(),h.scrollTop(),e&&e()},layout:function(){this.check_changes_in_active_form(),this.has_changes=!0;var a={},b={};for($.each(this.nodes,function(c){void 0===a[c]&&(a[c]=0),void 0===b[c]&&(b[c]=[])}),$.each(this.nodes,function(c,d){$.each(d.input_terminals,function(c,e){$.each(e.connectors,function(c,e){var f=e.handle1.node;a[d.id]+=1,b[f.id].push(d.id)})})}),node_ids_by_level=[];;){level_parents=[];for(var c in a)0==a[c]&&level_parents.push(c);if(0==level_parents.length)break;node_ids_by_level.push(level_parents);for(var d in level_parents){var e=level_parents[d];delete a[e];for(var f in b[e])a[b[e][f]]-=1}}if(!a.length){var g=this.nodes,h=80;v_pad=30;var i=h;$.each(node_ids_by_level,function(a,b){b.sort(function(a,b){return $(g[a].element).position().top-$(g[b].element).position().top});var c=0,d=v_pad;$.each(b,function(a,b){var e=g[b],f=$(e.element);$(f).css({top:d,left:i}),c=Math.max(c,$(f).width()),d+=$(f).height()+v_pad}),i+=c+h}),$.each(g,function(a,b){b.redraw()})}},bounds_for_all_nodes:function(){var a,b=1/0,c=-(1/0),d=1/0,f=-(1/0);return $.each(this.nodes,function(g,h){e=$(h.element),a=e.position(),b=Math.min(b,a.left),c=Math.max(c,a.left+e.width()),d=Math.min(d,a.top),f=Math.max(f,a.top+e.width())}),{xmin:b,xmax:c,ymin:d,ymax:f}},fit_canvas_to_nodes:function(){function a(a,b){return Math.ceil(a/b)*b}function b(a,b){return b>a||a>3*b?(new_pos=(Math.ceil(a%b/b)+1)*b,-(a-new_pos)):0}var c=this.bounds_for_all_nodes(),d=this.canvas_container.position(),e=this.canvas_container.parent(),f=b(c.xmin,100),g=b(c.ymin,100);f=Math.max(f,d.left),g=Math.max(g,d.top);var h=d.left-f,i=d.top-g,j=a(c.xmax+100,100)+f,k=a(c.ymax+100,100)+g;j=Math.max(j,-h+e.width()),k=Math.max(k,-i+e.height()),this.canvas_container.css({left:h,top:i,width:j,height:k}),this.canvas_container.children().each(function(){var a=$(this).position();$(this).css("left",a.left+f),$(this).css("top",a.top+g)})}});var D=null,E=null,F=Backbone.View.extend({initialize:function(a){this.node=a.node,this.output_width=Math.max(150,this.$el.width()),this.tool_body=this.$el.find(".toolFormBody"),this.tool_body.find("div").remove(),this.newInputsDiv().appendTo(this.tool_body),this.terminalViews={},this.outputTerminlViews={}},render:function(){this.renderToolErrors(),this.$el.css("width",Math.min(250,Math.max(this.$el.width(),this.output_width)))},renderToolErrors:function(){this.node.tool_errors?this.$el.addClass("tool-node-error"):this.$el.removeClass("tool-node-error")},newInputsDiv:function(){return $("<div class='inputs'></div>")},updateMaxWidth:function(a){this.output_width=Math.max(this.output_width,a)},addRule:function(){this.tool_body.append($("<div class='rule'></div>"))},addDataInput:function(a,b){var c=!0;b||(b=this.$(".inputs"),c=!1);var d=this.terminalViews[a.name],e="dataset_collection"==a.input_type?M:L;if(!d||d instanceof e||(d.el.terminal.destroy(),d=null),d){var f=d.el.terminal;f.update(a),f.destroyInvalidConnections()}else d=new e({node:this.node,input:a});this.terminalViews[a.name]=d;var g=d.el,h=new G({terminalElement:g,input:a,nodeView:this,skipResize:c}),i=h.$el;return b.append(i.prepend(d.terminalElements())),d},addDataOutput:function(a){var b=a.collection?P:O,c=new b({node:this.node,output:a}),d=new I({output:a,terminalElement:c.el,nodeView:this});this.tool_body.append(d.$el.append(c.terminalElements()))},updateDataOutput:function(a){var b=this.node.output_terminals[a.name];b.update(a)}}),G=Backbone.View.extend({className:"form-row dataRow input-data-row",initialize:function(a){this.input=a.input,this.nodeView=a.nodeView,this.terminalElement=a.terminalElement,this.$el.attr("name",this.input.name).html(this.input.label),a.skipResize||(this.$el.css({position:"absolute",left:-1e3,top:-1e3,display:"none"}),$("body").append(this.el),this.nodeView.updateMaxWidth(this.$el.outerWidth()),this.$el.css({position:"",left:"",top:"",display:""}),this.$el.remove())}}),H=Backbone.View.extend({tagName:"div",initialize:function(a){this.label=a.label,this.node=a.node,this.output=a.output;var b=this;this.$el.attr("class","callout "+this.label).css({display:"none"}).append($("<div class='buttons'></div>").append($("<img/>").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small-outline.png").click(function(){-1!=$.inArray(b.output.name,b.node.workflow_outputs)?(b.node.workflow_outputs.splice($.inArray(b.output.name,b.node.workflow_outputs),1),b.$("img").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small-outline.png")):(b.node.workflow_outputs.push(b.output.name),b.$("img").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small.png")),c.workflow.has_changes=!0,c.canvas_manager.draw_overview()}))).tooltip({delay:500,title:"Mark dataset as a workflow output. All unmarked datasets will be hidden."}),this.$el.css({top:"50%",margin:"-8px 0px 0px 0px",right:8}),this.$el.show(),this.resetImage()},resetImage:function(){-1===$.inArray(this.output.name,this.node.workflow_outputs)?this.$("img").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small-outline.png"):this.$("img").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small.png")},hoverImage:function(){this.$("img").attr("src",galaxy_config.root+"static/images/fugue/asterisk-small-yellow.png")}}),I=Backbone.View.extend({className:"form-row dataRow",initialize:function(a){this.output=a.output,this.terminalElement=a.terminalElement,this.nodeView=a.nodeView;var b=this.output,c=b.name,d=this.nodeView.node,e=b.extensions.indexOf("input")>=0||b.extensions.indexOf("input_collection")>=0;if(e||(c=c+" ("+b.extensions.join(", ")+")"),this.$el.html(c),"tool"==d.type){var f=new H({label:c,output:b,node:d});this.$el.append(f.el),this.$el.hover(function(){f.hoverImage()},function(){f.resetImage()})}this.$el.css({position:"absolute",left:-1e3,top:-1e3,display:"none"}),$("body").append(this.el),this.nodeView.updateMaxWidth(this.$el.outerWidth()+17),this.$el.css({position:"",left:"",top:"",display:""}).detach()}}),J=Backbone.View.extend({setupMappingView:function(a){var b=new this.terminalMappingClass({terminal:a}),c=new this.terminalMappingViewClass({model:b});c.render(),a.terminalMappingView=c,this.terminalMappingView=c},terminalElements:function(){return this.terminalMappingView?[this.terminalMappingView.el,this.el]:[this.el]}}),K=J.extend({className:"terminal input-terminal",initialize:function(a){var b=a.node,c=a.input,d=c.name,e=this.terminalForInput(c);e.multiple||this.setupMappingView(e),this.el.terminal=e,e.node=b,e.name=d,b.input_terminals[d]=e},events:{dropinit:"onDropInit",dropstart:"onDropStart",dropend:"onDropEnd",drop:"onDrop",hover:"onHover"},onDropInit:function(a,b){var c=this.el.terminal;return $(b.drag).hasClass("output-terminal")&&c.canAccept(b.drag.terminal)},onDropStart:function(a,b){b.proxy.terminal&&(b.proxy.terminal.connectors[0].inner_color="#BBFFBB")},onDropEnd:function(a,b){b.proxy.terminal&&(b.proxy.terminal.connectors[0].inner_color="#FFFFFF")},onDrop:function(a,b){var c=this.el.terminal;new f(b.drag.terminal,c).redraw()},onHover:function(){var a=this.el,b=a.terminal;if(b.connectors.length>0){var c=$("<div class='callout'></div>").css({display:"none"}).appendTo("body").append($("<div class='button'></div>").append($("<div/>").addClass("fa-icon-button fa fa-times").click(function(){$.each(b.connectors,function(a,b){b&&b.destroy()}),c.remove()}))).bind("mouseleave",function(){$(this).remove()});c.css({top:$(a).offset().top-2,left:$(a).offset().left-c.width(),"padding-right":$(a).width()}).show()}}}),L=K.extend({terminalMappingClass:p,terminalMappingViewClass:o,terminalForInput:function(a){return new z({element:this.el,input:a})}}),M=K.extend({terminalMappingClass:q,terminalMappingViewClass:t,terminalForInput:function(a){return new A({element:this.el,input:a})}}),N=J.extend({className:"terminal output-terminal",initialize:function(a){var b=a.node,c=a.output,d=c.name,e=this.terminalForOutput(c);this.setupMappingView(e),this.el.terminal=e,e.node=b,e.name=d,b.output_terminals[d]=e},events:{drag:"onDrag",dragstart:"onDragStart",dragend:"onDragEnd"},onDrag:function(a,b){var d=function(){var a=$(b.proxy).offsetParent().offset(),d=b.offsetX-a.left,e=b.offsetY-a.top;$(b.proxy).css({left:d,top:e}),b.proxy.terminal.redraw(),c.canvas_manager.update_viewport_overlay()};d(),$("#canvas-container").get(0).scroll_panel.test(a,d)},onDragStart:function(a,b){$(b.available).addClass("input-terminal-active"),c.workflow.check_changes_in_active_form();var d=$('<div class="drag-terminal" style="position: absolute;"></div>').appendTo("#canvas-container").get(0);d.terminal=new x({element:d});var e=new f;return e.dragging=!0,e.connect(this.el.terminal,d.terminal),d},onDragEnd:function(a,b){var c=b.proxy.terminal.connectors[0];c&&c.destroy(),$(b.proxy).remove(),$(b.available).removeClass("input-terminal-active"),$("#canvas-container").get(0).scroll_panel.stop()}}),O=N.extend({terminalMappingClass:r,terminalMappingViewClass:s,terminalForOutput:function(a){var b=a.extensions,c=new x({element:this.el,datatypes:b});return c}}),P=N.extend({terminalMappingClass:u,terminalMappingViewClass:v,terminalForOutput:function(a){var b=a.collection_type,c=new B({element:this.el,collection_type:b,datatypes:a.extensions});return c}});return $.extend(k.prototype,{test:function(a,b){clearTimeout(this.timeout);var c=a.pageX,d=a.pageY,e=$(this.panel),f=e.position(),g=e.width(),h=e.height(),i=e.parent(),j=i.width(),k=i.height(),l=i.offset(),m=l.left,n=l.top,o=m+i.width(),p=n+i.height(),q=-(g-j/2),r=-(h-k/2),s=j/2,t=k/2,u=!1,v=5,w=23;if(m>c-v){if(f.left<s){var x=Math.min(w,s-f.left);e.css("left",f.left+x),u=!0}}else if(c+v>o){if(f.left>q){var x=Math.min(w,f.left-q);e.css("left",f.left-x),u=!0}}else if(n>d-v){if(f.top<t){var x=Math.min(w,t-f.top);e.css("top",f.top+x),u=!0}}else if(d+v>p&&f.top>r){var x=Math.min(w,f.top-q);e.css("top",f.top-x+"px"),u=!0}if(u){b();var e=this;this.timeout=setTimeout(function(){e.test(a,b)},50)}},stop:function(){clearTimeout(this.timeout)}}),$.extend(l.prototype,{init_drag:function(){var a=this,b=function(b,c){b=Math.min(b,a.cv.width()/2),b=Math.max(b,-a.cc.width()+a.cv.width()/2),c=Math.min(c,a.cv.height()/2),c=Math.max(c,-a.cc.height()+a.cv.height()/2),a.cc.css({left:b,top:c}),a.cv.css({"background-position-x":b,"background-position-y":c}),a.update_viewport_overlay()};this.cc.each(function(){this.scroll_panel=new k(this)});var d,e;this.cv.bind("dragstart",function(){var b=$(this).offset(),c=a.cc.position();e=c.top-b.top,d=c.left-b.left}).bind("drag",function(a,c){b(c.offsetX+d,c.offsetY+e)}).bind("dragend",function(){c.workflow.fit_canvas_to_nodes(),a.draw_overview()}),this.ov.bind("drag",function(c,d){var e=a.cc.width(),f=a.cc.height(),g=a.oc.width(),h=a.oc.height(),i=$(this).offsetParent().offset(),j=d.offsetX-i.left,k=d.offsetY-i.top;b(-(j/g*e),-(k/h*f))}).bind("dragend",function(){c.workflow.fit_canvas_to_nodes(),a.draw_overview()}),$("#overview-border").bind("drag",function(b,c){var d=$(this).offsetParent(),e=d.offset(),f=Math.max(d.width()-(c.offsetX-e.left),d.height()-(c.offsetY-e.top));$(this).css({width:f,height:f}),a.draw_overview()}),$("#overview-border div").bind("drag",function(){})},update_viewport_overlay:function(){var a=this.cc,b=this.cv,c=this.oc,d=this.ov,e=a.width(),f=a.height(),g=c.width(),h=c.height(),i=a.position();d.css({left:-(i.left/e*g),top:-(i.top/f*h),width:b.width()/e*g-2,height:b.height()/f*h-2})},draw_overview:function(){var a,b,d,e,f=$("#overview-canvas"),g=f.parent().parent().width(),h=f.get(0).getContext("2d"),i=$("#canvas-container").width(),j=$("#canvas-container").height(),k=this.cv.width(),l=this.cv.height();k>i&&l>j?(d=i/k*g,e=(g-d)/2,a=j/l*g,b=(g-a)/2):j>i?(b=0,a=g,d=Math.ceil(a*i/j),e=(g-d)/2):(d=g,e=0,a=Math.ceil(d*j/i),b=(g-a)/2),f.parent().css({left:e,top:b,width:d,height:a}),f.attr("width",d),f.attr("height",a),$.each(c.workflow.nodes,function(b,c){h.fillStyle="#D2C099",h.strokeStyle="#D8B365",h.lineWidth=1;var e=$(c.element),f=e.position(),g=f.left/i*d,k=f.top/j*a,l=e.width()/i*d,m=e.height()/j*a;c.tool_errors?(h.fillStyle="#FFCCCC",h.strokeStyle="#AA6666"):void 0!=c.workflow_outputs&&c.workflow_outputs.length>0&&(h.fillStyle="#E8A92D",
h.strokeStyle="#E8A92D"),h.fillRect(g,k,l,m),h.strokeRect(g,k,l,m)}),this.update_viewport_overlay()}}),{CanvasManager:l,Workflow:g,populate_datatype_info:j,InputTerminal:z,OutputTerminal:x,InputCollectionTerminal:A,OutputCollectionTerminal:B,InputTerminalView:L,OutputTerminalView:O,InputCollectionTerminalView:M,OutputCollectionTerminalView:P,InputTerminalMapping:p,OutputTerminalMapping:r,InputCollectionTerminalMapping:p,OutputCollectionTerminalMapping:u,Connector:f,CollectionTypeDescription:d,TerminalMapping:m,NULL_COLLECTION_TYPE_DESCRIPTION:NULL_COLLECTION_TYPE_DESCRIPTION,ANY_COLLECTION_TYPE_DESCRIPTION:ANY_COLLECTION_TYPE_DESCRIPTION,Node:C,NodeView:F}});
//# sourceMappingURL=../../../maps/mvc/workflow/workflow-manager.js.map