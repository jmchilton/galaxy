define(['mvc/workflow/workflow-view-terminals', 'mvc/workflow/workflow-view-data'], function( TerminalViews, DataViews ){
    return Backbone.View.extend( {
        initialize: function( options ){
            this.node = options.node;
            this.output_width = Math.max(150, this.$el.width());
            this.tool_body = this.$el.find( ".toolFormBody" );
            this.tool_body.find( "div" ).remove();
            this.newInputsDiv().appendTo( this.tool_body );
            this.terminalViews = {};
            this.outputTerminlViews = {};
        },

        render: function() {
            var label = this.node.label;
            if(label) {
                this.$el.find(".nodeTitle").text(label);
            }
            this.renderToolErrors();
            this.$el.css( "width", Math.min(250, Math.max( this.$el.width(), this.output_width )));
        },

        renderToolErrors: function( ) {
            if ( this.node.tool_errors ) {
                this.$el.addClass( "tool-node-error" );
            } else {
                this.$el.removeClass( "tool-node-error" );
            }
        },

        newInputsDiv: function() {
            return $("<div class='inputs'></div>");
        },

        updateMaxWidth: function( newWidth ) {
            this.output_width = Math.max( this.output_width, newWidth );
        },

        addRule: function() {
            this.tool_body.append( $( "<div class='rule'></div>" ) );
        },

        addDataInput: function( input, body ) {
            var skipResize = true;
            if( ! body ) {
                body = this.$( ".inputs" );
                // initial addition to node - resize input to help calculate node
                // width.
                skipResize = false;
            }
            var terminalView = this.terminalViews[ input.name ];
            var terminalViewClass = ( input.input_type == "dataset_collection" ) ? TerminalViews.InputCollectionTerminalView : TerminalViews.InputTerminalView;
            if( terminalView && ! ( terminalView instanceof terminalViewClass ) ) {
                terminalView.el.terminal.destroy();
                terminalView = null;
            }
            if( ! terminalView ) {
                terminalView = new terminalViewClass( {
                    node: this.node,
                    input: input
                } );             
            } else {
                var terminal = terminalView.el.terminal;
                terminal.update( input );
                terminal.destroyInvalidConnections();
            }
            this.terminalViews[ input.name ] = terminalView;
            var terminalElement = terminalView.el;
            var inputView = new DataViews.DataInputView( {
                terminalElement: terminalElement,
                input: input, 
                nodeView: this,
                skipResize: skipResize
            } );
            var ib = inputView.$el;
            body.append( ib.prepend( terminalView.terminalElements() ) );
            return terminalView;
        },

        addDataOutput: function( output ) {
            var terminalViewClass = ( output.collection ) ? TerminalViews.OutputCollectionTerminalView : TerminalViews.OutputTerminalView;
            var terminalView = new terminalViewClass( {
                node: this.node,
                output: output
            } );
            var outputView = new DataViews.DataOutputView( {
                "output": output,
                "terminalElement": terminalView.el,
                "nodeView": this,
            } );
            this.tool_body.append( outputView.$el.append( terminalView.terminalElements() ) );
        },

        updateDataOutput: function( output ) {
            var outputTerminal = this.node.output_terminals[ output.name ];
            outputTerminal.update( output );
        }
    });
});