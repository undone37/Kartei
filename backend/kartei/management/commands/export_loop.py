"""Long-running exporter: runs auto exports, purges the recycle bin, syncs Outlook and AD, pushes to the CardDAV relay.
Interval is read from Settings each loop; an Outlook, AD or relay "sync now" request is picked up within POLL seconds."""
import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from kartei import adsync, audit, exports, graph, ldapusers, relaypush, reviews
from kartei.models import ExportProfile, Record, Settings

log = logging.getLogger(__name__)
POLL = 10


def tick():
    s = Settings.get()
    for p in ExportProfile.objects.filter(enabled=True, schedule="auto"):
        log.info("export %s: %s", p.name, exports.run(p))
    if s.trash_days:
        for r in Record.objects.filter(deleted_at__lt=timezone.now() - timedelta(days=s.trash_days)):
            audit.log(None, "purge", "record", r.uid, r.display_name, {"reason": [None, f"trash_days={s.trash_days}"]})
            r.delete()
    started, mailed = reviews.tick()
    if started or mailed:
        log.info("reviews: started %s, mails %s", started, mailed)
    if (status := graph.run()) is not None:
        log.info("outlook sync: %s", status)
    if ldapusers.due(s):
        log.info("ldap user import: %s", ldapusers.run())
    if (status := adsync.run()) is not None:
        log.info("ad sync: %s", status)
    if (status := relaypush.run()) is not None:
        log.info("carddav relay push: %s", status)
    return s.export_interval_minutes


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, once=False, **opts):
        while True:
            close_old_connections()
            try:
                minutes = tick()
            except Exception:  # keep the loop alive; next tick retries
                log.exception("export loop failed")
                minutes = 5
            if once:
                return
            deadline = time.monotonic() + max(minutes, 1) * 60
            while time.monotonic() < deadline:
                time.sleep(POLL)
                close_old_connections()
                try:
                    if Settings.objects.filter(pk=1, graph_sync_requested__isnull=False).exists():
                        log.info("outlook sync (requested): %s", graph.run())
                except Exception:
                    log.exception("outlook sync failed")
                try:
                    if Settings.objects.filter(pk=1, ad_sync_requested__isnull=False).exists():
                        log.info("ad sync (requested): %s", adsync.run())
                except Exception:
                    log.exception("ad sync failed")
                try:
                    if Settings.objects.filter(pk=1, carddav_relay_requested__isnull=False).exists():
                        log.info("carddav relay push (requested): %s", relaypush.run())
                except Exception:
                    log.exception("carddav relay push failed")
