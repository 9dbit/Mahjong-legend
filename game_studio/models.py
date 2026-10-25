"""Durable versions, tickets and append-only settlement records."""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q

class ConfigurationVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20)
    digest = models.CharField(max_length=64)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'digest'], name='studio_version_hash_unique')]

class Release(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    digest = models.CharField(max_length=64, unique=True)
    config = models.JSONField()
    versions = models.JSONField(default=dict)
    engine_hash = models.CharField(max_length=64)
    validation = models.JSONField(default=dict)
    preview = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        permissions = [('edit_studio', 'Edit Studio drafts and assets'),
                       ('publish_release', 'Publish and roll back releases'),
                       ('test_studio', 'Preview and run Math Lab')]

class ActiveRelease(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    release = models.ForeignKey(Release, on_delete=models.PROTECT)
    generation = models.PositiveIntegerField(default=1)
    changed_at = models.DateTimeField(auto_now=True)
    setup_used = models.BooleanField(default=False)

class Draft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    revision = models.PositiveIntegerField(default=1)
    config = models.JSONField()
    validation = models.JSONField(default=dict)
    base_release = models.ForeignKey(Release, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Asset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    kind = models.CharField(max_length=12)
    status = models.CharField(max_length=12, default='pending')
    object_key = models.CharField(max_length=240)
    sha256 = models.CharField(max_length=64)
    mime = models.CharField(max_length=80, default='application/octet-stream')
    byte_size = models.PositiveIntegerField()
    metadata = models.JSONField(default=dict)
    recipe = models.JSONField(default=dict)
    original = models.ForeignKey('self', null=True, on_delete=models.PROTECT)
    is_derivative = models.BooleanField(default=False)
    published = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=24)
    status = models.CharField(max_length=12, default='queued', db_index=True)
    request = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    progress = models.FloatField(default=0)
    error = models.CharField(max_length=500, blank=True)
    fence = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    cancel_requested = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    target = models.CharField(max_length=80)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class PlayerSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)
    balance = models.DecimalField(max_digits=38, decimal_places=12)
    spins = models.PositiveIntegerField(default=0)
    ticket_sequence = models.PositiveIntegerField(default=0)
    preview_release = models.ForeignKey(Release, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    touched_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(balance__gte=0), name='studio_balance_nonnegative')]

class SpinTicket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(PlayerSession, on_delete=models.PROTECT, related_name='tickets')
    sequence = models.PositiveIntegerField()
    release = models.ForeignKey(Release, on_delete=models.PROTECT)
    # Never serialized until the completed round reveals this seed.
    secret_seed = models.CharField(max_length=64)
    commitment = models.CharField(max_length=64)
    status = models.CharField(max_length=12, default='ready')
    fence = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    stake = models.CharField(max_length=40, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['session', 'sequence'], name='studio_ticket_sequence_unique'),
            models.UniqueConstraint(fields=['session'], condition=Q(status__in=['ready', 'pending']), name='studio_one_open_ticket')]

class SpinRequest(models.Model):
    session = models.ForeignKey(PlayerSession, on_delete=models.PROTECT)
    key = models.UUIDField()
    ticket = models.ForeignKey(SpinTicket, on_delete=models.PROTECT)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['session', 'key'], name='studio_idempotency_unique')]

class Round(models.Model):
    ticket = models.OneToOneField(SpinTicket, primary_key=True, on_delete=models.PROTECT)
    session = models.ForeignKey(PlayerSession, on_delete=models.PROTECT, related_name='rounds')
    release = models.ForeignKey(Release, on_delete=models.PROTECT)
    transcript = models.JSONField()
    response = models.JSONField(default=dict)
    stake = models.DecimalField(max_digits=38, decimal_places=12)
    award = models.DecimalField(max_digits=38, decimal_places=12)
    created_at = models.DateTimeField(auto_now_add=True)

class LedgerEntry(models.Model):
    session = models.ForeignKey(PlayerSession, on_delete=models.PROTECT)
    round = models.OneToOneField(Round, null=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12)
    debit = models.DecimalField(max_digits=38, decimal_places=12, default=0)
    credit = models.DecimalField(max_digits=38, decimal_places=12, default=0)
    balance_after = models.DecimalField(max_digits=38, decimal_places=12)
    created_at = models.DateTimeField(auto_now_add=True)

class AuthThrottle(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    count = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField()

class WorkerHeartbeat(models.Model):
    name = models.CharField(primary_key=True,max_length=60)
    seen_at = models.DateTimeField()
