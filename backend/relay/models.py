from django.db import models


class Card(models.Model):
    """One contact as Kartei rendered it, in both vCard flavours. Nothing else about the contact reaches the DMZ."""
    uid = models.UUIDField(primary_key=True)
    etag = models.CharField(max_length=80)
    ios = models.TextField()
    android = models.TextField()
    # sync-collection: when the card last changed; deleted cards stay as tombstones for TOMBSTONE_DAYS
    changed_at = models.DateTimeField(auto_now=True, db_index=True)
    deleted = models.BooleanField(default=False)


class Book(models.Model):
    """Singleton (pk=1): address book version and the CardDAV login, both pushed by Kartei."""
    ctag = models.CharField(max_length=40, default="0")
    username = models.CharField(max_length=150, blank=True)
    password_hash = models.CharField(max_length=255, blank=True)  # Django password hash; empty = nobody gets in
    pushed_at = models.DateTimeField(null=True, blank=True)
    tombstones_since = models.DateTimeField(null=True, blank=True)  # removals before this are forgotten

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]
