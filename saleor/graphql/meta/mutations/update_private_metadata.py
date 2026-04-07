import graphene

from ....core.exceptions import PermissionDenied
from ....permission.enums import AccountPermissions
from ...core import ResolveInfo
from ...core.types import MetadataError, NonNullList
from ..inputs import MetadataInput, MetadataInputDescription
from ..permissions import PRIVATE_META_PERMISSION_MAP
from .base import BaseMetadataMutation
from .utils import get_valid_metadata_instance, update_private_metadata


class UpdatePrivateMetadata(BaseMetadataMutation):
    class Meta:
        description = (
            "Updates private metadata of an object. "
            f"{MetadataInputDescription.PRIVATE_METADATA_INPUT}"
        )
        permission_map = PRIVATE_META_PERMISSION_MAP
        error_type_class = MetadataError
        error_type_field = "metadata_errors"

    class Arguments:
        id = graphene.ID(
            description="ID or token (for Order and Checkout) of an object to update.",
            required=True,
        )
        input = NonNullList(
            MetadataInput,
            description="Fields required to update the object's metadata.",
            required=True,
        )

    @classmethod
    def check_permissions(cls, context, permissions=None, **data):  # type: ignore[override]
        is_app = bool(getattr(context, "app", None))
        if is_app and permissions and AccountPermissions.MANAGE_STAFF in permissions:
            raise PermissionDenied(
                message="Apps are not allowed to perform this mutation."
            )
        return super().check_permissions(context, permissions)

    @classmethod
    def perform_mutation(cls, _root, info: ResolveInfo, /, **data):
        instance = cls.get_instance(info, **data)

        if instance:
            meta_instance = get_valid_metadata_instance(instance)
            metadata_list = data.pop("input")

            cls.create_metadata_from_graphql_input(
                metadata_list, error_field_name="input"
            )

            items = {data.key: data.value for data in metadata_list}
            update_private_metadata(meta_instance, items)

        return cls.success_response(instance)
