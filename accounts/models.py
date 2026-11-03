from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    bio = models.TextField(max_length=500, blank=True, default="")
    age = models.PositiveIntegerField(null=True, blank=True)
    location = models.CharField(max_length=80, blank=True, default="")

    def __str__(self):
        return f"Profile of {self.user}"


class LoginRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_records",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.user} @ {self.created}"


def get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
