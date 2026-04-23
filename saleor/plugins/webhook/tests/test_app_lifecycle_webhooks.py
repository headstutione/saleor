"""End-to-end tests for app lifecycle webhook self-receive.

Confirms an app without MANAGE_APPS permission receives its own
APP_INSTALLED, APP_UPDATED, APP_DELETED, APP_STATUS_CHANGED events.
These tests exercise the real dispatch filter — they do not mock
get_webhooks_for_event — so the bypass-on-affected-app path is
covered end-to-end.
"""

from unittest import mock

import pytest
from django.utils import timezone

from ....app.models import App
from ....webhook.event_types import WebhookEventAsyncType
from ....webhook.models import Webhook
from ...manager import get_plugins_manager


@pytest.fixture
def app_with_lifecycle_webhook(db, settings):
    settings.PLUGINS = ["saleor.plugins.webhook.plugin.WebhookPlugin"]

    def factory(event_type, *, is_active=True, removed_at=None):
        app = App.objects.create(name="Self-receive app", is_active=is_active)
        if removed_at:
            app.removed_at = removed_at
            app.save(update_fields=["removed_at"])
        webhook = Webhook.objects.create(
            name="lifecycle",
            app=app,
            target_url="http://example.com/webhook",
            is_active=True,
        )
        webhook.events.create(event_type=event_type)
        return app, webhook

    return factory


@mock.patch("saleor.plugins.webhook.plugin.trigger_webhooks_async")
def test_app_receives_own_app_installed_without_manage_apps(
    mocked_trigger, app_with_lifecycle_webhook
):
    app, webhook = app_with_lifecycle_webhook(WebhookEventAsyncType.APP_INSTALLED)
    assert not app.permissions.exists()

    manager = get_plugins_manager(allow_replica=False)
    manager.app_installed(app)

    assert mocked_trigger.called
    delivered_webhooks = mocked_trigger.call_args.args[2]
    assert webhook in list(delivered_webhooks)


@mock.patch("saleor.plugins.webhook.plugin.trigger_webhooks_async")
def test_app_receives_own_app_updated_without_manage_apps(
    mocked_trigger, app_with_lifecycle_webhook
):
    app, webhook = app_with_lifecycle_webhook(WebhookEventAsyncType.APP_UPDATED)
    assert not app.permissions.exists()

    manager = get_plugins_manager(allow_replica=False)
    manager.app_updated(app)

    assert mocked_trigger.called
    delivered_webhooks = mocked_trigger.call_args.args[2]
    assert webhook in list(delivered_webhooks)


@mock.patch("saleor.plugins.webhook.plugin.trigger_webhooks_async")
def test_app_receives_own_app_deleted_without_manage_apps(
    mocked_trigger, app_with_lifecycle_webhook
):
    """Verify self-receive for the soft-deleted app.

    The affected app is soft-deleted (is_active=False, removed_at set)
    at dispatch time, yet must still receive APP_DELETED.
    """
    app, webhook = app_with_lifecycle_webhook(
        WebhookEventAsyncType.APP_DELETED,
        is_active=False,
        removed_at=timezone.now(),
    )
    assert not app.permissions.exists()

    manager = get_plugins_manager(allow_replica=False)
    manager.app_deleted(app)

    assert mocked_trigger.called
    delivered_webhooks = mocked_trigger.call_args.args[2]
    assert webhook in list(delivered_webhooks)


@mock.patch("saleor.plugins.webhook.plugin.trigger_webhooks_async")
def test_app_receives_own_app_status_changed_on_deactivate(
    mocked_trigger, app_with_lifecycle_webhook
):
    """Verify self-receive for the deactivated app.

    A deactivated app (is_active=False) must still receive its own
    APP_STATUS_CHANGED webhook.
    """
    app, webhook = app_with_lifecycle_webhook(
        WebhookEventAsyncType.APP_STATUS_CHANGED, is_active=False
    )
    assert not app.permissions.exists()

    manager = get_plugins_manager(allow_replica=False)
    manager.app_status_changed(app)

    assert mocked_trigger.called
    delivered_webhooks = mocked_trigger.call_args.args[2]
    assert webhook in list(delivered_webhooks)


@mock.patch("saleor.plugins.webhook.plugin.trigger_webhooks_async")
def test_unrelated_app_without_manage_apps_does_not_receive_lifecycle_event(
    mocked_trigger, app_with_lifecycle_webhook
):
    """Verify bypass does not leak to unrelated apps.

    An app subscribed to APP_DELETED without MANAGE_APPS must not
    receive events about *other* apps — only its own.
    """
    affected_app = App.objects.create(name="Target", is_active=True)
    _, unrelated_webhook = app_with_lifecycle_webhook(WebhookEventAsyncType.APP_DELETED)

    manager = get_plugins_manager(allow_replica=False)
    manager.app_deleted(affected_app)

    if mocked_trigger.called:
        delivered_webhooks = list(mocked_trigger.call_args.args[2])
        assert unrelated_webhook not in delivered_webhooks
