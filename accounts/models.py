from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import make_password, check_password
from django.db import models
import random
import string


def generate_remote_id():
    """SKY-XXXXXX format ka unique ID banata hai"""
    digits = ''.join(random.choices(string.digits, k=6))
    return f"SKY-{digits}"


class CustomUser(AbstractUser):
    remote_id = models.CharField(max_length=12, unique=True, blank=True)
    is_online = models.BooleanField(default=False)

    # Unattended access PIN - login password se bilkul alag, optional.
    # Hashed store hota hai, kabhi bhi plain text nahi.
    access_pin_hash = models.CharField(max_length=128, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.remote_id:
            new_id = generate_remote_id()
            while CustomUser.objects.filter(remote_id=new_id).exists():
                new_id = generate_remote_id()
            self.remote_id = new_id
        super().save(*args, **kwargs)

    def set_access_pin(self, raw_pin):
        self.access_pin_hash = make_password(raw_pin)

    def check_access_pin(self, raw_pin):
        if not self.access_pin_hash or not raw_pin:
            return False
        return check_password(raw_pin, self.access_pin_hash)

    def clear_access_pin(self):
        self.access_pin_hash = None

    def __str__(self):
        return f"{self.username} ({self.remote_id})"



from django.utils import timezone


class ConnectionLog(models.Model):
    CONNECT_VIA_CHOICES = [
        ("pin", "PIN (Auto-Accept)"),
        ("manual", "Manual Accept"),
    ]
    STATUS_CHOICES = [
        ("ongoing", "Ongoing"),
        ("ended", "Ended"),
    ]

    session_id = models.CharField(max_length=20, unique=True)
    requester = models.ForeignKey(
        CustomUser, related_name="initiated_connections",
        on_delete=models.SET_NULL, null=True
    )
    target = models.ForeignKey(
        CustomUser, related_name="received_connections",
        on_delete=models.SET_NULL, null=True
    )
    connect_via = models.CharField(max_length=10, choices=CONNECT_VIA_CHOICES, default="manual")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="ongoing")

    def __str__(self):
        return f"{self.requester} -> {self.target} ({self.status})"