from connexion import App
from connexion.resolver import RestyResolver

from specsynthase.specbuilder import SpecBuilder

from .controller import DRS_SPEC


class RewriteRestyResolver(RestyResolver):


    def resolve_operation_id(self, operation):
        """
        Resolves the operationId using REST semantics unless explicitly configured in the spec
        :type operation: connexion.operations.AbstractOperation
        """
        operation = self._rewrite_operation(operation)
        return super(RewriteRestyResolver, self).resolve_operation_id(operation)

    def resolve_operation_id_using_rest_semantics(self, operation):
        operation = self._rewrite_operation(operation)
        return super(RewriteRestyResolver, self).resolve_operation_id_using_rest_semantics(operation)

    def _rewrite_operation(self, operation):
        operation._router_controller = "galaxy.job_data.controller"
        return operation


# use the swagger spec to define the flaskapp
app = App(__name__, resolver=RewriteRestyResolver('api'), options=dict(swagger_ui=True, swagger_json=True))


def configure_app(app):
    """Configure app"""

    specs = SpecBuilder()\
            .add_spec(DRS_SPEC)
    app.add_api(
        specs,
        validate_responses=True,
        strict_validation=True,
    )

    return app


def main():
    _app = configure_app(app)

    # run app
    _app.run()


if __name__ == "__main__":
    main()
