from fastapi import APIRouter

from ..config import settings as settings  # noqa: F401
from ..jobs import enqueue_import_job as enqueue_import_job  # noqa: F401
from . import import_uploads, erp_integration, import_workflow, user_management, single_sign_on, role_management, tenant_settings, custom_fields, data_management, notification_settings, reporting, organization_settings, onboarding


router = APIRouter(tags=['imports-settings'])

# Compatibility surface for direct internal imports while implementations live
# in domain-specific modules.  Import workspaces remain rooted at
# Path(".workspace") / "imports" in import_uploads.py.
_DOMAIN_MODULES = (
    import_uploads,
    erp_integration,
    import_workflow,
    user_management,
    single_sign_on,
    role_management,
    tenant_settings,
    custom_fields,
    data_management,
    notification_settings,
    reporting,
    organization_settings,
    onboarding,
)


def __getattr__(name: str):
    """Preserve the legacy module-level helper and endpoint import surface."""
    for module in _DOMAIN_MODULES:
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Preserve the legacy router registration order so the generated OpenAPI document is byte-stable.
router.routes.extend(import_uploads.router.routes)
router.routes.extend(erp_integration.router.routes)
router.routes.extend(import_workflow.router.routes)
router.routes.extend(user_management.router.routes[:9])
router.routes.extend(single_sign_on.router.routes)
router.routes.extend(user_management.router.routes[9:])
router.routes.extend(role_management.router.routes)
router.routes.extend(tenant_settings.router.routes)
router.routes.extend(custom_fields.router.routes)
router.routes.extend(data_management.router.routes)
router.routes.extend(notification_settings.router.routes)
router.routes.extend(reporting.router.routes)
router.routes.extend(organization_settings.router.routes)
router.routes.extend(onboarding.router.routes)
