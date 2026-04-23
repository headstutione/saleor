from django.conf import settings

from ....celeryconf import app
from ....core.db.connection import allow_writer


@app.task(queue=settings.DATA_MIGRATIONS_TASKS_QUEUE_NAME)
@allow_writer()
def fill_app_extension_settings_task():
    # No-op: the AppExtension.http_target_method field has been removed.
    # Retained so migration 0035_app_extensions_mount_target_settings_reshape can
    # still import it via post_migrate signal handler.
    return
