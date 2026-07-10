from django.contrib.auth.models import AbstractUser
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

    def save(self, *args, **kwargs):
        if not self.remote_id:
            new_id = generate_remote_id()
            while CustomUser.objects.filter(remote_id=new_id).exists():
                new_id = generate_remote_id()
            self.remote_id = new_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.remote_id})"